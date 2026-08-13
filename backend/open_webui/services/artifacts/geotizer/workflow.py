"""The GeoTeaser run itself: chunk evidence, owner envelope, submission.

`implementation-steps.md` S1.2 and S1.6. The workflow belongs in the core with
the effect shell injected -- `GisCall`, `AgentCall` and `VisionEvidenceCall` are
parameters, so the run is testable without an Open WebUI process and the
Workspace Tool is left with argument coercion and the terminal envelope.

The RAG dispatcher is injected the same way, through `RagDispatcher` below.
`rag_runtime` stays in Open WebUI under the app lifespan's shutdown drain (S1.5),
so this module describes the surface it uses rather than importing the class:
four members, and nothing here can reach past them into the runtime.

`_rag_v2_active` takes the fallback as an argument. It used to read
`ENABLE_GEOMAS_RAG_V2` from the tool's module scope, which made "is v2 on" a
property of the process rather than of the call.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from ...core.tasks import AgentTask
from ...core.text import extract_json_object
from ...geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
    ensure_state_can_continue,
)
from ...project_evidence.proposals import (
    apply_structured_external_field_proposals,
    apply_structured_gis_field_proposals,
    build_knowledge_search_plan,
    correct_explicitly_derived_value_origins,
    normalize_gis_field_proposals,
    normalize_gis_object_profile,
    repair_negative_provenance,
)
from ...project_evidence.resource_coherence import cohere_resource_estimate_proposals
from ...project_evidence.retrieval import (
    RetrievalPlan,
    build_retrieval_plans,
    normalize_negative_search_notes,
    normalize_retrieval_traces,
)
from .observability import owner_attempt_diagnostic
from .owner_envelope import (
    build_accepted_field_summary,
    build_batch_tasks,
    compact_batch_context,
    extract_owner_envelope,
    merge_owner_envelopes,
    owner_failure_envelope,
    partition_owner_batch,
    promote_assemble_conclusions,
    recover_backend_owned_owner_envelope,
    xlsx_download_path,
)
from .prompts import (
    _contributor_prompt,
    _contributors_for_batch,
    _needs_deterministic_infrastructure,
    _object_profile_prompt,
    _owner_prompt,
)
from .terminal import _emit_status, _terminal_outcome
from .validation import owner_submission, validate_owner_envelope
from .vision import (
    apply_structured_visual_field_proposals,
    normalize_visual_field_proposals,
)

# The effect shell, as types. The tool builds these; nothing here does.
GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
AgentCall = Callable[
    [AgentTask, str, str, Mapping[str, Any] | None],
    Awaitable[str],
]
VisionEvidenceCall = Callable[
    [str, str | None, Mapping[str, Any]],
    Awaitable[Mapping[str, Any] | None],
]

MAX_OWNER_ATTEMPTS = 3
MAX_BATCHES = 12
MAX_OWNER_FIELDS_PER_CALL = 18


class RagSettings(Protocol):
    mode: str
    collections: tuple[str, ...]
    index_version: str


class RagDispatcher(Protocol):
    """Everything the run uses from the shadow dispatcher, and nothing else.

    Written as a protocol rather than an import so the boundary holds in one
    direction only: Open WebUI may hand its dispatcher in, and the core cannot
    reach for one.
    """

    settings: RagSettings

    async def begin_attempt(self, *args: Any, **kwargs: Any) -> Any: ...

    def submit_shadow(self, *args: Any, **kwargs: Any) -> None: ...

    async def execute_active(self, *args: Any, **kwargs: Any) -> Any: ...


def _rag_v2_active(
    dispatcher: RagDispatcher | None,
    *,
    fallback: bool = False,
) -> bool:
    # The fallback is the caller's, not the process's. This used to read
    # `ENABLE_GEOMAS_RAG_V2` from the tool's module scope.
    return dispatcher.settings.mode == 'active' if dispatcher is not None else fallback


def _rag_v2_collections(
    dispatcher: RagDispatcher | None,
) -> tuple[str, ...]:
    return dispatcher.settings.collections if dispatcher is not None else ()


def _rag_v2_index_version(
    dispatcher: RagDispatcher | None,
) -> str | None:
    if dispatcher is None:
        return None
    return dispatcher.settings.index_version or None


async def run_geotizer_workflow(
    *,
    object_name: str,
    project_id: str | None,
    model_run_id: str | None,
    run_id: str | None,
    allow_draft: bool,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: RagDispatcher | None = None,
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
    rag_attempt: Any | None = None
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
    rag_dispatcher: RagDispatcher | None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: Any | None = None,
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
    rag_dispatcher: RagDispatcher | None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: Any | None = None,
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
    # `contributor_results` is a gather over `contributors`, so the two are the
    # same length by construction; `strict` says so where it is relied on.
    for task, result in zip(contributors, contributor_results, strict=True):
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


__all__ = [
    'AgentCall',
    'GisCall',
    'MAX_BATCHES',
    'MAX_OWNER_ATTEMPTS',
    'MAX_OWNER_FIELDS_PER_CALL',
    'RagDispatcher',
    'VisionEvidenceCall',
    '_rag_v2_active',
    '_rag_v2_collections',
    '_rag_v2_index_version',
    'run_geotizer_workflow',
]
