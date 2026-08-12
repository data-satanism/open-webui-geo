"""One-command GeoTeaser workflow exposed as an Open WebUI built-in tool."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import Request

from open_webui.services.geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
)
from open_webui.services.artifacts.geotizer.observability import (
    owner_attempt_diagnostic,
)
from open_webui.services.artifacts.geotizer.prompts import (
    _batch_quality_rules,
    _contributor_prompt,
    _contributors_for_batch,
    _gis_infrastructure_rules,
    _needs_deterministic_infrastructure,
    _object_profile_prompt,
    _owner_prompt,
    _structured_contributor_contract,
)
from open_webui.services.artifacts.geotizer.terminal import (
    _emit_status,
    _error_result,
    _gis_error_user_message,
    _proxy_download_path,
    _proxy_source_report_paths,
    _terminal_outcome,
)
from open_webui.services.artifacts.geotizer.owner_envelope import (
    build_accepted_field_summary,
    build_batch_tasks,
    compact_batch_context,
    execution_mode_for_task,
    extract_owner_envelope,
    merge_owner_envelopes,
    normalize_delegator_message,
    owner_completion_valves,
    owner_failure_envelope,
    partition_owner_batch,
    promote_assemble_conclusions,
    recover_backend_owned_owner_envelope,
    xlsx_download_path,
)
from open_webui.services.artifacts.geotizer.validation import (
    owner_submission,
    validate_owner_envelope,
)
from open_webui.services.core.tasks import AgentTask
from open_webui.services.core.text import extract_json_object
from open_webui.services.geotizer.errors import ensure_state_can_continue
from open_webui.services.project_evidence.proposals import (
    apply_structured_external_field_proposals,
    apply_structured_gis_field_proposals,
    build_knowledge_search_plan,
    correct_explicitly_derived_value_origins,
    normalize_gis_field_proposals,
    normalize_gis_object_profile,
    repair_negative_provenance,
)
from open_webui.services.geotizer.semantics import (
    SEMANTIC_POLICY_VERSION,
    semantic_hint,
)
from open_webui.utils.geotizer_rag_runtime import (
    GeoMASRAGDispatcher,
    GeoMASRAGRuntimeSettings,
    ShadowAttemptContext,
)
from open_webui.services.project_evidence.retrieval import (
    RetrievalPlan,
    build_retrieval_plans,
    normalize_negative_search_notes,
    normalize_retrieval_traces,
)
from open_webui.services.project_evidence.resource_coherence import (
    cohere_resource_estimate_proposals,
)
from open_webui.utils.geotizer_vision import (
    apply_structured_visual_field_proposals,
    normalize_visual_field_proposals,
)

GIS_TOOL_IDS = ('server:mcpgis', 'server:mcp:mcpgis')
VISION_TOOL_IDS = ('geology_vision', 'geomas_geological_vision')
DELEGATOR_TOOL_ID = 'mainagent_tool_yulong'
SUB_AGENT_TOOL_ID = 'sub_agent'
# GEOMAS-DEF-001. `skilledagent-sakana` exists in no contour, so every
# owner-completion and tool-free call raised `Model not found` and came back
# classified retryable. `skilledagent-final` is the id that resolves.
SKILLED_MODEL_ID = 'skilledagent-final'
MAX_OWNER_ATTEMPTS = 3
MAX_BATCHES = 12
MAX_OWNER_FIELDS_PER_CALL = 18
ENABLE_GEOMAS_RAG_V2 = os.getenv('ENABLE_GEOMAS_RAG_V2', 'False').lower() == 'true'
GRR_SCHEDULE_FIELD_KEYS = frozenset(
    {
        'geotizer_object.v1.r068.a05',
        'geotizer_object.v1.r069.a05',
        'geotizer_object.v1.r070.a05',
        'geotizer_object.v1.r071.a05',
        'geotizer_object.v1.r072.a05',
        'geotizer_object.v1.r073.a02',
        'geotizer_object.v1.r074.a02',
        'geotizer_object.v1.r075.a02',
    }
)

GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
AgentCall = Callable[
    [AgentTask, str, str, Mapping[str, Any] | None],
    Awaitable[str],
]
VisionEvidenceCall = Callable[
    [str, str | None, Mapping[str, Any]],
    Awaitable[Mapping[str, Any] | None],
]

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


def _rag_v2_active(
    dispatcher: GeoMASRAGDispatcher | None,
) -> bool:
    return dispatcher.settings.mode == 'active' if dispatcher is not None else ENABLE_GEOMAS_RAG_V2


def _rag_v2_collections(
    dispatcher: GeoMASRAGDispatcher | None,
) -> tuple[str, ...]:
    return dispatcher.settings.collections if dispatcher is not None else ()


def _rag_v2_index_version(
    dispatcher: GeoMASRAGDispatcher | None,
) -> str | None:
    if dispatcher is None:
        return None
    return dispatcher.settings.index_version or None


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
    return result


async def run_geotizer_workflow(
    *,
    object_name: str,
    project_id: str | None,
    model_run_id: str | None,
    run_id: str | None,
    allow_draft: bool,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: GeoMASRAGDispatcher | None = None,
    vision_evidence_call: VisionEvidenceCall | None = None,
    event_emitter=None,
    parent_chat_id: str | None = None,
    attempt_key: str | None = None,
) -> dict[str, Any]:
    """Effect shell around the pure GeoTeaser planner and validators."""
    if run_id:
        state = await gis_call({'action': 'get', 'run_id': run_id})
    else:
        state = await gis_call(
            {
                'action': 'start',
                'object_name': object_name,
                'project_id': project_id,
                'model_run_id': model_run_id,
                'linked_gis_project_is_object_scope': True,
            }
        )
    _raise_for_gis_error(state)
    active_run_id = str(state.get('run_id') or run_id or '')
    rag_attempt: ShadowAttemptContext | None = None
    if rag_dispatcher is not None and rag_dispatcher.settings.mode == 'shadow':
        rag_attempt = await rag_dispatcher.begin_attempt(
            run_id=active_run_id,
            parent_chat_id=parent_chat_id,
            attempt_key=attempt_key,
            is_retry=bool(run_id),
            retry_reason='explicit_run_resume' if run_id else None,
        )
    knowledge_search_plan: Mapping[str, Any] = {}
    gis_project = state.get('gis_project')
    if (
        isinstance(gis_project, Mapping)
        and gis_project.get('status') == 'resolved'
        and gis_project.get('project_id')
        and state.get('next_batch')
    ):
        await _emit_status(
            event_emitter,
            'GeoTeaser: derive GIS profile for related knowledge search',
            done=False,
        )
        profile_task = AgentTask(
            kind='gis',
            producer='GISagent_yulong',
            role='contributor',
            task_id='GIS-OBJECT-PROFILE',
            payload=dict(gis_project),
        )
        try:
            raw_profile = await agent_call(
                profile_task,
                _object_profile_prompt(
                    object_name=object_name,
                    run_id=active_run_id,
                    gis_project=gis_project,
                ),
                object_name,
                state.get('datacube'),
            )
        except Exception as exc:
            raw_profile = json.dumps(
                {
                    'profile_status': 'unavailable',
                    'diagnostics': [f'{type(exc).__name__}: {exc}'],
                },
                ensure_ascii=False,
            )
        profile = normalize_gis_object_profile(
            raw_profile,
            object_name=str(gis_project.get('object_name') or object_name),
            project_id=str(gis_project['project_id']),
        )
        knowledge_search_plan = build_knowledge_search_plan(profile)

    for batch_index in range(MAX_BATCHES):
        next_batch = state.get('next_batch')
        if not next_batch:
            break
        await _emit_status(
            event_emitter,
            (f'GeoTeaser: batch {batch_index + 1} {next_batch.get("batch_id")} ({next_batch.get("producer")})'),
            done=False,
        )
        state = await _produce_and_submit_owner_batch(
            current_state=state,
            next_batch=next_batch,
            object_name=object_name,
            run_id=active_run_id,
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            datacube=state.get('datacube'),
            knowledge_search_plan=knowledge_search_plan,
            vision_evidence_call=vision_evidence_call,
            vision_project_id=_resolved_vision_project_id(
                gis_project,
                project_id,
            ),
            rag_attempt=rag_attempt,
        )
        _raise_for_gis_error(state)
    else:
        raise GeotizerOrchestrationError(f'GeoTeaser exceeded the bounded limit of {MAX_BATCHES} owner batches')

    if state.get('next_batch'):
        raise GeotizerOrchestrationError('GeoTeaser stopped before all owner batches')
    await _emit_status(
        event_emitter,
        'GeoTeaser: final audit and XLSX rendering',
        done=False,
    )
    final = await gis_call(
        {
            'action': 'finalize',
            'run_id': active_run_id,
            'allow_draft': allow_draft,
        }
    )
    _raise_for_gis_error(final)
    if final.get('workflow_status') != 'finalized':
        raise GeotizerOrchestrationError('GIS service did not finalize the run')
    xlsx_download_path(final)
    terminal = _terminal_outcome(final)
    await _emit_status(
        event_emitter,
        (
            'GeoTeaser: XLSX draft is ready; publication is blocked'
            if terminal['status'] == 'draft_ready_publication_blocked'
            else 'GeoTeaser: XLSX is ready'
        ),
        done=True,
    )
    return final


def _resolved_vision_project_id(
    gis_project: Any,
    requested_project_id: str | None,
) -> str | None:
    if isinstance(gis_project, Mapping) and gis_project.get('project_id'):
        return str(gis_project['project_id'])
    return requested_project_id


async def _append_visual_evidence(
    evidence: list[dict[str, Any]],
    vision_evidence_call: VisionEvidenceCall | None,
    *,
    object_name: str,
    project_id: str | None,
    next_batch: Mapping[str, Any],
    allowed_field_keys: list[str],
) -> None:
    if vision_evidence_call is None:
        return
    visual_result = await vision_evidence_call(
        object_name,
        project_id,
        next_batch,
    )
    if not isinstance(visual_result, Mapping):
        return
    evidence.append(
        {
            'route_id': 'VISION-EVIDENCE',
            'producer': 'GeoMAS Geological Vision',
            'source_domain': 'vision',
            'relation_to_object': str(visual_result.get('project_match') or 'source_declared'),
            'output': json.dumps(visual_result, ensure_ascii=False),
            'field_proposals': [
                proposal.as_dict()
                for proposal in normalize_visual_field_proposals(
                    visual_result,
                    allowed_field_keys=allowed_field_keys,
                )
            ],
        }
    )


async def _produce_and_submit_owner_batch(
    *,
    current_state: Mapping[str, Any],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: GeoMASRAGDispatcher | None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: ShadowAttemptContext | None = None,
) -> dict[str, Any]:
    chunks = partition_owner_batch(
        next_batch,
        max_fields=MAX_OWNER_FIELDS_PER_CALL,
    )
    envelopes = []
    for chunk in chunks:
        tasks = build_batch_tasks(chunk)
        owner, evidence = await _collect_chunk_evidence(
            tasks=tasks,
            next_batch=chunk,
            object_name=object_name,
            run_id=run_id,
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            datacube=datacube,
            knowledge_search_plan=knowledge_search_plan,
            vision_evidence_call=vision_evidence_call,
            vision_project_id=vision_project_id,
            rag_attempt=rag_attempt,
        )
        prior_chunk_patches = _enriched_owner_patches(
            next_batch,
            envelopes,
        )
        context = compact_batch_context(
            chunk,
            object_name=object_name,
            run_id=run_id,
            datacube=datacube,
            contributor_evidence=evidence,
            knowledge_search_plan=knowledge_search_plan,
            rag_v2_enabled=_rag_v2_active(rag_dispatcher),
            rag_v2_collections=_rag_v2_collections(rag_dispatcher),
            rag_v2_index_version=_rag_v2_index_version(rag_dispatcher),
            accepted_field_summary=build_accepted_field_summary(
                current_state,
                additional_patches=prior_chunk_patches,
            ),
        )
        envelopes.append(
            await _produce_valid_owner_envelope(
                owner=owner,
                context=context,
                next_batch=chunk,
                object_name=object_name,
                run_id=run_id,
                agent_call=agent_call,
                datacube=datacube,
            )
        )

    envelope = merge_owner_envelopes(
        next_batch,
        chunks,
        envelopes,
        run_id=run_id,
    )
    return await gis_call(owner_submission(next_batch, envelope))


async def _collect_chunk_evidence(
    *,
    tasks: Sequence[AgentTask],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: GeoMASRAGDispatcher | None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: ShadowAttemptContext | None = None,
) -> tuple[AgentTask, list[dict[str, Any]]]:
    owner = next(task for task in tasks if task.role == 'owner')
    contributors = _contributors_for_batch(next_batch, tasks)
    rag_v2_active = _rag_v2_active(rag_dispatcher)
    retrieval_plans_by_task: dict[str, tuple[RetrievalPlan, ...]] = {}
    gateway_traces_by_task: dict[str, tuple[dict[str, Any], ...]] = {}
    for task in contributors:
        if task.kind != 'kb' or not (
            rag_v2_active or (rag_dispatcher is not None and rag_dispatcher.settings.mode == 'shadow')
        ):
            continue
        retrieval_plans = build_retrieval_plans(
            next_batch,
            knowledge_search_plan,
            run_id=run_id,
            object_name=object_name,
            index_version=_rag_v2_index_version(rag_dispatcher),
            collections=_rag_v2_collections(rag_dispatcher),
        )
        retrieval_plans_by_task[task.task_id] = retrieval_plans
        if rag_dispatcher is not None and rag_dispatcher.settings.mode == 'shadow':
            rag_dispatcher.submit_shadow(
                retrieval_plans,
                run_id=run_id,
                object_name=object_name,
                batch_id=str(next_batch.get('batch_id') or ''),
                attempt=rag_attempt,
            )
        elif rag_dispatcher is not None and rag_v2_active:
            gateway_traces_by_task[task.task_id] = await rag_dispatcher.execute_active(retrieval_plans)
    contributor_results = await asyncio.gather(
        *[
            agent_call(
                task,
                _contributor_prompt(
                    object_name=object_name,
                    run_id=run_id,
                    task=task,
                    next_batch=next_batch,
                    knowledge_search_plan=knowledge_search_plan,
                    rag_v2_enabled=rag_v2_active,
                    retrieval_plans=retrieval_plans_by_task.get(task.task_id),
                    retrieval_traces=gateway_traces_by_task.get(task.task_id),
                ),
                object_name,
                datacube,
            )
            for task in contributors
        ]
    )
    allowed_field_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    evidence = await _deterministic_infrastructure_evidence(
        next_batch=next_batch,
        run_id=run_id,
        allowed_field_keys=allowed_field_keys,
        gis_call=gis_call,
    )
    evidence.extend(
        await _deterministic_grr_schedule_evidence(
            next_batch=next_batch,
            run_id=run_id,
            allowed_field_keys=allowed_field_keys,
            gis_call=gis_call,
        )
    )
    for task, result in zip(contributors, contributor_results):
        if task.kind == 'kb' and rag_v2_active:
            retrieval_plans = retrieval_plans_by_task.get(task.task_id) or build_retrieval_plans(
                next_batch,
                knowledge_search_plan,
                run_id=run_id,
                object_name=object_name,
                index_version=_rag_v2_index_version(rag_dispatcher),
                collections=_rag_v2_collections(rag_dispatcher),
            )
        else:
            retrieval_plans = ()
        allowed_query_ids = [plan.query_id for plan in retrieval_plans if plan.status == 'planned']
        item = {
            'route_id': task.task_id,
            'producer': task.producer,
            'source_domain': task.kind,
            'relation_to_object': ('direct' if task.kind == 'gis' else 'source_declared'),
            'output': result,
        }
        if task.kind == 'kb' and rag_v2_active:
            item['retrieval_plans'] = [plan.as_dict() for plan in retrieval_plans]
            item['allowed_query_ids'] = allowed_query_ids
            try:
                structured_result = extract_json_object(result)
            except GeotizerOrchestrationError:
                structured_result = {}
            item['negative_search_notes'] = list(
                normalize_negative_search_notes(
                    structured_result.get('negative_search_notes'),
                    retrieval_plans,
                    allowed_field_keys=allowed_field_keys,
                )
            )
            item['retrieval_traces'] = list(
                normalize_retrieval_traces(
                    gateway_traces_by_task.get(task.task_id) or structured_result.get('retrieval_traces'),
                    retrieval_plans,
                )
            )
        if task.kind in {'gis', 'kb', 'web'}:
            item['field_proposals'] = [
                proposal.as_dict()
                for proposal in normalize_gis_field_proposals(
                    result,
                    allowed_field_keys=allowed_field_keys,
                    allowed_query_ids=(allowed_query_ids if task.kind == 'kb' and rag_v2_active else None),
                )
            ]
        evidence.append(item)
    await _append_visual_evidence(
        evidence,
        vision_evidence_call,
        object_name=object_name,
        project_id=vision_project_id,
        next_batch=next_batch,
        allowed_field_keys=allowed_field_keys,
    )
    evidence, coherence_diagnostics = cohere_resource_estimate_proposals(evidence)
    if coherence_diagnostics:
        evidence.append(
            {
                'route_id': 'RESOURCE-ESTIMATE-COHERENCE',
                'producer': 'deterministic_runtime',
                'source_domain': 'derived',
                'relation_to_object': 'direct',
                'output': json.dumps(
                    {
                        'status': 'resource_estimate_conflicts_filtered',
                        'diagnostics': coherence_diagnostics,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return owner, evidence


def _enriched_owner_patches(
    next_batch: Mapping[str, Any],
    envelopes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    field_by_key = {str(field.get('field_key') or ''): dict(field) for field in next_batch.get('fields') or []}
    return [
        {
            **field_by_key.get(str(patch.get('field_key') or ''), {}),
            **dict(patch),
        }
        for envelope in envelopes
        for patch in envelope.get('patches') or []
        if isinstance(patch, Mapping)
    ]


def _extract_backend_owned_owner_envelope(
    raw: str,
    next_batch: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    try:
        envelope = extract_owner_envelope(raw, next_batch)
    except GeotizerOrchestrationError:
        recovered = recover_backend_owned_owner_envelope(
            raw,
            next_batch,
            run_id=run_id,
        )
        if recovered is None:
            raise
        return recovered

    expected_identity = {
        'batch_id': str(next_batch.get('batch_id') or ''),
        'producer': str(next_batch.get('producer') or ''),
        'policy_version': str(next_batch.get('policy_version') or ''),
        'template_version': str(next_batch.get('template_version') or ''),
    }
    if all(envelope.get(key) == value for key, value in expected_identity.items()):
        return envelope
    return (
        recover_backend_owned_owner_envelope(
            raw,
            next_batch,
            run_id=run_id,
        )
        or envelope
    )


async def _produce_valid_owner_envelope(
    *,
    owner: AgentTask,
    context: Mapping[str, Any],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    agent_call: AgentCall,
    datacube: Mapping[str, Any] | None,
) -> dict[str, Any]:
    previous_output = ''
    feedback: Any = None
    candidate_envelopes: list[Mapping[str, Any]] = []
    attempt_diagnostics: list[Mapping[str, Any]] = []
    owner_proposal_evidence: list[Mapping[str, Any]] = []
    allowed_field_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    expected_field_keys = set(allowed_field_keys)
    allowed_query_ids = [
        str(plan.get('query_id') or '')
        for plan in context.get('retrieval_plans') or []
        if plan.get('status') == 'planned'
    ]
    for attempt in range(1, MAX_OWNER_ATTEMPTS + 1):
        prompt = _owner_prompt(
            context=context,
            attempt=attempt,
            feedback=feedback,
            previous_output=previous_output,
        )
        raw = await agent_call(owner, prompt, object_name, datacube)
        previous_output = raw
        attempt_diagnostics.append(owner_attempt_diagnostic(raw, attempt=attempt))
        raw_proposals = normalize_gis_field_proposals(
            raw,
            allowed_field_keys=allowed_field_keys,
            allowed_query_ids=(allowed_query_ids if owner.kind == 'kb' and allowed_query_ids else None),
        )
        current_owner_evidence: list[Mapping[str, Any]] = []
        if raw_proposals:
            evidence_item = {
                'route_id': (f'OWNER-DRAFT-{next_batch.get("batch_id")}-ATTEMPT-{attempt}'),
                'producer': owner.producer,
                'source_domain': owner.kind,
                'relation_to_object': 'source_declared',
                'output': raw,
                'field_proposals': [proposal.as_dict() for proposal in raw_proposals],
            }
            if owner.kind == 'kb' and allowed_query_ids:
                evidence_item['allowed_query_ids'] = allowed_query_ids
                evidence_item['retrieval_plans'] = list(context.get('retrieval_plans') or [])
            current_owner_evidence.append(evidence_item)
            owner_proposal_evidence.append(evidence_item)

        try:
            envelope = _extract_backend_owned_owner_envelope(
                raw,
                next_batch,
                run_id=run_id,
            )
        except GeotizerOrchestrationError as exc:
            feedback = [str(exc)]
            continue

        proposal_keys = {proposal.field_key for proposal in raw_proposals}
        proposal_only = bool(raw_proposals) and not isinstance(envelope.get('patches'), list)
        if proposal_only:
            envelope = owner_failure_envelope(
                next_batch,
                run_id=run_id,
                attempts=attempt,
                feedback=[
                    ('Owner returned structured field_proposals; backend converted them to bounded draft patches.')
                ],
                object_name=object_name,
                accepted_field_summary=(context.get('accepted_field_summary') or ()),
                attempt_diagnostics=attempt_diagnostics,
            )
        candidate_envelopes.append(envelope)

        envelope = repair_negative_provenance(
            next_batch,
            envelope,
            run_id=run_id,
            attempt=attempt,
        )
        combined_evidence = [
            *(context.get('contributor_evidence') or []),
            *current_owner_evidence,
        ]
        envelope = apply_structured_visual_field_proposals(
            next_batch,
            envelope,
            combined_evidence,
        )
        envelope = apply_structured_gis_field_proposals(
            next_batch,
            envelope,
            combined_evidence,
        )
        envelope = apply_structured_external_field_proposals(
            next_batch,
            envelope,
            combined_evidence,
        )
        envelope = correct_explicitly_derived_value_origins(envelope)
        envelope = promote_assemble_conclusions(
            next_batch,
            envelope,
            context.get('accepted_field_summary') or [],
        )
        envelope['run_id'] = run_id
        candidate_envelopes.append(envelope)
        violations = validate_owner_envelope(next_batch, envelope)
        if not violations and (not proposal_only or proposal_keys == expected_field_keys):
            return envelope
        feedback = list(violations)
        if proposal_only and proposal_keys != expected_field_keys:
            feedback.append(
                'structured field_proposals covered '
                f'{len(proposal_keys)}/{len(expected_field_keys)} bounded '
                'fields; return decisions for the remaining field_key values'
            )

    fallback = owner_failure_envelope(
        next_batch,
        run_id=run_id,
        attempts=MAX_OWNER_ATTEMPTS,
        feedback=feedback or [],
        object_name=object_name,
        accepted_field_summary=context.get('accepted_field_summary') or (),
        candidate_envelopes=candidate_envelopes,
        attempt_diagnostics=attempt_diagnostics,
    )
    combined_evidence = [
        *(context.get('contributor_evidence') or []),
        *owner_proposal_evidence,
    ]
    enhanced = apply_structured_visual_field_proposals(
        next_batch,
        fallback,
        combined_evidence,
    )
    enhanced = apply_structured_gis_field_proposals(
        next_batch,
        enhanced,
        combined_evidence,
    )
    enhanced = apply_structured_external_field_proposals(
        next_batch,
        enhanced,
        combined_evidence,
    )
    enhanced = correct_explicitly_derived_value_origins(enhanced)
    enhanced = promote_assemble_conclusions(
        next_batch,
        enhanced,
        context.get('accepted_field_summary') or [],
    )
    enhanced['run_id'] = run_id
    if validate_owner_envelope(next_batch, enhanced):
        return fallback
    return enhanced


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

    selected = _find_vision_tool_record(await Tools.get_tools())
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
            analysis_payload = _parse_vision_analysis(raw)
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


def _find_vision_tool_record(records):
    selected = next(
        (record for preferred_id in VISION_TOOL_IDS for record in records if record.id == preferred_id),
        None,
    )
    if selected is not None:
        return selected
    return next(
        (
            record
            for record in records
            if ('geological vision' in record.name.casefold() or 'analyze_geological_materials' in record.content)
        ),
        None,
    )


def _parse_vision_analysis(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GeotizerOrchestrationError('Geological Vision did not return evidence_json.') from exc
    if not isinstance(parsed, Mapping):
        raise GeotizerOrchestrationError('Geological Vision evidence_json must be an object.')
    return dict(parsed)


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


async def _deterministic_infrastructure_evidence(
    *,
    next_batch: Mapping[str, Any],
    run_id: str,
    allowed_field_keys: Sequence[str],
    gis_call: GisCall,
) -> list[dict[str, Any]]:
    if not _needs_deterministic_infrastructure(next_batch):
        return []
    deterministic = await gis_call(
        {
            'action': 'infrastructure_proposals',
            'run_id': run_id,
        }
    )
    if deterministic.get('workflow_status') not in {'ready', 'partial'}:
        raise GeotizerGisError(deterministic.get('error') or deterministic.get('violations') or deterministic)
    return [
        {
            'route_id': 'GIS-INFRASTRUCTURE-DETERMINISTIC',
            'producer': 'gis_service',
            'source_domain': 'gis',
            'relation_to_object': 'direct',
            'output': json.dumps(
                deterministic,
                ensure_ascii=False,
            ),
            'field_proposals': [
                proposal.as_dict()
                for proposal in normalize_gis_field_proposals(
                    json.dumps(deterministic, ensure_ascii=False),
                    allowed_field_keys=allowed_field_keys,
                )
            ],
        }
    ]


async def _deterministic_grr_schedule_evidence(
    *,
    next_batch: Mapping[str, Any],
    run_id: str,
    allowed_field_keys: Sequence[str],
    gis_call: GisCall,
) -> list[dict[str, Any]]:
    """Do not project a licence-derived scenario into document plan fields."""
    _ = (next_batch, run_id, allowed_field_keys, gis_call)
    return []


def _raise_for_gis_error(state: Mapping[str, Any]) -> None:
    if state.get('error') and not state.get('workflow_status'):
        raise GeotizerGisError(state['error'])
    if state.get('workflow_status') == 'needs_input':
        raise GeotizerGisError(state.get('error') or state)
    if state.get('workflow_status') == 'validation_failed':
        raise GeotizerGisError(
            {
                'code': 'gis_validation_failed',
                'violations': list(state.get('violations') or []),
            }
        )
    ensure_state_can_continue(state)
