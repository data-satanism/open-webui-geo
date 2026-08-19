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
    StatusSettings,
    attachment_files,
    carry_forward_mode_line,
    carry_forward_summary,
    card_docx_link,
    completeness_lines,
    conflict_section,
    run_notes_section,
    preamble_note,
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
from open_webui.utils.kb_collection_scope import resolve_kb_scope, visual_source_files
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


def _kb_scope(files: Sequence[Any] | None = None) -> dict[str, Any]:
    """This run's KB collection scope, as the workflow takes it.

    Only this adapter may read it: `services/` imports no `open_webui` and no
    environment. The resolution itself lives in `utils/kb_collection_scope.py`
    beside the allowlist it unions with; what belongs here is the call.
    """
    return resolve_kb_scope(files)


def _status_settings(stored: Mapping[str, Any]) -> StatusSettings:
    """The two valves that decide how the run narrates itself.

    Off the orchestration tool's stored row and nothing of GeoTeaser's own,
    because the specialist lines and these lines are two halves of one
    transcript: a second setting here would let an operator switch one half and
    watch the other keep speaking English. Absent keys fall through to the same
    `ru` and `user` that tool ships, so an untouched contour gets one language
    rather than two.
    """
    return StatusSettings(
        language=str(stored.get('STATUS_LANGUAGE') or 'ru'),
        verbosity=str(stored.get('STATUS_VERBOSITY') or 'user'),
    )


