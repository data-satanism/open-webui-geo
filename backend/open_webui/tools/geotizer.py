"""One-command GeoTeaser workflow exposed as an Open WebUI built-in tool."""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import Request

from open_webui.services.geotizer.errors import (
    GeotizerOrchestrationError,
)
from open_webui.services.artifacts.geotizer.workflow import (
    AgentCall,
    GisCall,
    VisionEvidenceCall,
    run_geotizer_workflow,
)
from open_webui.services.artifacts.geotizer.vision import (
    find_vision_tool_record,
    parse_vision_analysis,
)
from open_webui.services.artifacts.geotizer.terminal import (
    attachment_files,
    _error_result,
    _proxy_download_path,
    _proxy_source_report_paths,
    _terminal_outcome,
)
from open_webui.services.artifacts.geotizer.owner_envelope import (
    execution_mode_for_task,
    normalize_delegator_message,
    owner_completion_valves,
)
from open_webui.services.core.tasks import AgentTask
from open_webui.services.core.text import extract_json_object
from open_webui.utils.geotizer_rag_runtime import (
    GeoMASRAGDispatcher,
    GeoMASRAGRuntimeSettings,
)

GIS_TOOL_IDS = ('server:mcpgis', 'server:mcp:mcpgis')
DELEGATOR_TOOL_ID = 'mainagent_tool_yulong'
SUB_AGENT_TOOL_ID = 'sub_agent'
# GEOMAS-DEF-001. `skilledagent-sakana` exists in no contour, so every
# owner-completion and tool-free call raised `Model not found` and came back
# classified retryable. `skilledagent-final` is the id that resolves.
SKILLED_MODEL_ID = 'skilledagent-final'

log = logging.getLogger(__name__)
GEOMAS_RUNTIME_DATA_DIR = Path(os.getenv('DATA_DIR', Path(__file__).resolve().parents[2] / 'data'))


async def _execute_geomas_retrieval_plan(
    request: Request,
    user,
    plan: Mapping[str, Any],
    collection_names: Sequence[str],
) -> Mapping[str, Any]:
    """Call the same validated handler used by the public typed endpoint."""

    from open_webui.routers.retrieval import (
        GeoMASRetrievalPlanForm,
        query_geomas_retrieval_plan_handler,
    )

    return await query_geomas_retrieval_plan_handler(
        request,
        GeoMASRetrievalPlanForm(
            plan=dict(plan),
            collection_names=list(collection_names),
        ),
        user,
    )


