"""One-command GeoTeaser workflow exposed as an Open WebUI built-in tool."""

from __future__ import annotations

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
)
from open_webui.services.core.tasks import AgentTask
from open_webui.utils.geotizer_run_registry import build_run_registry
from open_webui.utils.geotizer_rag_runtime import (
    GeoMASRAGDispatcher,
    GeoMASRAGRuntimeSettings,
)

GIS_TOOL_IDS = ('server:mcpgis', 'server:mcp:mcpgis')
# `SKILLED_MODEL_ID` stood here until the delegator repoint. It existed to be
# written into the retired `sub_agent` tool's `DEFAULT_MODEL` valve; with that
# write gone, this adapter names no model at all. Model selection belongs to
# Multitask Orchestration, which resolves `agent='skilled'` through its own
# `SKILLED_MODEL` valve -- and GEOMAS-DEF-001's correction of that valve to
# `skilledagent-final` is recorded in
# `GMM/operations/gt-conv-01/geomas-def-001-multitask-patch.json`, against a
# tool this repository does not hold. Keeping a second copy here would be a
# constant no code reads, and two places for one fact to drift apart.

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
            # CORE-BOUNDARY-01 action 6. `None` here is the pre-existing
            # behaviour -- one run per command -- and is what an unwritable
            # DATA_DIR or `GEOMAS_RUN_IDEMPOTENCY=false` produces.
            run_registry=build_run_registry(GEOMAS_RUNTIME_DATA_DIR),
            # The run collects evidence as this user, bounded by their grants.
            # Without them in the key the binding is deployment-wide and the
            # second asker gets the first asker's evidence.
            requester_id=str((__user__ or {}).get('id') or ''),
            vision_collection_url=vision_collection_url.strip() or None,
            # The items verbatim, not `item['id']`. Reading one field here threw
            # away every shape that nests or omits it, and `attached_source_fingerprints`
            # is where knowing the shapes belongs -- the adapter's job is to hand
            # over what it was given.
            attached_file_ids=list(__files__ or []),
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


# The orchestrator that replaced the HTTP sub-chat delegator. Kept as a
# constant, not a literal, so a contour that names it differently is one line.
ORCHESTRATOR_TOOL_ID = 'multitask_orchestration'

# `execution_mode_for_task` speaks the GeoTeaser batch's language; `run_agent_task`
# speaks the orchestrator's. One mapping, in one place.
ORCHESTRATOR_MODE = {
    'specialist_contributor': 'contributor',
    'specialist_owner_completion': 'owner_completion',
    'tool_free_owner': 'tool_free',
}


async def _build_agent_caller(runtime) -> AgentCall:
    """Call specialists through `multitask_orchestration.run_agent_task`.

    This used to load two superseded tools by id: `mainagent_tool_yulong`, the
    HTTP sub-chat delegator that Multitask Orchestration replaced, and
    `sub_agent`, which is not in this path at all. It mutated the second's
    `DEFAULT_MODEL`, switched fourteen of its `ENABLE_*_TOOLS` valves off one by
    one, and monkey-patched `_extract_chat_history_message` onto the first. If
    either tool is absent from a contour, `load_tool_module_by_id` raises and
    every GeoTeaser run fails before its first batch.

    `run_agent_task` is the seam the orchestrator publishes for exactly this --
    "programmatic entry point for other tools", plain data in and text out. None
    of the contortions survive it: `owner_completion` and `tool_free` return no
    tools by construction, because `AGENT_CATEGORIES['skilled']` is empty, which
    is what the valve-stripping above was reaching for.

    It goes through `load_tool_module_by_id` rather than importing a service,
    because the orchestrator is still a Workspace Tool in `webui.db` and no
    service exists to import (§2 of the review). When it is extracted, this is
    the one function that changes.
    """
    from open_webui.utils.plugin import load_tool_module_by_id

    try:
        orchestrator, _ = await load_tool_module_by_id(ORCHESTRATOR_TOOL_ID)
    except Exception as exc:  # noqa: BLE001
        # The absent case is the whole reason this was a P0. It has to be a
        # named result the run can report, not a KeyError out of a plugin loader.
        #
        # The cause is carried in the message, not only chained: `fill_geotizer`
        # formats `str(exc)` into the terminal envelope and never walks
        # `__cause__`, so a tool that is installed but fails to import would
        # otherwise reach the operator as "is not installed on this contour" with
        # the actual ImportError nowhere in the output.
        raise GeotizerOrchestrationError(
            f'missing_runtime_context: Workspace Tool {ORCHESTRATOR_TOOL_ID!r} could not be '
            f'loaded on this contour, so no specialist can be reached '
            f'({type(exc).__name__}: {exc}).'
        ) from exc

    # Loading is not the same as exposing. `prompt-verification.md` §12.7
    # describes this seam as `load_tool_module_by_id` then
    # `getattr(module, "run_agent_task")` "with an explicit error if the
    # attribute is missing", and §13.8 names the operator-visible failure
    # verbatim. Guarding only the load left a contour running an older
    # orchestrator to fail on its first owner batch with a bare `AttributeError`,
    # which `fill_geotizer`'s blanket handler turns into
    # `_error_result('AttributeError', ...)` -- unattributed, and after the run
    # has already done work.
    if not callable(getattr(orchestrator, 'run_agent_task', None)):
        raise GeotizerOrchestrationError(
            f'missing_runtime_context: Workspace Tool {ORCHESTRATOR_TOOL_ID!r} is installed '
            f'but does not expose run_agent_task; this contour is running a version older '
            f'than the one GeoTeaser calls.'
        )

    async def call(
        task: AgentTask,
        prompt: str,
        object_name: str,
        datacube: Mapping[str, Any] | None,
    ) -> str:
        mode = ORCHESTRATOR_MODE[execution_mode_for_task(task)]
        return await orchestrator.run_agent_task(
            agent=task.kind,
            prompt=prompt,
            mode=mode,
            original_user_request=f'Заполнить GeoTeaser для {object_name}',
            expected_output='Follow the exact JSON-only output contract in specialist_task.',
            __request__=runtime['__request__'],
            __user__=runtime['__user__'],
            __event_emitter__=runtime['__event_emitter__'],
            __event_call__=runtime['__event_call__'],
            __metadata__=runtime['__metadata__'],
            __chat_id__=runtime['__chat_id__'],
            __message_id__=runtime['__message_id__'],
        )

    return call


async def _user_model(user_data: dict):
    from open_webui.models.users import UserModel

    return UserModel(**user_data)