async def fill_geotizer(
    object_name: str,
    project_id: str = '',
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

    :param object_name: Geological object or licence-area name.
    :param project_id: Optional exact linked GIS project ID.
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
        # Not fatal, and not silent. Without a request identity the run key is
        # input-only, which is the composition that made an object fillable
        # exactly once -- so a caller in that state should be findable in a log
        # rather than discovered from a user saying the card never changes.
        log.warning(
            'GeoTeaser run key has no request identity: __message_id__ is absent, '
            'so an identical later request will be served this run instead of a new one'
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
        agent_call, status = await _build_agent_caller(runtime)
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
            run_mode=run_mode.strip() or 'clean',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            vision_evidence_call=vision_evidence_call,
            event_emitter=__event_emitter__,
            parent_chat_id=__chat_id__,
            # The request, not the question. Without it two identical commands
            # are one key forever: the second binds to the first run and the
            # card comes back with yesterday's id, coverage and link.
            attempt_key=__message_id__,
            # CORE-BOUNDARY-01 action 6. `None` here is the pre-existing
            # behaviour -- one run per command -- and is what an unwritable
            # DATA_DIR or `GEOMAS_RUN_IDEMPOTENCY=false` produces.
            run_registry=build_run_registry(GEOMAS_RUNTIME_DATA_DIR),
            # The run collects evidence as this user, bounded by their grants.
            # Without them in the key the binding is deployment-wide and the
            # second asker gets the first asker's evidence.
            requester_id=str((__user__ or {}).get('id') or ''),
            # `resolve_owner_fields_per_call` says why this is not a valve.
            owner_fields_per_call=os.getenv('GEOMAS_OWNER_FIELDS_PER_CALL'),
            vision_collection_url=vision_collection_url.strip() or None,
            # The items verbatim, not `item['id']`. Reading one field here threw
            # away every shape that nests or omits it, and `attached_source_fingerprints`
            # is where knowing the shapes belongs -- the adapter's job is to hand
            # over what it was given.
            attached_file_ids=visual_source_files(__files__),
            # Configuration, read here because the core has no environment.
            # Sent on every run, including when nothing is configured: a run
            # that says "unconfigured" is reporting that its corpus was the
            # fifty most recently touched knowledge bases, which is the fact a
            # later reader needs and the one no run has ever carried.
            **_kb_scope(__files__),
            # Off the orchestration tool's stored row, read once beside the
            # model valves, so the specialist lines and the GeoTeaser lines in
            # the same message answer to one switch.
            status=status,
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
    carried = carry_forward_summary(final)
    filled = counts.get('filled', 0)
    mode_line = carry_forward_mode_line(carried, filled=filled)
    # GT-GIS-01. Said on the card, not only in the state: a run that reports 343
    # filled of which 339 came from another card has found four facts, and a
    # reader who is not told cannot know which number they are looking at.
    # All five statuses, and what `filled` is made of. Built in the core: five
    # labels and a version-skew branch is rendering, and the boundary contract
    # keeps rendering out of the Workspace copy.
    filled_line = completeness_lines(final)
    # Above the card, not below it: the reader's question is why this looks
    # like the run they already have, and the answer has to arrive before the
    # numbers that prompted it.
    note = preamble_note(final, fallback_run_id=run_id)
    resumed_note = f'{note}\n\n' if note else ''
    result = (
        resumed_note
        + f'GeoTeaser для **{final.get("object_name") or object_name}** '
        f'{terminal["headline"]}.\n\n'
        + filled_line
        + (
        f'- Строгая полнота: {fill_quality.get("strict_fill_percent", 0)}% '
        f'(цель 80%: {"достигнута" if fill_quality.get("target_met") else "не достигнута"})\n'
        f'- Ошибки audit: {terminal["failed"]}\n'
        f'- Предупреждения audit: {terminal["warnings"]}\n'
        f'- Публикация: {terminal["publication"]}\n'
        + mode_line
        + f'- Run ID: `{final.get("run_id")}`\n'
        f'- SHA-256: `{xlsx.get("sha256", "")}`\n\n'
        f'[Скачать {"черновик" if not terminal["audit_passed"] else "заполненный"} '
        f'GeoTeaser XLSX]({proxy_path})'
        )
        # The card in both formats, then the evidence behind it -- the order
        # `attachment_files` already puts the same five artefacts in.
        + card_docx_link(report_paths)
        # GT-4 puts the disagreements ahead of the completeness figure, and
        # GT-3a requires all four statuses. Neither was reachable: the card
        # never carried `conflicted` at all.
        + conflict_section(final)
        + run_notes_section(final)
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


async def _build_agent_caller(runtime) -> tuple[AgentCall, StatusSettings]:
    """Call specialists through `multitask_orchestration.run_agent_task`.

    Returns the caller and the status settings, because both are read out of
    one `get_tool_valves_by_id` row and it has to stay one row. The orchestrator
    narrates the specialist half of the run from `STATUS_LANGUAGE` and
    `STATUS_VERBOSITY`; GeoTeaser narrates the rest. A second fetch, or a second
    place those two names are read, is how one message ends up half Russian.

    The agent name goes across verbatim. Nothing is translated on the way, and
    nothing here checks the name against a list -- `run_agent_task` refuses an
    agent it has no model valve and no tool surface for, and says which it
    serves. A `PRODUCER_KIND_MAP` valve was read here for one round; it was the
    second place routing could be wrong, and both of the outages this work
    caused came from that second place.

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

    from open_webui.models.tools import Tools

    # Loading a module is not the same as configuring it. load_tool_module_by_id
    # returns whatever Tools() constructed, so every valve an operator set in
    # Workspace stays in the database unless it is read back explicitly. Without
    # this, GIS_MODEL is the class default, the default is empty, and the API
    # answers `404: Model '' was not found` -- which reads downstream as "the
    # specialist found nothing" and renders a card at 5.1%.
    #
    # The repoint that replaced the two-delegator block carried the load and
    # dropped the hydration; `Current_Geomas` does it at :1323 and :1342, and
    # `_build_vision_evidence_caller` does it thirty lines above. The pattern was
    # known, applied next door, and still lost -- because nothing asserted it.
    #
    # Fetched outside the `Valves` guard, which now covers the hydration alone.
    # Only the hydration needs a `Valves` class -- with none there is nothing to
    # construct. The status valves are a different question: the row is what the
    # operator set whatever the loaded build declares, and a build with no
    # `Valves` class is precisely the old orchestrator whose half of the
    # transcript would then be narrated in a language nobody chose. One fetch,
    # because two could be served from either side of a valve edit.
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
            __metadata__=runtime['__metadata__'],
            __chat_id__=runtime['__chat_id__'],
            __message_id__=runtime['__message_id__'],
        )

    return call, status


async def _user_model(user_data: dict):
    from open_webui.models.users import UserModel

    return UserModel(**user_data)