async def query_geomas_retrieval_plan(
    plan: dict[str, Any],
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """Execute an exact GeoMAS RetrievalPlan against the isolated v2 index.

    This callable is exposed to knowledge agents only while the active v2
    feature flag is enabled. The collection allowlist comes from server-side
    configuration, never from model-provided arguments.

    :param plan: Complete geomas.retrieval_plan.v1 object from GeoTeaser.
    :return: One geomas.retrieval_trace.v1 JSON object.
    """

    if __request__ is None or not __user__:
        return json.dumps(
            {'error': {'code': 'missing_runtime_context'}},
            ensure_ascii=False,
        )
    settings = GeoMASRAGRuntimeSettings.from_env(data_dir=GEOMAS_RUNTIME_DATA_DIR)
    errors = settings.configuration_errors()
    if settings.mode != 'active' or errors:
        return json.dumps(
            {
                'error': {
                    'code': 'geomas_rag_v2_not_executable',
                    'configuration_errors': list(errors),
                }
            },
            ensure_ascii=False,
        )
    user = await _user_model(__user__)
    trace = await _execute_geomas_retrieval_plan(
        __request__,
        user,
        plan,
        settings.collections,
    )
    return json.dumps(trace, ensure_ascii=False)


def _build_rag_dispatcher(
    request: Request,
    user,
) -> GeoMASRAGDispatcher | None:
    settings = GeoMASRAGRuntimeSettings.from_env(data_dir=GEOMAS_RUNTIME_DATA_DIR)
    errors = settings.configuration_errors()
    if settings.mode == 'disabled':
        return None
    if settings.mode in {'active', 'invalid'} and errors:
        raise GeotizerOrchestrationError('; '.join(errors))
    if settings.mode == 'shadow' and errors:
        log.error('GeoMAS RAG shadow configuration error: %s', '; '.join(errors))

    async def query_call(
        plan: Mapping[str, Any],
        collection_names: Sequence[str],
    ) -> Mapping[str, Any]:
        return await _execute_geomas_retrieval_plan(
            request,
            user,
            plan,
            collection_names,
        )

    return GeoMASRAGDispatcher(settings, query_call)


async def fill_geotizer(
    object_name: str,
    project_id: str = '',
    model_run_id: str = '',
    run_id: str = '',
    allow_draft: bool = True,
    vision_collection_url: str = '',
    __request__: Request = None,
    __user__: dict = None,
    __event_emitter__=None,
    __event_call__=None,
    __metadata__: dict = None,
    __chat_id__: str = None,
    __message_id__: str = None,
    __model_knowledge__: list[dict] = None,
    __files__: list[dict] = None,
) -> str:
    """Fill GeoTeaser Object through the deterministic GIS state machine.

    Use this function for a user request such as "Заполни Геотизер для ...".
    It is the only tool the parent model should call for the complete workflow:
    the function resolves the GIS project, collects bounded KB/WEB/GIS evidence,
    submits all exact-owner batches, runs the final audit and returns a download
    link for the rendered XLSX. Do not call specialist or Excel tools manually
    before or after this function.

    :param object_name: Geological object or licence-area name.
    :param project_id: Optional exact linked GIS project ID.
    :param model_run_id: Optional exact DataCube run ID.
    :param run_id: Optional existing GeoTeaser run ID to resume.
    :param allow_draft: Allow final XLSX with explicit data gaps.
    :param vision_collection_url: Optional exact Open WebUI collection URL or
        ID containing project-specific maps and sections.
    :return: Markdown result with completeness counts and XLSX download link.
    """
    if __request__ is None or __user__ is None:
        return _error_result(
            'missing_runtime_context',
            'Open WebUI request and user context are required.',
            run_id=run_id,
        )
    if not object_name.strip():
        return _error_result(
            'missing_object_name',
            'object_name is required.',
            run_id=run_id,
        )

    user = await _user_model(__user__)
    runtime = {
        '__request__': __request__,
        '__user__': __user__,
        '__event_emitter__': __event_emitter__,
        '__event_call__': __event_call__,
        '__metadata__': __metadata__ or {},
        '__chat_id__': __chat_id__,
        '__message_id__': __message_id__,
        '__model_knowledge__': __model_knowledge__ or [],
        '__files__': __files__ or [],
    }
    try:
        gis_call = await _resolve_geotizer_callable(
            __request__,
            user,
            runtime,
        )
        agent_call = await _build_agent_caller(runtime)
        rag_dispatcher = _build_rag_dispatcher(__request__, user)
        vision_evidence_call = await _build_vision_evidence_caller(
            runtime,
            collection_url=vision_collection_url.strip(),
        )
        final = await run_geotizer_workflow(
            object_name=object_name.strip(),
            project_id=project_id.strip() or None,
            model_run_id=model_run_id.strip() or None,
            run_id=run_id.strip() or None,
            allow_draft=allow_draft,
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            vision_evidence_call=vision_evidence_call,
            event_emitter=__event_emitter__,
            parent_chat_id=__chat_id__,
            attempt_key=__message_id__,
        )
    except Exception as exc:
        current_run_id = getattr(exc, 'run_id', None) or run_id
        return _error_result(
            type(exc).__name__,
            str(exc),
            run_id=current_run_id,
            details=getattr(exc, 'details', None),
        )

    proxy_path = _proxy_download_path(final)
    report_paths = _proxy_source_report_paths(final)
    terminal = _terminal_outcome(final)
    audit = final.get('audit')
    audit = audit if isinstance(audit, Mapping) else {}
    counts = final.get('counts') or audit.get('completeness') or {}
    fill_quality = final.get('fill_quality') or {}
    xlsx = final.get('xlsx') or {}
    result = (
        f'GeoTeaser для **{final.get("object_name") or object_name}** '
        f'{terminal["headline"]}.\n\n'
        f'- Заполнено: {counts.get("filled", 0)}\n'
        f'- Строгая полнота: {fill_quality.get("strict_fill_percent", 0)}% '
        f'(цель 80%: {"достигнута" if fill_quality.get("target_met") else "не достигнута"})\n'
        f'- Не найдено: {counts.get("not_found", 0)}\n'
        '- Требует экспертной проверки: '
        f'{counts.get("requires_expert_review", 0)}\n'
        f'- Ошибки audit: {terminal["failed"]}\n'
        f'- Предупреждения audit: {terminal["warnings"]}\n'
        f'- Публикация: {terminal["publication"]}\n'
        f'- Run ID: `{final.get("run_id")}`\n'
        f'- SHA-256: `{xlsx.get("sha256", "")}`\n\n'
        f'[Скачать {"черновик" if not terminal["audit_passed"] else "заполненный"} '
        f'GeoTeaser XLSX]({proxy_path})'
    )
    if report_paths:
        result += (
            '\n\n'
            f'[Скачать отчёт по источникам PDF]({report_paths["pdf"]})\n\n'
            f'[Скачать отчёт по источникам MD]({report_paths["markdown"]})\n\n'
            f'[Скачать машиночитаемый state.json]({report_paths["state"]})'
        )

    # CORE-BOUNDARY-01 action 7. An addition to the download API, never a
    # replacement: the links above are the access route and survive the chat.
    # The attachment is a convenience, so a failure to emit it must not lose a
    # finished run -- the result is already built and is returned either way.
    if __event_emitter__:
        try:
            files = attachment_files(
                proxy_path,
                report_paths,
                object_name=str(final.get('object_name') or object_name),
            )
            if files:
                await __event_emitter__({'type': 'chat:message:files', 'data': {'files': files}})
        except Exception:
            log.warning('GeoTeaser: could not attach the artefacts to the message', exc_info=True)

    return result


async def _resolve_geotizer_callable(request, user, runtime) -> GisCall:
    from open_webui.utils.tools import get_tools

    tools: dict[str, dict] = {}
    for tool_id in GIS_TOOL_IDS:
        resolved = await get_tools(
            request,
            [tool_id],
            user,
            {
                '__user__': runtime['__user__'],
                '__event_emitter__': runtime['__event_emitter__'],
                '__event_call__': runtime['__event_call__'],
                '__metadata__': runtime['__metadata__'],
                '__request__': request,
                '__chat_id__': runtime['__chat_id__'],
                '__message_id__': runtime['__message_id__'],
                '__model__': {},
                '__messages__': [],
                '__files__': [],
            },
        )
        tools.update(resolved)
        if any(name == 'geotizer_fill' or name.endswith('_geotizer_fill') for name in tools):
            break

    entry = next(
        (value for name, value in tools.items() if name == 'geotizer_fill' or name.endswith('_geotizer_fill')),
        None,
    )
    if entry is None:
        raise GeotizerOrchestrationError('Configured GIS tool server does not expose geotizer_fill')
    callable_ = entry['callable']

    async def call(payload: dict[str, Any]) -> dict[str, Any]:
        raw = await callable_(**payload)
        if isinstance(raw, tuple | list) and raw:
            raw = raw[0]
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise GeotizerOrchestrationError(f'geotizer_fill returned {type(raw).__name__}, expected object')
        return raw

    return call


async def _build_vision_evidence_caller(
    runtime: Mapping[str, Any],
    *,
    collection_url: str,
) -> VisionEvidenceCall | None:
    """Load the OCR-owned Geological Vision tool when visual inputs exist."""
    supplied_files = list(runtime.get('__files__') or [])
    if not supplied_files and not collection_url:
        return None

    from open_webui.models.tools import Tools
    from open_webui.utils.plugin import load_tool_module_by_id

    selected = find_vision_tool_record(await Tools.get_tools())
    if selected is None:
        raise GeotizerOrchestrationError(
            'GeoTeaser received visual sources, but the GeoMAS Geological Vision tool is not installed.'
        )

    vision_tool, _ = await load_tool_module_by_id(selected.id)
    valve_values = await Tools.get_tool_valves_by_id(selected.id) or {}
    if hasattr(vision_tool, 'Valves'):
        vision_tool.valves = vision_tool.Valves(**valve_values)
    analyze = getattr(
        vision_tool,
        'analyze_geological_materials',
        None,
    )
    prepare = getattr(
        vision_tool,
        '_prepare_geotizer_visual_evidence',
        None,
    )
    if not callable(analyze) or not callable(prepare):
        raise GeotizerOrchestrationError(
            'Installed GeoMAS Geological Vision tool does not implement the GeoTeaser evidence contract.'
        )

    analysis_payload: Mapping[str, Any] | None = None
    analysis_project_id: str | None = None

    async def call(
        object_name: str,
        project_id: str | None,
        next_batch: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        nonlocal analysis_payload, analysis_project_id
        if analysis_payload is None:
            raw = await analyze(
                task=(
                    'Извлеки из приложенных карт и разрезов только '
                    'проверяемые сведения для заполнения Геотизера объекта '
                    f'{object_name}.'
                ),
                knowledge_collection_url=collection_url,
                project_id=project_id or '',
                output_format='evidence_json',
                __files__=supplied_files,
                __request__=runtime.get('__request__'),
            )
            analysis_payload = parse_vision_analysis(raw)
            analysis_project_id = project_id
        elif analysis_project_id != project_id:
            raise GeotizerOrchestrationError('Geological Vision analysis project changed inside one GeoTeaser run.')

        project_match = 'project_specific_source' if supplied_files and not collection_url else 'unverified'
        prepared = prepare(
            analysis_payload,
            bounded_fields=list(next_batch.get('fields') or []),
            object_name=object_name,
            project_id=project_id or '',
            project_match=project_match,
        )
        if not isinstance(prepared, Mapping):
            raise GeotizerOrchestrationError('Geological Vision GeoTeaser evidence must be an object.')
        return dict(prepared)

    return call


async def _build_agent_caller(runtime) -> AgentCall:
    from open_webui.models.tools import Tools
    from open_webui.utils.plugin import load_tool_module_by_id

    delegator, _ = await load_tool_module_by_id(DELEGATOR_TOOL_ID)
    delegator_valves = await Tools.get_tool_valves_by_id(DELEGATOR_TOOL_ID) or {}
    if hasattr(delegator, 'Valves'):
        delegator.valves = delegator.Valves(**delegator_valves)
    owner_delegator = copy.copy(delegator)
    if hasattr(delegator, 'Valves'):
        owner_delegator.valves = delegator.Valves(
            **owner_completion_valves(
                delegator.valves.model_dump(),
            )
        )
    original_extract_message = getattr(delegator, '_extract_chat_history_message', None)
    if callable(original_extract_message):

        def extract_normalized_message(chat_data, message_id):
            return normalize_delegator_message(original_extract_message(chat_data, message_id))

        delegator._extract_chat_history_message = extract_normalized_message

    sub_agent, _ = await load_tool_module_by_id(SUB_AGENT_TOOL_ID)
    sub_agent_valves = await Tools.get_tool_valves_by_id(SUB_AGENT_TOOL_ID) or {}
    if hasattr(sub_agent, 'Valves'):
        sub_agent.valves = sub_agent.Valves(**sub_agent_valves)
        sub_agent.valves.DEFAULT_MODEL = SKILLED_MODEL_ID
        sub_agent.valves.AVAILABLE_TOOL_IDS = '__geotizer_no_external_tools__'
        for name in (
            'ENABLE_TIME_TOOLS',
            'ENABLE_WEB_TOOLS',
            'ENABLE_IMAGE_TOOLS',
            'ENABLE_KNOWLEDGE_TOOLS',
            'ENABLE_CHAT_TOOLS',
            'ENABLE_MEMORY_TOOLS',
            'ENABLE_NOTES_TOOLS',
            'ENABLE_CHANNELS_TOOLS',
            'ENABLE_TERMINAL_TOOLS',
            'ENABLE_CODE_INTERPRETER_TOOLS',
            'ENABLE_SKILLS_TOOLS',
            'ENABLE_TASK_TOOLS',
            'ENABLE_AUTOMATION_TOOLS',
            'ENABLE_CALENDAR_TOOLS',
        ):
            if hasattr(sub_agent.valves, name):
                setattr(sub_agent.valves, name, False)

    async def call(
        task: AgentTask,
        prompt: str,
        object_name: str,
        datacube: Mapping[str, Any] | None,
    ) -> str:
        execution_mode = execution_mode_for_task(task)
        if execution_mode == 'tool_free_owner':
            model = runtime['__request__'].app.state.MODELS.get(
                SKILLED_MODEL_ID,
                {'id': SKILLED_MODEL_ID},
            )
            result = await sub_agent.run_sub_agent(
                description=(f'GeoTeaser {task.task_id}: {task.producer} tool-free owner decision'),
                prompt=prompt,
                __user__=runtime['__user__'],
                __request__=runtime['__request__'],
                __model__=model,
                __metadata__=runtime['__metadata__'],
                __id__='builtin:fill_geotizer',
                __event_emitter__=runtime['__event_emitter__'],
                __event_call__=runtime['__event_call__'],
                __chat_id__=runtime['__chat_id__'],
                __message_id__=runtime['__message_id__'],
                __messages__=[],
            )
            outer = extract_json_object(result)
            return str(outer.get('result') or result)

        active_delegator = owner_delegator if execution_mode == 'specialist_owner_completion' else delegator
        return await active_delegator.ask_specialist_agent(
            agent=task.kind,
            task=prompt,
            original_user_request=f'Заполнить GeoTeaser для {object_name}',
            expected_output=('Follow the exact JSON-only output contract in specialist_task.'),
            __event_emitter__=runtime['__event_emitter__'],
            __event_call__=runtime['__event_call__'],
            __request__=runtime['__request__'],
            __user__=runtime['__user__'],
            __metadata__=runtime['__metadata__'],
            __chat_id__=runtime['__chat_id__'],
            __message_id__=runtime['__message_id__'],
        )

    return call


async def _user_model(user_data: dict):
    from open_webui.models.users import UserModel

    return UserModel(**user_data)
