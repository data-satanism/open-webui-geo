"""One-command GeoTeaser workflow exposed as an Open WebUI built-in tool."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import Request

from open_webui.build_revision import build_revision
from open_webui.services.geotizer.errors import (
    GeotizerOrchestrationError,
)
from open_webui.services.artifacts.geotizer.workflow import (
    AgentCall,
    GisCall,
    VisionEvidenceCall,
    round_usage_scope,
    run_geotizer_workflow,
)
from open_webui.services.artifacts.geotizer.area_request import (
    area_deadline_seconds,
    concurrent_members,
    fill_area,
    render_area_answer,
)
from open_webui.services.artifacts.geotizer.area_workflow import member_filler
from open_webui.services.artifacts.geotizer.run_scope import scoped_metadata
from open_webui.services.artifacts.geotizer.vision import (
    find_vision_tool_record,
    parse_vision_analysis,
)
from open_webui.services.artifacts.geotizer.terminal import (
    StatusSettings,
    attachment_files,
    carry_forward_mode_line,
    card_evidence_sections,
    carry_forward_summary,
    completeness_lines,
    preamble_note,
    failure_details,
    recovered_run_id,
    run_detail_lines,
    target_line,
    _error_result,
    _proxy_download_path,
    _proxy_source_report_paths,
    _terminal_outcome,
)
from open_webui.services.artifacts.geotizer.owner_envelope import (
    execution_mode_for_task,
)
from open_webui.services.core.tasks import AgentTask
from open_webui.utils.geotizer_context_window import geotizer_failure_code
from open_webui.utils.geotizer_run_registry import build_run_registry
from open_webui.utils.geotizer_query_sink import QueryDrain
from open_webui.utils.kb_collection_scope import resolve_kb_scope, visual_source_files
from open_webui.utils.geotizer_rag_runtime import (
    GeoMASRAGDispatcher,
    GeoMASRAGRuntimeSettings,
)

GIS_TOOL_IDS = ('server:mcpgis', 'server:mcp:mcpgis')

log = logging.getLogger(__name__)
GEOMAS_RUNTIME_DATA_DIR = Path(os.getenv('DATA_DIR', Path(__file__).resolve().parents[2] / 'data'))


async def _execute_geomas_retrieval_plan(
    request: Request,
    user,
    plan: Mapping[str, Any],
    collection_names: Sequence[str],
) -> Mapping[str, Any]:
    """Call the same validated handler used by the public typed endpoint."""

    from open_webui.tools.geotizer_retrieval import (
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


def _kb_scope(files: Sequence[Any] | None = None) -> dict[str, Any]:
    """This run's KB collection scope, as the workflow takes it.

    Resolved by `utils.kb_collection_scope.resolve_kb_scope` from the attached files.
    """
    return resolve_kb_scope(files)


def _status_settings(stored: Mapping[str, Any]) -> StatusSettings:
    """The run's narration settings, from the orchestration tool's stored valve row.

    Reads `STATUS_LANGUAGE` and `STATUS_VERBOSITY`; an absent key defaults to
    `ru` and `user` respectively.
    """
    return StatusSettings(
        language=str(stored.get('STATUS_LANGUAGE') or 'ru'),
        verbosity=str(stored.get('STATUS_VERBOSITY') or 'user'),
    )


async def fill_geotizer(
    object_name: str = '',
    project_id: str = '',
    licence_id: str = '',
    licence_layer_id: str = '',
    model_run_id: str = '',
    run_id: str = '',
    allow_draft: bool = True,
    vision_collection_url: str = '',
    run_mode: str = 'clean',
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

    :param object_name: Object or licence-area name; optional with licence_id.
    :param project_id: Optional exact linked GIS project ID.
    :param licence_id: Which licence inside the project, when the project holds
        a registry rather than one object's data. A licence number as a person
        has it (СЛХ025834ТП), spelling ignored. Send it after a run refused
        with gis_project_multi_licence, or alone as the only identity.
    :param licence_layer_id: Which layer to take licence_id from, when one
        number matched in several. Only after licence_ambiguous named them.
    :param model_run_id: Optional exact DataCube run ID.
    :param run_id: Exact run ID from an earlier result, to resume a run that was
        interrupted before it finished. Never invent one, and never send one to
        start over — a new run_id does not produce a clean run. Use run_mode
        for that.
    :param allow_draft: Allow final XLSX with explicit data gaps.
    :param vision_collection_url: Optional exact Open WebUI collection URL or
        ID containing project-specific maps and sections.
    :param run_mode: clean or carry_forward. clean is the default and is what
        "fill it again", "start over" or "заново" means: the card is built only
        from evidence found in this run. carry_forward additionally reuses
        values from previous finalized runs of the same object, which raises
        the completeness figure without adding evidence. Send carry_forward
        only when the user explicitly asks to keep the previous values.
    :return: Markdown result with completeness counts and the download links.
    """
    if __request__ is None or __user__ is None:
        return _error_result(
            'missing_runtime_context',
            'Open WebUI request and user context are required.',
            run_id=run_id,
        )
    if not str(__message_id__ or '').strip():
        log.warning(
            'GeoTeaser run key has no request identity: __message_id__ is absent, '
            'so an identical later request will be served this run instead of a new one'
        )
    if not object_name.strip() and not licence_id.strip():
        return _error_result(
            'object_identity_missing',
            'Нужен object_name — название объекта — или licence_id, номер лицензии.',
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
    started_run: dict[str, Any] = {}
    try:
        gis_call = await _resolve_geotizer_callable(
            __request__,
            user,
            runtime,
        )
        agent_call, status, round_usage_drain = await _build_agent_caller(runtime)
        rag_dispatcher = _build_rag_dispatcher(__request__, user)
        query_drain = QueryDrain()
        vision_evidence_call = await _build_vision_evidence_caller(
            runtime,
            collection_url=vision_collection_url.strip(),
        )
        final = await run_geotizer_workflow(
            build_revision=build_revision(),
            object_name=object_name.strip(),
            project_id=project_id.strip() or None,
            licence_id=licence_id.strip() or None,
            licence_layer_id=licence_layer_id.strip() or None,
            model_run_id=model_run_id.strip() or None,
            run_id=run_id.strip() or None,
            allow_draft=allow_draft,
            run_mode=run_mode.strip() or 'clean',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            query_drain=query_drain,
            round_usage_drain=round_usage_drain,
            vision_evidence_call=vision_evidence_call,
            event_emitter=__event_emitter__,
            parent_chat_id=__chat_id__,
            attempt_key=__message_id__,
            run_registry=build_run_registry(GEOMAS_RUNTIME_DATA_DIR),
            requester_id=str((__user__ or {}).get('id') or ''),
            started_run=started_run,
            owner_fields_per_call=os.getenv('GEOMAS_OWNER_FIELDS_PER_CALL'),
            fill_deadline_seconds=os.getenv('GEOMAS_FILL_DEADLINE_SECONDS'),
            vision_collection_url=vision_collection_url.strip() or None,
            attached_file_ids=visual_source_files(__files__),
            **_kb_scope(__files__),
            status=status,
        )
    except Exception as exc:
        current_run_id = recovered_run_id(started_run, exc, run_id)
        code, overflow = geotizer_failure_code(exc)
        return _error_result(
            code,
            str(exc),
            run_id=current_run_id,
            details={**(failure_details(exc) or {}), **overflow} or None,
        )

    proxy_path = _proxy_download_path(final)
    report_paths = _proxy_source_report_paths(final)
    terminal = _terminal_outcome(final)
    audit = final.get('audit')
    audit = audit if isinstance(audit, Mapping) else {}
    counts = final.get('counts') or audit.get('completeness') or {}
    xlsx = final.get('xlsx') or {}
    carried = carry_forward_summary(final)
    filled = counts.get('filled', 0)
    mode_line = carry_forward_mode_line(carried, filled=filled)
    filled_line = completeness_lines(final)
    detail_lines = run_detail_lines(final, carried_mode_line=mode_line)
    note = preamble_note(final, fallback_run_id=run_id)
    resumed_note = f'{note}\n\n' if note else ''
    result = (
        resumed_note
        + f'GeoTeaser для **{final.get("object_name") or object_name}** '
        f'{terminal["headline"]}.\n\n'
        + filled_line
        + (
        target_line(final)
        + f'- Ошибки audit: {terminal["failed"]}\n'
        f'- Предупреждения audit: {terminal["warnings"]}\n'
        f'- Публикация: {terminal["publication"]}\n'
        + detail_lines
        + f'- Run ID: `{final.get("run_id")}`\n'
        f'- SHA-256: `{xlsx.get("sha256", "")}`\n\n'
        f'[Скачать {"черновик" if not terminal["audit_passed"] else "заполненный"} '
        f'GeoTeaser XLSX]({proxy_path})'
        )
        + card_evidence_sections(final, report_paths)
    )
    if report_paths:
        result += (
            '\n\n'
            f'[Скачать отчёт по источникам PDF]({report_paths["pdf"]})\n\n'
            f'[Скачать отчёт по источникам MD]({report_paths["markdown"]})\n\n'
            f'[Скачать машиночитаемый state.json]({report_paths["state"]})'
        )

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


async def _resolve_geotizer_callable(
    request, user, runtime, operation: str = 'geotizer_fill'
) -> GisCall:
    """A callable for one named operation on the GIS tool server.

    `operation` is `geotizer_fill` (the state machine and `resolve_scope`),
    `geotizer_area_scope` or `geotizer_area_fold`; each accepts only its own
    actions. Raises `GeotizerOrchestrationError` when no configured GIS tool
    server exposes the operation. The returned callable takes the payload as
    keyword arguments, decodes a JSON string result, and raises
    `GeotizerOrchestrationError` when the result is not an object.
    """
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
        if any(name == operation or name.endswith(f'_{operation}') for name in tools):
            break

    entry = next(
        (value for name, value in tools.items() if name == operation or name.endswith(f'_{operation}')),
        None,
    )
    if entry is None:
        raise GeotizerOrchestrationError(
            f'Configured GIS tool server does not expose {operation}'
        )
    callable_ = entry['callable']

    async def call(payload: dict[str, Any]) -> dict[str, Any]:
        raw = await callable_(**payload)
        if isinstance(raw, tuple | list) and raw:
            raw = raw[0]
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise GeotizerOrchestrationError(
                f'{operation} returned {type(raw).__name__}, expected object'
            )
        return raw

    return call


async def _build_vision_evidence_caller(
    runtime: Mapping[str, Any],
    *,
    collection_url: str,
) -> VisionEvidenceCall | None:
    """Load the OCR-owned Geological Vision tool when visual inputs exist."""
    supplied_files = visual_source_files(runtime.get('__files__'))
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


ORCHESTRATOR_TOOL_ID = 'multitask_orchestration'

ORCHESTRATOR_MODE = {
    'specialist_contributor': 'contributor',
    'specialist_owner_completion': 'owner_completion',
    'tool_free_owner': 'tool_free',
}


async def _build_agent_caller(runtime) -> tuple[AgentCall, StatusSettings, Any]:
    """Call specialists through `multitask_orchestration.run_agent_task`.

    Returns the agent caller, the status settings and the orchestrator's
    round-usage scope. The orchestrator's valves and the status settings are
    read from one `Tools.get_tool_valves_by_id` row. The agent name is passed
    to `run_agent_task` unchanged. Raises `GeotizerOrchestrationError` with a
    `missing_runtime_context:` message when the orchestrator Workspace Tool
    cannot be loaded or does not expose `run_agent_task`.
    """
    from open_webui.utils.plugin import load_tool_module_by_id

    try:
        orchestrator, _ = await load_tool_module_by_id(ORCHESTRATOR_TOOL_ID)
    except Exception as exc:  # noqa: BLE001
        raise GeotizerOrchestrationError(
            f'missing_runtime_context: Workspace Tool {ORCHESTRATOR_TOOL_ID!r} could not be '
            f'loaded on this contour, so no specialist can be reached '
            f'({type(exc).__name__}: {exc}).'
        ) from exc

    if not callable(getattr(orchestrator, 'run_agent_task', None)):
        raise GeotizerOrchestrationError(
            f'missing_runtime_context: Workspace Tool {ORCHESTRATOR_TOOL_ID!r} is installed '
            f'but does not expose run_agent_task; this contour is running a version older '
            f'than the one GeoTeaser calls.'
        )

    from open_webui.models.tools import Tools

    stored = await Tools.get_tool_valves_by_id(ORCHESTRATOR_TOOL_ID) or {}
    if hasattr(orchestrator, 'Valves'):
        orchestrator.valves = orchestrator.Valves(**stored)
    status = _status_settings(stored)

    async def call(
        task: AgentTask,
        prompt: str,
        object_name: str,
        datacube: Mapping[str, Any] | None,
    ) -> str:
        mode = ORCHESTRATOR_MODE[execution_mode_for_task(task)]
        return await orchestrator.run_agent_task(
            agent=task.agent,
            prompt=prompt,
            mode=mode,
            original_user_request=f'Заполнить GeoTeaser для {object_name}',
            expected_output='Follow the exact JSON-only output contract in specialist_task.',
            __request__=runtime['__request__'],
            __user__=runtime['__user__'],
            __event_emitter__=runtime['__event_emitter__'],
            __event_call__=runtime['__event_call__'],
            __metadata__=scoped_metadata(runtime['__metadata__']),
            __chat_id__=runtime['__chat_id__'],
            __message_id__=runtime['__message_id__'],
        )

    return call, status, round_usage_scope(orchestrator)


async def _user_model(user_data: dict):
    from open_webui.models.users import UserModel

    return UserModel(**user_data)


def _area_deadline_seconds() -> tuple[float | None, str | None]:
    """`GEOMAS_AREA_DEADLINE_SECONDS`, judged by `area_deadline_seconds`.

    Returns `(seconds or None, note)`; the note is set only when a configured
    value was refused. Unset means no area deadline.
    """
    return area_deadline_seconds(os.getenv('GEOMAS_AREA_DEADLINE_SECONDS'))


def _area_concurrent_members() -> tuple[int, str | None]:
    """`GEOMAS_AREA_CONCURRENT_MEMBERS`, judged by `concurrent_members`.

    Returns `(count, note)`; the count defaults to three and bounds how many
    members fill at once, not how many members an area has.
    """
    return concurrent_members(os.getenv('GEOMAS_AREA_CONCURRENT_MEMBERS'))


async def fill_geoteaser_area(
    object_name: str = '',
    licence_ids: list[str] | None = None,
    licence_layers: dict[str, str] | None = None,
    project_id: str = '',
    area_scope_id: str = '',
    policy_version: str = '',
    calculation_crs: str = '',
    allow_draft: bool = True,
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
    """Fill several licences as one area and fold them into one result.

    Use this for a request such as "Заполни область из лицензий ..." or
    "Заполни Лекын-Тальбейскую площадь". For a single object use
    `fill_geotizer` instead. This tool fills members concurrently, a bounded
    number at a time, and then aggregates. The cost it states comes from
    `cost_phrase`, as a lower bound; quote that figure, never compute one.

    When neither licence_ids nor a resolvable name is given the tool searches,
    and when the search finds several licences it ASKS which — it never picks.

    :param object_name: Area or licence-area name to search for, when the
        licence numbers are not known. A name matching several licences returns
        a question listing them and what filling all of them would cost.
    :param licence_ids: Exact licence numbers to fill as one area, as a person
        has them (МАГ03394БЭ). Supplied, nothing is searched and nothing is
        asked. A number that matches nothing, or matches several layers,
        refuses the whole area rather than filling the rest.
    :param licence_layers: Which layer to use for a licence that lives in
        several, keyed by licence number:
        {"МАГ03395БЭ": "Licenses_2024_2025"}. Send it only when a refusal named
        the layers for that licence. Per licence and never shared — five layers
        for one number says nothing about where another lives — and the layers
        are not merged: they are states of a licence, current, annulled and
        junior-programme, with different geometries and dates.
    :param project_id: Optional exact linked GIS project ID holding the members.
    :param area_scope_id: Identifier for this area, recorded on the manifest and
        on the aggregation result so the run can be found again.
    :param policy_version: The aggregation policy to fold under. Send only a
        value the user named. Omitted, the run uses the policy this build ships
        and says so in its answer and on its manifest — which is a resolved
        value, not a hidden default: the result reproduces exactly because the
        policy it was folded under is recorded.
    :param calculation_crs: Projected CRS every overlap is measured in. Send
        only a value the user named. Omitted, the run takes the UTM zone of the
        area's centroid and says so, recording the zone and how many zones the
        members span. A geographic CRS is refused rather than replaced: an area
        in square degrees is not an area, and overriding a value the user named
        is not this tool's to do.
    :param allow_draft: Allow a member's final XLSX with explicit data gaps.
    :return: Markdown: the members with their run ids, and the folded summary.
    """
    if __request__ is None or __user__ is None:
        return _error_result(
            'missing_runtime_context',
            'Open WebUI request and user context are required.',
            run_id=None,
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
        gis_call = await _resolve_geotizer_callable(__request__, user, runtime)
        scope_call = await _resolve_geotizer_callable(
            __request__, user, runtime, 'geotizer_area_scope'
        )
        fold_call = await _resolve_geotizer_callable(
            __request__, user, runtime, 'geotizer_area_fold'
        )
        agent_call, status, round_usage_drain = await _build_agent_caller(runtime)
        area_deadline, area_deadline_note = _area_deadline_seconds()
        area_concurrency, area_concurrency_note = _area_concurrent_members()
        answer = await fill_area(
            gis_call=gis_call,
            scope_call=scope_call,
            fold_call=fold_call,
            member_fill=member_filler(
                fill=run_geotizer_workflow,
                build_revision=build_revision(),
                model_run_id=None,
                run_id=None,
                allow_draft=allow_draft,
                run_mode='clean',
                gis_call=gis_call,
                agent_call=agent_call,
                rag_dispatcher=_build_rag_dispatcher(__request__, user),
                per_member={'query_drain': QueryDrain},
                round_usage_drain=round_usage_drain,
                parent_chat_id=__chat_id__,
                attempt_key=__message_id__,
                status=status,
                event_emitter=__event_emitter__,
                owner_fields_per_call=os.getenv('GEOMAS_OWNER_FIELDS_PER_CALL'),
                fill_deadline_seconds=os.getenv('GEOMAS_FILL_DEADLINE_SECONDS'),
            ),
            object_name=object_name.strip(),
            licence_ids=licence_ids or (),
            licence_layers=licence_layers or None,
            project_id=project_id.strip(),
            area_scope_id=area_scope_id.strip(),
            policy_version=policy_version.strip(),
            calculation_crs=calculation_crs.strip(),
            area_deadline_seconds=area_deadline,
            area_concurrent_members=area_concurrency,
            area_deadline_note=area_deadline_note or '',
            area_concurrency_note=area_concurrency_note or '',
            event_emitter=__event_emitter__,
            status=status,
        )
    except Exception as exc:
        return _error_result(type(exc).__name__, str(exc), run_id=None)
    return render_area_answer(answer)
