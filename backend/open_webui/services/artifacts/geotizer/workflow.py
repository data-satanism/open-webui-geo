"""The GeoTeaser run itself: chunk evidence, owner envelope, submission.

The effect shell is injected: `GisCall`, `AgentCall` and `VisionEvidenceCall`
are parameters, and the RAG dispatcher is described by `RagDispatcher` rather
than imported.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from typing import Any, Protocol

from ...core.idempotency import (
    RunKey,
    RunRegistry,
    RunResolution,
    canonical_digest,
    frozen_inputs_hash,
    resolve_run,
    run_key,
)
from ...core.deadline import FillDeadline
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
    collection_scope_problems,
    correct_explicitly_derived_value_origins,
    normalize_gis_field_proposals,
    normalize_gis_field_proposals_with_rejections,
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
from .observability import EMPTY_RESPONSE, owner_attempt_diagnostic
from .owner_envelope import (
    bounded_previous_output,
    classify_rule_excluded_patches,
    coerce_contradictory_patch_fields,
    record_unrecorded_conflicts,
    grouped_repair_feedback,
    record_retrieval_queries,
    build_accepted_field_summary,
    build_batch_tasks,
    compact_batch_context,
    extract_owner_envelope,
    merge_owner_envelopes,
    flag_invalid_scope_conclusions,
    flag_model_contradictions,
    flag_plan_beyond_licence_term,
    gis_retrieval_expansion,
    refuse_one_sided_conflicts,
    register_locator_only_sources,
    retire_stale_projected_reasons,
    state_the_negative_search,
    normalize_source_inventory,
    MAX_CONSECUTIVE_SPECIALIST_FAILURES,
    inject_row_declared_work_stage,
    refuse_a_licence_record_in_the_work_stage_row,
    refuse_absence_written_as_a_value,
    normalize_patch_source_locators,
    refuse_lone_web_resource_values,
    refuse_out_of_radius_infrastructure,
    refuse_prose_in_numeric_rows,
    a_reading_is_not_a_computation,
    cells_note,
    refuse_a_unit_the_source_contradicts,
    refuse_the_wrong_kind_of_answer,
    refuse_unanswerable_spatial_rows,
    render_run_notes,
    spatial_divergence_notes,
    owner_failure_envelope,
    specialist_failure_signal,
    chunk_marker,
    specialist_round_record,
    stamp_chunk_provenance,
    SpecialistRoundLog,
    partition_owner_batch,
    promote_assemble_conclusions,
    recover_backend_owned_owner_envelope,
    xlsx_download_path,
)
from .prompts import (
    _contributor_prompt,
    _contributors_for_batch,
    _receives_deterministic_gis,
    _object_profile_prompt,
    _owner_prompt,
)
from .run_scope import set_gis_scope
from .terminal import (
    StatusSettings,
    _emit_status,
    _terminal_outcome,
    member_subject,
)
from .validation import owner_submission, validate_owner_envelope
from .vision import (
    apply_structured_visual_field_proposals,
    normalize_visual_field_proposals,
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

MAX_OWNER_ATTEMPTS = 3
MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES = 2
MAX_BATCHES = 12
MAX_OWNER_FIELDS_PER_CALL = 18

OWNER_ROW_WIDTH = 6


DEFAULT_FILL_DEADLINE_SECONDS = 6 * 60 * 60


def resolve_fill_deadline(requested: Any) -> tuple[float, str | None]:
    """The wall-clock backstop for one fill, and a note when a value was refused.

    Returns `(seconds, note)`. `None` or `''` gives the default and no note. A
    value that is not a number, or is negative, gives the default and a note
    saying so. Zero means no deadline. Any other value, however small, is used,
    with a note when it differs from `DEFAULT_FILL_DEADLINE_SECONDS`.
    """
    if requested in (None, ''):
        return float(DEFAULT_FILL_DEADLINE_SECONDS), None
    try:
        seconds = float(requested)
    except (TypeError, ValueError):
        return (
            float(DEFAULT_FILL_DEADLINE_SECONDS),
            f'fill_deadline_seconds={requested!r} is not a number — '
            f'{DEFAULT_FILL_DEADLINE_SECONDS} s used.',
        )
    if seconds < 0:
        return (
            float(DEFAULT_FILL_DEADLINE_SECONDS),
            f'fill_deadline_seconds={requested!r} must not be negative — '
            f'{DEFAULT_FILL_DEADLINE_SECONDS} s used.',
        )
    if seconds and seconds != DEFAULT_FILL_DEADLINE_SECONDS:
        return (
            seconds,
            f'fill_deadline_seconds={seconds:g} is in force instead of the '
            f'{DEFAULT_FILL_DEADLINE_SECONDS} s default. Said here because a '
            'card truncated by a lowered backstop and a card truncated by a '
            'genuine hang are otherwise identical.',
        )
    return seconds, None


def resolve_owner_fields_per_call(requested: Any) -> tuple[int, str | None]:
    """The chunk size for one run, and a degradation note when it was refused.

    Returns `(size, note)`. `None` or `''` gives `MAX_OWNER_FIELDS_PER_CALL` and no
    note. A value that is not an integer, is below 1, or is not a multiple of
    `OWNER_ROW_WIDTH` is refused: the default is returned with a note saying why.
    """
    if requested in (None, ''):
        return MAX_OWNER_FIELDS_PER_CALL, None
    try:
        size = int(requested)
    except (TypeError, ValueError):
        return (
            MAX_OWNER_FIELDS_PER_CALL,
            f'owner_fields_per_call={requested!r} is not a number — '
            f'{MAX_OWNER_FIELDS_PER_CALL} used.',
        )
    if size < 1:
        return (
            MAX_OWNER_FIELDS_PER_CALL,
            f'owner_fields_per_call={size} must be positive — '
            f'{MAX_OWNER_FIELDS_PER_CALL} used.',
        )
    if size % OWNER_ROW_WIDTH:
        return (
            MAX_OWNER_FIELDS_PER_CALL,
            f'owner_fields_per_call={size} does not divide the {OWNER_ROW_WIDTH}-field '
            f'resource row, so a row would straddle two chunks and its '
            f'cross-patch consistency check would not run — '
            f'{MAX_OWNER_FIELDS_PER_CALL} used.',
        )
    return size, None

OBJECT_PROFILE_TASK_ID = 'GIS-OBJECT-PROFILE'


class RagSettings(Protocol):
    mode: str
    collections: tuple[str, ...]
    index_version: str


class RagDispatcher(Protocol):
    """Everything the run uses from the shadow dispatcher, and nothing else."""

    settings: RagSettings

    async def begin_attempt(self, *args: Any, **kwargs: Any) -> Any: ...

    def submit_shadow(self, *args: Any, **kwargs: Any) -> None: ...

    async def execute_active(self, *args: Any, **kwargs: Any) -> Any: ...


class RoundUsageDrain(Protocol):
    """A fill's own collection of what each of its rounds cost.

    `open` starts the collection and must be called before any round is recorded
    into it; `drain` returns what was recorded. May be absent, in which case every
    round is reported `unmeasured`.
    """

    def open(self) -> None: ...

    def drain(self) -> list[dict[str, Any]]: ...


class _OrchestratorRoundUsage:
    """The orchestrator's `open_round_usage` and `drain_round_usage`, bound together as one scope."""

    def __init__(self, opener: Any, drain: Any) -> None:
        self._open, self._drain = opener, drain

    def open(self) -> None:
        self._open()

    def drain(self) -> list[dict[str, Any]]:
        return list(self._drain() or [])


def _round_usage_pair(source: Any) -> tuple[Any, Any] | None:
    """Both functions off one object, or None when that object lacks either."""
    opener = getattr(source, 'open_round_usage', None)
    drain = getattr(source, 'drain_round_usage', None)
    if callable(opener) and callable(drain):
        return opener, drain
    return None


def round_usage_scope(orchestrator: Any) -> RoundUsageDrain | None:
    """The orchestrator's round collection, or None on a build without one.

    Detected by attribute, not by version: both `open_round_usage` and
    `drain_round_usage` must be callable on the same object, the orchestrator
    instance or else the module that defines its type. A build exposing only one
    of them returns None.
    """
    found = _round_usage_pair(orchestrator)
    if found is None:
        module = sys.modules.get(getattr(type(orchestrator), '__module__', '') or '')
        if module is not None and module is not orchestrator:
            found = _round_usage_pair(module)
    if found is None:
        return None
    return _OrchestratorRoundUsage(*found)


class QueryDrain(Protocol):
    """What a specialist actually searched for, collected where it happens.

    Implemented by `open_webui.utils.geotizer_query_sink`. `recording` is a
    context manager: every search issued inside it is attributed to that call, and
    a search issued outside every scope records nothing.
    """

    def recording(self, *args: Any, **kwargs: Any) -> Any: ...

    def drain(self) -> list[dict[str, Any]]: ...

    def stats(self) -> dict[str, Any]: ...


def _rag_v2_active(
    dispatcher: RagDispatcher | None,
    *,
    fallback: bool = False,
) -> bool:
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


async def _start_gis_run(
    gis_call: GisCall,
    *,
    object_name: str,
    project_id: str | None,
    model_run_id: str | None,
    run_mode: str = 'clean',
    kb_scope_status: str | None = None,
    kb_configured_collections: Sequence[str] = (),
    licence_id: str | None = None,
    licence_layer_id: str | None = None,
) -> dict[str, Any]:
    """Send the GIS `start` action for a new run."""
    return await gis_call(
        {
            'action': 'start',
            'object_name': object_name,
            'project_id': project_id,
            'model_run_id': model_run_id,
            'linked_gis_project_is_object_scope': True,
            'run_mode': run_mode,
            'kb_scope_status': kb_scope_status,
            'kb_configured_collections': list(kb_configured_collections),
            'licence_id': licence_id,
            'licence_layer_id': licence_layer_id,
        }
    )


UNRESOLVABLE_RUN_ID = (
    'That run does not exist. Omit run_id to start a new run for this object, '
    'or supply run_mode="carry_forward" to reuse the previous card\'s values.'
)


def _run_is_missing(state: Mapping[str, Any] | None, raised: Exception | None) -> bool:
    """Whether GIS is saying "no such run" rather than something else.

    Reads the raised exception's text, or only the `error`, `detail` and
    `message` keys of the state, and matches `404`, `not found`, `no such file`
    or `invalid run_id`, case-insensitively.
    """
    if raised is not None:
        text = str(raised)
    else:
        text = json.dumps(
            {key: (state or {}).get(key) for key in ('error', 'detail', 'message')},
            ensure_ascii=False,
        )
    lowered = text.lower()
    if '404' in lowered or 'not found' in lowered or 'no such file' in lowered:
        return True
    return 'invalid run_id' in lowered


FINISHED_STATUSES = ('finalized', 'completed')


async def _resume_or_explain(gis_call: GisCall, run_id: str) -> dict[str, Any]:
    """`action=get`, with the not-found and already-done cases explained."""
    try:
        state = await gis_call({'action': 'get', 'run_id': run_id})
    except Exception as exc:  # noqa: BLE001
        if _run_is_missing(None, exc):
            raise GeotizerOrchestrationError(UNRESOLVABLE_RUN_ID) from exc
        raise
    if _run_is_missing(state, None) and not state.get('run_id'):
        raise GeotizerOrchestrationError(UNRESOLVABLE_RUN_ID)
    status = str(state.get('status') or state.get('workflow_status') or '')
    if status in FINISHED_STATUSES:
        state = {**state, 'resumed_run_was_already_finalized': True}
    return state


_SOURCE_ID_PATHS = (('id',), ('file_id',), ('file', 'id'), ('source', 'id'), ('collection', 'id'))


def attached_source_fingerprints(items: Sequence[Any] | None) -> list[str]:
    """A stable identity per attached source, whatever shape it arrived in.

    A mapping yields the first non-empty string found along `_SOURCE_ID_PATHS`;
    a mapping with none is hashed whole, as is any non-mapping item. The result is
    sorted and de-duplicated.
    """
    found: set[str] = set()
    for item in items or ():
        if not isinstance(item, Mapping):
            found.add(f'raw:{canonical_digest(item)}')
            continue
        for path in _SOURCE_ID_PATHS:
            value: Any = item
            for step in path:
                value = value.get(step) if isinstance(value, Mapping) else None
                if value is None:
                    break
            if isinstance(value, str) and value.strip():
                found.add(f'{".".join(path)}:{value.strip()}')
                break
        else:
            found.add(f'shape:{canonical_digest(item)}')
    return sorted(found)


GEOTIZER_ARTIFACT_SET = ('geotizer_object',)


def geotizer_run_identity(
    *,
    requester_id: str,
    object_name: str = '',
    project_id: str | None,
    model_run_id: str | None,
    allow_draft: bool,
    vision_collection_url: str | None,
    attached_file_ids: Sequence[str] | None = None,
    run_mode: str = 'clean',
    attempt_key: str | None = None,
    rag_dispatcher: RagDispatcher | None = None,
    kb_scope_status: str | None = None,
    kb_configured_collections: Sequence[str] = (),
    licence_id: str | None = None,
    licence_layer_id: str | None = None,
) -> RunKey:
    """The persistent identity of "fill GeoTeaser for X", formed before GIS runs.

    Everything a caller can vary that changes the answer, and nothing else: two
    commands that differ in none of these inputs are the same run and return the
    same workbook.

    Raises `GeotizerOrchestrationError` when `requester_id` is empty, or when
    none of `project_id`, `object_name` and `licence_id` is given. The key's
    partition is `project_id`, else `object:<object_name>`, else
    `licence:<licence_id>`. `attempt_key` is the request identity; `None` keys on
    the inputs alone, so identical commands share one run indefinitely. The GIS
    template and assignment-policy versions are not part of the key.
    """
    if not str(requester_id or '').strip():
        raise GeotizerOrchestrationError(
            'a run identity needs the requesting user; an unattributed key would be '
            'shared across every caller'
        )
    partition = (
        (project_id or '').strip()
        or (f'object:{object_name.strip()}' if object_name.strip() else '')
        or (f'licence:{(licence_id or "").strip()}' if (licence_id or '').strip() else '')
    )
    if not partition:
        raise GeotizerOrchestrationError(
            'a run identity needs an object_name, a project_id or a licence_id'
        )
    return run_key(
        project_id=partition,
        artifact_set=GEOTIZER_ARTIFACT_SET,
        frozen_inputs_hash=frozen_inputs_hash(
            {
                'requester_id': str(requester_id).strip(),
                'object_name': object_name.strip(),
                'project_id': (project_id or '').strip() or None,
                'model_run_id': (model_run_id or '').strip() or None,
                'allow_draft': bool(allow_draft),
                'run_mode': run_mode,
                'licence_id': (licence_id or '').strip() or None,
                'licence_layer_id': (licence_layer_id or '').strip() or None,
                'attempt_key': (attempt_key or '').strip() or None,
                'vision_collection_url': (vision_collection_url or '').strip() or None,
                'attached_sources': attached_source_fingerprints(attached_file_ids),
                'rag': (
                    {
                        'index_version': _rag_v2_index_version(rag_dispatcher),
                        'collections': list(_rag_v2_collections(rag_dispatcher)),
                        'mode': rag_dispatcher.settings.mode,
                    }
                    if rag_dispatcher is not None
                    else None
                ),
                'kb_scope': {
                    'status': kb_scope_status,
                    'collections': list(kb_configured_collections),
                },
            }
        ),
    )


def _refuse_a_reused_run_that_answers_a_different_question(
    state: Mapping[str, Any],
    *,
    project_id: str | None,
    resolution: RunResolution,
) -> None:
    """Refuse a reused run whose GIS project differs from the pinned `project_id`.

    Does nothing when `project_id` is not pinned. The object name is not compared.
    """
    if not project_id:
        return
    gis_project = state.get('gis_project')
    resolved = (
        str(gis_project.get('project_id') or '').strip() if isinstance(gis_project, Mapping) else ''
    )
    if resolved and resolved != project_id.strip():
        raise GeotizerOrchestrationError(
            f'run {resolution.run_id} is recorded for this request but GIS resolved it '
            f'to project {resolved!r}, not {project_id.strip()!r}; refusing to return it'
        )


async def run_geotizer_workflow(
    *,
    object_name: str = '',
    project_id: str | None,
    licence_id: str | None = None,
    licence_layer_id: str | None = None,
    model_run_id: str | None,
    run_id: str | None,
    allow_draft: bool,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: RagDispatcher | None = None,
    query_drain: QueryDrain | None = None,
    round_usage_drain: RoundUsageDrain | None = None,
    vision_evidence_call: VisionEvidenceCall | None = None,
    event_emitter=None,
    parent_chat_id: str | None = None,
    attempt_key: str | None = None,
    run_registry: RunRegistry | None = None,
    run_mode: str = 'clean',
    requester_id: str | None = None,
    vision_collection_url: str | None = None,
    attached_file_ids: Sequence[str] | None = None,
    kb_scope_status: str | None = None,
    kb_configured_collections: Sequence[str] = (),
    status: StatusSettings | None = None,
    owner_fields_per_call: Any = None,
    fill_deadline_seconds: Any = None,
    started_run: MutableMapping[str, Any] | None = None,
    build_revision: Mapping[str, Any] | None = None,
    area_member: bool = False,
) -> dict[str, Any]:
    """Effect shell around the pure GeoTeaser planner and validators.

    `run_registry` is the persistent key -> run binding; `None` means no
    idempotency and every command starts a run. `requester_id`,
    `vision_collection_url` and `attached_file_ids` are used only to form the
    run's identity; without a `requester_id` the registry is bypassed.
    `kb_scope_status` and `kb_configured_collections` are the contour's configured
    KB collection allowlist; they go into the run key and the GIS run state, and
    `None` status is recorded as `unknown`. `status` is the language and verbosity
    of the progress lines; `None` uses the `StatusSettings` defaults.
    """
    if round_usage_drain is not None:
        round_usage_drain.open()
    status = status or StatusSettings()
    run_notes: list[Any] = []
    query_log: list[dict[str, Any]] = []
    gis_trace_log: list[dict[str, Any]] = []
    gis_rejection_log: list[dict[str, Any]] = []
    infrastructure_cache: dict[str, Any] = {}
    owner_fields_per_call, chunk_size_note = resolve_owner_fields_per_call(owner_fields_per_call)
    if chunk_size_note:
        run_notes.append(chunk_size_note)
    deadline_seconds, deadline_note = resolve_fill_deadline(fill_deadline_seconds)
    if deadline_note:
        run_notes.append(deadline_note)
    deadline = FillDeadline(deadline_seconds)
    deadline_stopped_at = ''
    run_started_at = _stamp()
    run_started = time.monotonic()
    batch_timings: list[dict[str, Any]] = []
    specialist_round_log = SpecialistRoundLog()
    resolution: RunResolution | None = None
    if run_id:
        state = await _resume_or_explain(gis_call, run_id)
    elif run_registry is not None and str(requester_id or '').strip():
        key = geotizer_run_identity(
            requester_id=str(requester_id).strip(),
            object_name=object_name,
            project_id=project_id,
            model_run_id=model_run_id,
            allow_draft=allow_draft,
            vision_collection_url=vision_collection_url,
            attached_file_ids=attached_file_ids,
            run_mode=run_mode,
            attempt_key=attempt_key,
            rag_dispatcher=rag_dispatcher,
            kb_scope_status=kb_scope_status,
            kb_configured_collections=kb_configured_collections,
            licence_id=licence_id,
            licence_layer_id=licence_layer_id,
        )
        started: dict[str, Any] = {}

        async def _start() -> str:
            started['state'] = await _start_gis_run(
                gis_call,
                object_name=object_name,
                project_id=project_id,
                model_run_id=model_run_id,
                run_mode=run_mode,
                kb_scope_status=kb_scope_status,
                kb_configured_collections=kb_configured_collections,
                licence_id=licence_id,
                licence_layer_id=licence_layer_id,
            )
            _raise_for_gis_error(started['state'])
            fresh = str(started['state'].get('run_id') or '').strip()
            if not fresh:
                raise GeotizerOrchestrationError('GIS started a run without returning a run_id')
            return fresh

        resolution = await resolve_run(key, registry=run_registry, start=_start)
        if resolution.reused:
            state = await gis_call({'action': 'get', 'run_id': resolution.run_id})
            _raise_for_gis_error(state)
            _refuse_a_reused_run_that_answers_a_different_question(
                state,
                project_id=project_id,
                resolution=resolution,
            )
        else:
            state = started['state']
    else:
        state = await _start_gis_run(
            gis_call,
            object_name=object_name,
            project_id=project_id,
            model_run_id=model_run_id,
            run_mode=run_mode,
            kb_scope_status=kb_scope_status,
            kb_configured_collections=kb_configured_collections,
            licence_id=licence_id,
            licence_layer_id=licence_layer_id,
        )
    _raise_for_gis_error(state)
    active_run_id = str(state.get('run_id') or run_id or '')
    _resolved_project = state.get('gis_project')
    set_gis_scope(
        project_id=(
            str(_resolved_project.get('project_id') or '').strip()
            if isinstance(_resolved_project, Mapping)
            else ''
        ),
        run_id=active_run_id,
        area_member=area_member,
    )
    if area_member:
        status = status.about(
            member_subject(
                object_name=(
                    (_resolved_project or {}).get('object_name')
                    if isinstance(_resolved_project, Mapping)
                    else None
                )
                or object_name,
                licence_id=licence_id,
            )
        )
    if started_run is not None:
        started_run['run_id'] = active_run_id
    await _emit_status(
        event_emitter,
        status.say(
            'run_started_named' if status.subject else 'run_started',
            run_id=active_run_id,
            object_name=object_name or licence_id or '—',
        ),
        done=False,
    )
    if resolution is not None and resolution.abandoned_run_id:
        await _emit_status(
            event_emitter,
            status.say(
                'parallel_key',
                run_id=active_run_id,
                abandoned_run_id=resolution.abandoned_run_id,
            ),
            done=False,
        )
    rag_attempt: Any | None = None
    if rag_dispatcher is not None and rag_dispatcher.settings.mode == 'shadow':
        rag_attempt = await rag_dispatcher.begin_attempt(
            run_id=active_run_id,
            parent_chat_id=parent_chat_id,
            attempt_key=attempt_key,
            is_retry=bool(run_id) or bool(resolution and resolution.reused),
            retry_reason=(
                'explicit_run_resume'
                if run_id
                else 'run_key_reuse'
                if resolution and resolution.reused
                else None
            ),
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
            status.say('profile'),
            done=False,
        )
        profile_task = AgentTask(
            agent='gis',
            producer=OBJECT_PROFILE_TASK_ID,
            role='contributor',
            task_id=OBJECT_PROFILE_TASK_ID,
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
        knowledge_search_plan = build_knowledge_search_plan(
            profile, collections=kb_configured_collections
        )
        scope_problems = collection_scope_problems(kb_configured_collections)
        if scope_problems:
            run_notes.append(
                'Область поиска по базе знаний содержит записи, которые не '
                'являются коллекциями: '
                f'{", ".join(scope_problems)}. Поиск внутри них невозможен, '
                'и пустой результат по ним означает invalid_scope, а не '
                'not_found.'
            )

    batches_total = state.get('batches_total')
    for batch_index in range(MAX_BATCHES):
        next_batch = state.get('next_batch')
        if not next_batch:
            break
        if deadline.expired() and not deadline_stopped_at:
            deadline_stopped_at = str(next_batch.get('batch_id') or '')
            remaining = _remaining_batch_count(state, batch_index, batches_total)
            run_notes.append(
                f'Достигнут предельный срок заполнения '
                f'({deadline.seconds:g} с): остановлено на пакете '
                f'{deadline_stopped_at}, не запрошено пакетов: {remaining}. '
                'Карта построена по тому, что успели собрать.'
            )
        await _emit_status(
            event_emitter,
            status.batch_line(
                n=batch_index + 1,
                total=batches_total,
                batch_id=next_batch.get('batch_id'),
                producer=next_batch.get('producer'),
                label=next_batch.get('label'),
            ),
            done=False,
        )
        batch_id = str(next_batch.get('batch_id') or '')
        batch_started_at = _stamp()
        batch_started = time.monotonic()
        queries_before = len(query_drain.drain()) if query_drain is not None else 0
        state = await _produce_and_submit_owner_batch(
            current_state=state,
            next_batch=next_batch,
            owner_fields_per_call=owner_fields_per_call,
            run_notes=run_notes,
            query_log=query_log,
            gis_trace_log=gis_trace_log,
            gis_rejection_log=gis_rejection_log,
            infrastructure_cache=infrastructure_cache,
            specialist_round_log=specialist_round_log,
            object_name=object_name,
            run_id=active_run_id,
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            query_drain=query_drain,
            datacube=state.get('datacube'),
            knowledge_search_plan=knowledge_search_plan,
            kb_configured_collections=kb_configured_collections,
            vision_evidence_call=vision_evidence_call,
            vision_project_id=_resolved_vision_project_id(
                gis_project,
                project_id,
            ),
            rag_attempt=rag_attempt,
            deadline=deadline,
        )
        batch_timings.append(
            _batch_timing(
                batch_id=batch_id,
                started_at=batch_started_at,
                finished_at=_stamp(),
                seconds=time.monotonic() - batch_started,
                entries=(query_drain.drain()[queries_before:] if query_drain else []),
            )
        )
        _raise_for_gis_error(state)
    else:
        raise GeotizerOrchestrationError(f'GeoTeaser exceeded the bounded limit of {MAX_BATCHES} owner batches')

    if state.get('next_batch'):
        raise GeotizerOrchestrationError('GeoTeaser stopped before all owner batches')
    await _emit_status(
        event_emitter,
        status.say('final'),
        done=False,
    )
    layer_manifest = next(
        (
            payload['layer_manifest']
            for payload in infrastructure_cache.values()
            if isinstance(payload, Mapping) and payload.get('layer_manifest')
        ),
        None,
    )
    mark_rejections_answered_elsewhere(gis_rejection_log, state.get('fields') or [])
    if round_usage_drain is not None:
        try:
            specialist_round_log.absorb_orchestrator_rounds(round_usage_drain.drain())
        except Exception:  # noqa: BLE001
            pass
    run_log = {
        key: value
        for key, value in (
            ('build_revision', dict(build_revision) if build_revision else None),
            ('run_notes', render_run_notes(run_notes) if run_notes else None),
            (
                'retrieval_queries',
                _queries_with_citations(
                    query_drain.drain() if query_drain is not None else [],
                    query_log,
                    state.get('fields') or [],
                    kb_configured_collections,
                )
                or None,
            ),
            (
                'retrieval_query_stats',
                _query_stats(
                    query_drain,
                    query_drain.drain() if query_drain is not None else [],
                    kb_configured_collections,
                ),
            ),
            ('specialist_round_failures', specialist_round_log.records or None),
            ('specialist_round_stats', specialist_round_log.stats() or None),
            ('specialist_round_usage', specialist_round_log.usage_stats() or None),
            ('specialist_rounds', specialist_round_log.rounds() or None),
            (
                'run_timing',
                _run_timing(
                    started_at=run_started_at,
                    finished_at=_stamp(),
                    total_seconds=time.monotonic() - run_started,
                    batches=batch_timings,
                ),
            ),
            ('gis_execution_trace', gis_trace_log or None),
            ('gis_layer_manifest', layer_manifest),
            ('gis_proposal_rejections', gis_rejection_log or None),
            (
                'gis_retrieval_expansion',
                gis_retrieval_expansion(gis_trace_log, state.get('fields') or [])
                or None,
            ),
        )
        if value is not None
    }
    final = await gis_call(
        {
            'action': 'finalize',
            'run_id': active_run_id,
            'allow_draft': allow_draft,
            **({'run_log': run_log} if run_log else {}),
        }
    )
    _raise_for_gis_error(final)
    if final.get('workflow_status') != 'finalized':
        raise GeotizerOrchestrationError('GIS service did not finalize the run')
    xlsx_download_path(final)
    if state.get('resumed_run_was_already_finalized'):
        final = {**final, 'resumed_run_was_already_finalized': True}
    if resolution is not None and resolution.reused:
        final = {**final, 'reused_run_from_registry': resolution.run_id}
    if run_notes:
        final = {**final, 'run_notes': render_run_notes(run_notes)}
    issued_and_planned = _queries_with_citations(
        query_drain.drain() if query_drain is not None else [],
        query_log,
        state.get('fields') or [],
        kb_configured_collections,
    )
    if issued_and_planned:
        final = {**final, 'retrieval_queries': issued_and_planned}
    query_stats = _query_stats(
        query_drain,
        query_drain.drain() if query_drain is not None else [],
        kb_configured_collections,
    )
    final = {
        **final,
        'run_timing': _run_timing(
            started_at=run_started_at,
            finished_at=_stamp(),
            total_seconds=time.monotonic() - run_started,
            batches=batch_timings,
        ),
    }
    if query_stats:
        final = {**final, 'retrieval_query_stats': query_stats}
    round_stats = specialist_round_log.stats()
    if round_stats:
        final = {
            **final,
            'specialist_round_failures': list(specialist_round_log.records),
            'specialist_round_stats': round_stats,
        }
    round_usage = specialist_round_log.usage_stats()
    if round_usage:
        final = {
            **final,
            'specialist_round_usage': round_usage,
            'specialist_rounds': specialist_round_log.rounds(),
        }
    if gis_trace_log:
        final = {**final, 'gis_execution_trace': gis_trace_log}
    terminal = _terminal_outcome(final)
    await _emit_status(
        event_emitter,
        status.say(
            'draft_ready'
            if terminal['status'] == 'draft_ready_publication_blocked'
            else 'ready'
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


def _remaining_batch_count(
    state: Mapping[str, Any],
    batch_index: int,
    batches_total: Any,
) -> int:
    """How many batches the deadline stopped short of, counting the one it stopped on.

    From `batches_total` when it is an integer, otherwise from the number of
    applied batches plus one; never below 1.
    """
    try:
        total = int(batches_total)
    except (TypeError, ValueError):
        applied = state.get('applied_batches')
        total = (len(applied) if isinstance(applied, Sequence) else 0) + 1
    return max(1, total - batch_index)


async def _produce_and_submit_owner_batch(
    *,
    current_state: Mapping[str, Any],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: RagDispatcher | None,
    query_drain: QueryDrain | None = None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    kb_configured_collections: Sequence[str] = (),
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: Any | None = None,
    owner_fields_per_call: int = MAX_OWNER_FIELDS_PER_CALL,
    run_notes: list[Any] | None = None,
    query_log: list[dict[str, Any]] | None = None,
    gis_trace_log: list[dict[str, Any]] | None = None,
    gis_rejection_log: list[dict[str, Any]] | None = None,
    infrastructure_cache: dict[str, Any] | None = None,
    specialist_round_log: SpecialistRoundLog | None = None,
    deadline: FillDeadline | None = None,
) -> dict[str, Any]:
    chunks = partition_owner_batch(
        next_batch,
        max_fields=owner_fields_per_call,
    )
    scope_names = [
        str((current_state.get('object_scope') or {}).get('object_name') or ''),
        str(object_name or ''),
    ]
    scope_name = [name for name in scope_names if name.strip()]
    envelopes = []
    for chunk in chunks:
        if deadline is not None and deadline.expired():
            envelopes.append(
                owner_failure_envelope(
                    chunk,
                    run_id=run_id,
                    attempts=0,
                    feedback=[],
                    object_name=object_name,
                    accepted_field_summary=build_accepted_field_summary(
                        current_state,
                        additional_patches=_enriched_owner_patches(next_batch, envelopes),
                    ),
                    scope_name=scope_name,
                    stopped_by_deadline=True,
                )
            )
            continue
        tasks = build_batch_tasks(chunk)
        owner, evidence = await _collect_chunk_evidence(
            tasks=tasks,
            next_batch=chunk,
            query_log=query_log,
            gis_trace_log=gis_trace_log,
            gis_rejection_log=gis_rejection_log,
            infrastructure_cache=infrastructure_cache,
            specialist_round_log=specialist_round_log,
            object_name=object_name,
            run_id=run_id,
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=rag_dispatcher,
            query_drain=query_drain,
            datacube=datacube,
            knowledge_search_plan=knowledge_search_plan,
            kb_configured_collections=kb_configured_collections,
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
            owner_agent=owner.agent,
            object_name=object_name,
            run_id=run_id,
            datacube=datacube,
            contributor_evidence=evidence,
            object_scope=current_state.get('object_scope'),
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
                run_notes=run_notes,
                scope_name=scope_name,
                owner=owner,
                context=context,
                next_batch=chunk,
                object_name=object_name,
                run_id=run_id,
                agent_call=agent_call,
                query_drain=query_drain,
                datacube=datacube,
                specialist_round_log=specialist_round_log,
            )
        )

    envelope, coherence_notes = merge_owner_envelopes(
        next_batch,
        chunks,
        envelopes,
        run_id=run_id,
    )
    if run_notes is not None:
        for note in coherence_notes:
            if note not in run_notes:
                run_notes.append(note)
    return await gis_call(owner_submission(next_batch, envelope))


def _cited_document_ids(fields: Sequence[Mapping[str, Any]]) -> set[str]:
    """Every document a filled cell says it was answered from.

    Collects `source_locator.document_id` of each filled field and every
    `__`-separated segment of at least eight characters of its `source_refs`,
    which includes segments that are not document ids.
    """
    cited: set[str] = set()
    for field in fields:
        if str(field.get('status') or '') != 'filled':
            continue
        locator = field.get('source_locator')
        if isinstance(locator, Mapping):
            document = str(locator.get('document_id') or '').strip()
            if document:
                cited.add(document)
        for reference in field.get('source_refs') or []:
            cited.update(part for part in str(reference).split('__') if len(part) >= 8)
    return cited


def _query_stats(
    drain: QueryDrain | None,
    issued: Sequence[Mapping[str, Any]] = (),
    marked_collections: Sequence[str] = (),
) -> dict[str, Any] | None:
    """How many searches the run made, and which collections it read.

    None when the drain reports no counts and no collection was read. Otherwise
    the drain's `stats()` plus `collections_read`, `collections_marked` and
    `collections_read_unmarked`, all three always present.
    """
    counts = drain.stats() if drain is not None else None
    read: set[str] = set()
    for entry in issued:
        for identifier in entry.get('searched_collections') or ():
            if str(identifier).strip():
                read.add(str(identifier))
    marked = {str(item) for item in marked_collections if str(item).strip()}
    if not counts and not read:
        return None
    stats: dict[str, Any] = dict(counts or {})
    stats['collections_read'] = sorted(read)
    stats['collections_marked'] = sorted(marked)
    stats['collections_read_unmarked'] = sorted(read - marked)
    return stats or None


def _stamp() -> str:
    """A wall-clock instant, for a timestamp a reader compares with the state's."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _batch_timing(
    *,
    batch_id: str,
    started_at: str,
    finished_at: str,
    seconds: float,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """One batch's cost, and what is derivable about where it went.

    `specialist_calls_that_searched` counts distinct (agent, chunk, attempt)
    among the batch's query entries. `chunks` is present only when an entry
    carries an `index/total` chunk label.
    """
    calls = {
        (entry.get('agent'), entry.get('chunk'), entry.get('attempt'))
        for entry in entries
    }
    totals = {
        str(entry.get('chunk') or '').split('/')[-1]
        for entry in entries
        if '/' in str(entry.get('chunk') or '')
    }
    timing: dict[str, Any] = {
        'batch_id': batch_id,
        'started_at': started_at,
        'finished_at': finished_at,
        'seconds': round(seconds, 3),
        'queries': len(entries),
        'specialist_calls_that_searched': len(calls),
    }
    numeric = {int(item) for item in totals if item.isdigit()}
    if numeric:
        timing['chunks'] = max(numeric)
    return timing


def _run_timing(
    *,
    started_at: str,
    finished_at: str,
    total_seconds: float,
    batches: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Where a fill's time went, per batch.

    `outside_batches_seconds` is the total minus the batch sum, floored at zero.
    `batches_are_sequential` is true when that difference is under the larger of
    one second and 2% of the total.
    """
    summed = sum(float(batch.get('seconds') or 0) for batch in batches)
    return {
        'started_at': started_at,
        'finished_at': finished_at,
        'total_seconds': round(total_seconds, 3),
        'batches': list(batches),
        'batches_sum_seconds': round(summed, 3),
        'outside_batches_seconds': round(max(0.0, total_seconds - summed), 3),
        'batches_are_sequential': bool(batches) and abs(total_seconds - summed) < max(
            1.0, 0.02 * total_seconds
        ),
    }


def _queries_with_citations(
    issued: Sequence[Mapping[str, Any]],
    planned: Sequence[Mapping[str, Any]],
    fields: Sequence[Mapping[str, Any]],
    marked_collections: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The queries a run issued, each with how much of what it returned was cited.

    Issued entries first, then the planned ones marked `source: planned`.
    `citations` and `cited_document_ids` join on document id only, and are written
    only when the entry has `result_document_ids` and the run has cited ids.
    `cited_collections` is written when the entry maps cited documents to
    collections, and `cited_collections_unmarked` when marked collections exist.
    """
    cited = _cited_document_ids(fields)
    marked = {str(item) for item in marked_collections if str(item).strip()}
    entries: list[dict[str, Any]] = []
    for entry in list(issued) + [dict(item, source='planned') for item in planned]:
        record = dict(entry)
        returned = [
            str(item) for item in (record.get('result_document_ids') or []) if str(item).strip()
        ]
        if returned and cited:
            matched = {identifier for identifier in returned if identifier in cited}
            record['citations'] = len(matched)
            record['cited_document_ids'] = sorted(matched)
            origins = record.get('result_collection_ids') or ()
            by_document = {
                str(document): str(origin)
                for document, origin in zip(record.get('result_document_ids') or (), origins)
                if str(origin).strip()
            }
            cited_collections = sorted(
                {by_document[document] for document in matched if document in by_document}
            )
            if cited_collections:
                record['cited_collections'] = cited_collections
                if marked:
                    record['cited_collections_unmarked'] = [
                        item for item in cited_collections if item not in marked
                    ]
        entries.append(record)
    return entries


async def _agent_call_recording_queries(
    agent_call: AgentCall,
    task: AgentTask,
    prompt: str,
    object_name: str,
    datacube: Mapping[str, Any] | None,
    *,
    drain: QueryDrain | None,
    batch_id: str,
    chunk: Any,
    attempt: int | None = None,
) -> str:
    """One specialist call, with every search it issues attributed to it.

    The recording scope is entered inside the coroutine, so each contributor
    scheduled by `asyncio.gather` has its own scope. With no drain this is
    `agent_call` alone.
    """
    if drain is None:
        return await agent_call(task, prompt, object_name, datacube)
    with drain.recording(
        agent=task.agent, batch_id=batch_id, chunk=chunk, attempt=attempt
    ):
        return await agent_call(task, prompt, object_name, datacube)


async def _collect_chunk_evidence(
    *,
    tasks: Sequence[AgentTask],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: RagDispatcher | None,
    query_drain: QueryDrain | None = None,
    datacube: Mapping[str, Any] | None,
    knowledge_search_plan: Mapping[str, Any],
    kb_configured_collections: Sequence[str] = (),
    vision_evidence_call: VisionEvidenceCall | None,
    vision_project_id: str | None,
    rag_attempt: Any | None = None,
    query_log: list[dict[str, Any]] | None = None,
    gis_trace_log: list[dict[str, Any]] | None = None,
    gis_rejection_log: list[dict[str, Any]] | None = None,
    infrastructure_cache: dict[str, Any] | None = None,
    specialist_round_log: SpecialistRoundLog | None = None,
) -> tuple[AgentTask, list[dict[str, Any]]]:
    owner = next(task for task in tasks if task.role == 'owner')
    contributors = _contributors_for_batch(next_batch, tasks)
    rag_v2_active = _rag_v2_active(rag_dispatcher)
    retrieval_plans_by_task: dict[str, tuple[RetrievalPlan, ...]] = {}
    gateway_traces_by_task: dict[str, tuple[dict[str, Any], ...]] = {}
    for task in contributors:
        if task.agent != 'kb' or not (
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
        record_retrieval_queries(
            query_log,
            retrieval_plans,
            batch_id=str(next_batch.get('batch_id') or ''),
            chunk=next_batch.get('owner_chunk'),
            agent=task.agent,
        )
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
            _agent_call_recording_queries(
                agent_call,
                task,
                _contributor_prompt(
                    object_name=object_name,
                    run_id=run_id,
                    task=task,
                    next_batch=next_batch,
                    knowledge_search_plan=knowledge_search_plan,
                    kb_collections=kb_configured_collections,
                    rag_v2_enabled=rag_v2_active,
                    retrieval_plans=retrieval_plans_by_task.get(task.task_id),
                    retrieval_traces=gateway_traces_by_task.get(task.task_id),
                ),
                object_name,
                datacube,
                drain=query_drain,
                batch_id=str(next_batch.get('batch_id') or ''),
                chunk=next_batch.get('owner_chunk'),
            )
            for task in contributors
        ]
    )
    if specialist_round_log is not None:
        for task, raw in zip(contributors, contributor_results):
            signal = specialist_failure_signal(raw)
            specialist_round_log.observe_round(
                agent=str(getattr(task, 'agent', '') or (signal or {}).get('agent') or ''),
                batch_id=str(next_batch.get('batch_id') or ''),
                chunk=next_batch.get('owner_chunk'),
                outcome='burnt' if (signal or {}).get('code') == 'empty_completion'
                else 'failed' if signal is not None else 'succeeded',
                usage=signal,
                failure=(
                    specialist_round_record(
                        signal,
                        role='contributor',
                        batch_id=str(next_batch.get('batch_id') or ''),
                        chunk=next_batch.get('owner_chunk'),
                    )
                    if signal is not None
                    else None
                ),
            )
    allowed_field_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    evidence = await _deterministic_infrastructure_evidence(
        next_batch=next_batch,
        run_id=run_id,
        allowed_field_keys=allowed_field_keys,
        gis_call=gis_call,
        cache=infrastructure_cache,
    )
    if gis_trace_log is not None:
        recorded = {str(entry.get('trace_id') or '') for entry in gis_trace_log}
        for item in evidence:
            for entry in item.get('gis_execution_trace') or []:
                if not isinstance(entry, Mapping):
                    continue
                trace_id = str(entry.get('trace_id') or '')
                if trace_id and trace_id in recorded:
                    continue
                recorded.add(trace_id)
                gis_trace_log.append(
                    {**dict(entry), 'batch_id': str(next_batch.get('batch_id') or '')}
                )
    if gis_rejection_log is not None:
        record_gis_proposal_rejections(
            gis_rejection_log,
            evidence,
            batch_id=str(next_batch.get('batch_id') or ''),
        )
    evidence.extend(
        await _deterministic_grr_schedule_evidence(
            next_batch=next_batch,
            run_id=run_id,
            allowed_field_keys=allowed_field_keys,
            gis_call=gis_call,
        )
    )
    for task, result in zip(contributors, contributor_results, strict=True):
        if task.agent == 'kb' and rag_v2_active:
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
            'source_domain': task.agent,
            'relation_to_object': ('direct' if task.agent == 'gis' else 'source_declared'),
            'output': result,
        }
        if task.agent == 'kb' and rag_v2_active:
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
        if task.agent in {'gis', 'kb', 'web'}:
            item['field_proposals'] = [
                proposal.as_dict()
                for proposal in normalize_gis_field_proposals(
                    result,
                    allowed_field_keys=allowed_field_keys,
                    allowed_query_ids=(allowed_query_ids if task.agent == 'kb' and rag_v2_active else None),
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


def _stamped_with_chunk_provenance(
    envelope: Mapping[str, Any],
    next_batch: Mapping[str, Any],
    specialist_round_log: SpecialistRoundLog | None,
) -> dict[str, Any]:
    """Which chunk produced these cells, and which contributor never answered.

    The chunk comes from the batch the owner was handed; the failures come from
    `specialist_round_log`, keyed on that chunk. Without a log the chunk is still
    stamped.
    """
    marker = chunk_marker(
        next_batch.get('owner_chunk'), batch_id=str(next_batch.get('batch_id') or '')
    )
    failures = (
        specialist_round_log.failures_for(
            str(next_batch.get('batch_id') or ''), marker['index']
        )
        if specialist_round_log is not None and marker is not None
        else []
    )
    return stamp_chunk_provenance(envelope, chunk=marker, failures=failures)


async def _produce_valid_owner_envelope(
    *,
    owner: AgentTask,
    context: Mapping[str, Any],
    next_batch: Mapping[str, Any],
    object_name: str,
    run_id: str,
    agent_call: AgentCall,
    query_drain: QueryDrain | None = None,
    datacube: Mapping[str, Any] | None,
    run_notes: list[Any] | None = None,
    scope_name: Sequence[str] | str = '',
    specialist_round_log: SpecialistRoundLog | None = None,
) -> dict[str, Any]:
    previous_output = ''
    feedback: Any = None
    degradations: list[Any] = run_notes if run_notes is not None else []
    candidate_envelopes: list[Mapping[str, Any]] = []
    attempt_diagnostics: list[Mapping[str, Any]] = []
    feedback_by_attempt: list[Mapping[str, Any]] = []
    consecutive_empty = 0
    previous_violations: frozenset[str] | None = None
    repeated_violations = False
    specialist_failures: list[Mapping[str, Any]] = []
    consecutive_specialist_failures = 0
    owner_proposal_evidence: list[Mapping[str, Any]] = []
    allowed_field_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    expected_field_keys = set(allowed_field_keys)
    allowed_query_ids = [
        str(plan.get('query_id') or '')
        for plan in context.get('retrieval_plans') or []
        if plan.get('status') == 'planned'
    ]
    for attempt in range(1, MAX_OWNER_ATTEMPTS + 1):
        attempt_notes: list[Any] = []
        prompt = _owner_prompt(
            context=context,
            attempt=attempt,
            feedback=grouped_repair_feedback(feedback) if feedback else feedback,
            previous_output=(
                bounded_previous_output(previous_output, feedback) if feedback else previous_output
            ),
        )
        raw = await _agent_call_recording_queries(
            agent_call,
            owner,
            prompt,
            object_name,
            datacube,
            drain=query_drain,
            batch_id=str(next_batch.get('batch_id') or ''),
            chunk=next_batch.get('owner_chunk'),
            attempt=attempt,
        )
        previous_output = raw
        diagnostic = owner_attempt_diagnostic(raw, attempt=attempt, request=prompt)
        attempt_diagnostics.append(diagnostic)

        if diagnostic.get('response_mode') == EMPTY_RESPONSE:
            consecutive_empty += 1
            feedback = [
                f'Owner returned no output on attempt {attempt} '
                f'({consecutive_empty} in a row).'
            ]
            feedback_by_attempt.append({'attempt': attempt, 'violations': list(feedback)})
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES:
                break
            continue
        consecutive_empty = 0

        signal = specialist_failure_signal(raw)
        if signal is not None:
            specialist_failures.append(signal)
            if specialist_round_log is not None:
                specialist_round_log.add(
                    specialist_round_record(
                        signal,
                        role='owner',
                        batch_id=str(next_batch.get('batch_id') or ''),
                        chunk=next_batch.get('owner_chunk'),
                        attempt=attempt,
                    )
                )
            consecutive_specialist_failures += 1
            diagnostic = {**diagnostic, 'specialist_failure': signal}
            attempt_diagnostics[-1] = diagnostic
            feedback = [
                f'{signal["agent"] or "specialist"} reported '
                f'{signal["code"] or "a failure"} on attempt {attempt}; '
                'no owner envelope was produced.'
            ]
            feedback_by_attempt.append({'attempt': attempt, 'violations': list(feedback)})
            if signal.get('retryable') is False:
                break
            if consecutive_specialist_failures >= MAX_CONSECUTIVE_SPECIALIST_FAILURES:
                break
            continue
        consecutive_specialist_failures = 0

        raw_proposals = normalize_gis_field_proposals(
            raw,
            allowed_field_keys=allowed_field_keys,
            allowed_query_ids=(allowed_query_ids if owner.agent == 'kb' and allowed_query_ids else None),
        )
        current_owner_evidence: list[Mapping[str, Any]] = []
        if raw_proposals:
            evidence_item = {
                'route_id': (f'OWNER-DRAFT-{next_batch.get("batch_id")}-ATTEMPT-{attempt}'),
                'producer': owner.producer,
                'source_domain': owner.agent,
                'relation_to_object': 'source_declared',
                'output': raw,
                'field_proposals': [proposal.as_dict() for proposal in raw_proposals],
            }
            if owner.agent == 'kb' and allowed_query_ids:
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
            feedback_by_attempt.append({'attempt': attempt, 'violations': list(feedback)})
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

        envelope, source_repair_notes = normalize_source_inventory(envelope)
        for note in source_repair_notes:
            if note not in degradations:
                degradations.append(note)

        envelope, coercion_notes = coerce_contradictory_patch_fields(envelope)
        for note in coercion_notes:
            if note not in degradations:
                degradations.append(note)

        envelope, locator_notes = normalize_patch_source_locators(envelope)
        for note in locator_notes:
            if note not in degradations:
                degradations.append(note)

        envelope, work_stage_notes = inject_row_declared_work_stage(next_batch, envelope)
        for note in work_stage_notes:
            if note not in degradations:
                degradations.append(note)

        envelope = repair_negative_provenance(
            next_batch,
            envelope,
            run_id=run_id,
            attempt=attempt,
        )

        envelope, negative_notes = state_the_negative_search(next_batch, envelope)
        attempt_notes.extend(negative_notes)

        envelope, locator_ref_notes = register_locator_only_sources(
            next_batch,
            envelope,
            run_id=run_id,
        )
        attempt_notes.extend(locator_ref_notes)

        envelope, exclusion_notes = classify_rule_excluded_patches(next_batch, envelope)
        attempt_notes.extend(exclusion_notes)
        combined_evidence = [
            *(context.get('contributor_evidence') or []),
            *current_owner_evidence,
        ]
        envelope, absence_notes = refuse_absence_written_as_a_value(envelope)
        attempt_notes.extend(absence_notes)
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
        envelope, lone_web_notes = refuse_lone_web_resource_values(envelope)
        attempt_notes.extend(lone_web_notes)
        envelope, spatial_notes = refuse_unanswerable_spatial_rows(
            envelope,
            _unanswerable_spatial_rows(combined_evidence),
        )
        attempt_notes.extend(spatial_notes)
        envelope, radius_notes = refuse_out_of_radius_infrastructure(envelope)
        attempt_notes.extend(radius_notes)
        envelope, numeric_notes = refuse_prose_in_numeric_rows(next_batch, envelope)
        envelope, kind_notes = refuse_the_wrong_kind_of_answer(next_batch, envelope)
        envelope, work_stage_source_notes = (
            refuse_a_licence_record_in_the_work_stage_row(
                envelope,
                accepted_fields=context.get('accepted_field_summary') or (),
            )
        )
        kind_notes = [*kind_notes, *work_stage_source_notes]
        envelope, reading_notes = a_reading_is_not_a_computation(envelope)
        envelope, unit_notes = refuse_a_unit_the_source_contradicts(envelope)
        numeric_notes = [*numeric_notes, *kind_notes, *reading_notes, *unit_notes]
        attempt_notes.extend(numeric_notes)
        attempt_notes.extend(spatial_divergence_notes(envelope))
        envelope, unrecorded_conflict_notes = record_unrecorded_conflicts(envelope)
        envelope, one_sided_notes = refuse_one_sided_conflicts(envelope)
        envelope, contradiction_notes = flag_model_contradictions(envelope)
        envelope, plan_term_notes = flag_plan_beyond_licence_term(
            envelope,
            accepted_fields=context.get('accepted_field_summary') or (),
        )
        corpus_scope = (
            (context.get('knowledge_search_plan') or {}).get('corpus_scope') or {}
        )
        envelope, invalid_scope_notes = flag_invalid_scope_conclusions(
            envelope,
            non_corpus_names=[
                *(corpus_scope.get('not_a_corpus') or ()),
                *(corpus_scope.get('invalid_entries') or ()),
            ],
        )
        attempt_notes.extend(
            [
                *unrecorded_conflict_notes,
                *one_sided_notes,
                *contradiction_notes,
                *plan_term_notes,
                *invalid_scope_notes,
            ]
        )
        envelope = promote_assemble_conclusions(
            next_batch,
            envelope,
            context.get('accepted_field_summary') or [],
        )
        envelope, stale_reason_notes = retire_stale_projected_reasons(envelope)
        for note in stale_reason_notes:
            if note not in attempt_notes:
                attempt_notes.append(note)
        envelope['run_id'] = run_id
        candidate_envelopes.append(envelope)
        violations = validate_owner_envelope(next_batch, envelope, object_name=scope_name or [object_name])
        if not violations and (not proposal_only or proposal_keys == expected_field_keys):
            for note in attempt_notes:
                if note not in degradations:
                    degradations.append(note)
            return _stamped_with_chunk_provenance(
                envelope, next_batch, specialist_round_log
            )
        feedback = list(violations)
        if proposal_only and proposal_keys != expected_field_keys:
            feedback.append(
                'structured field_proposals covered '
                f'{len(proposal_keys)}/{len(expected_field_keys)} bounded '
                'fields; return decisions for the remaining field_key values'
            )
        feedback_by_attempt.append({'attempt': attempt, 'violations': list(feedback)})
        signature = frozenset(str(item) for item in feedback)
        if previous_violations is not None and signature == previous_violations:
            repeated_violations = True
            repeat_note = cells_note(
                'Owner refused twice with the same violations on {count} '
                'cells; stopped rather than spend a third attempt on feedback '
                'that states the objection and not the answer ({keys}).',
                allowed_field_keys,
            )
            if repeat_note not in attempt_notes:
                attempt_notes.append(repeat_note)
            for note in attempt_notes:
                if note not in degradations:
                    degradations.append(note)
            break
        previous_violations = signature

    fallback = owner_failure_envelope(
        next_batch,
        specialist_failures=list(specialist_failures),
        ended_in_specialist_failure=bool(consecutive_specialist_failures),
        unactionable_feedback=repeated_violations,
        run_id=run_id,
        attempts=len(attempt_diagnostics),
        feedback=feedback or [],
        object_name=object_name,
        scope_name=scope_name or [object_name],
        accepted_field_summary=context.get('accepted_field_summary') or (),
        candidate_envelopes=candidate_envelopes,
        attempt_diagnostics=attempt_diagnostics,
        feedback_by_attempt=feedback_by_attempt,
    )
    combined_evidence = [
        *(context.get('contributor_evidence') or []),
        *owner_proposal_evidence,
    ]
    fallback, salvage_absence_notes = refuse_absence_written_as_a_value(fallback)
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
    enhanced, fallback_notes = refuse_lone_web_resource_values(enhanced)
    enhanced, unanswerable_notes = refuse_unanswerable_spatial_rows(
        enhanced,
        _unanswerable_spatial_rows(combined_evidence),
    )
    enhanced, radius_notes = refuse_out_of_radius_infrastructure(enhanced)
    absence_notes = salvage_absence_notes
    enhanced, numeric_notes = refuse_prose_in_numeric_rows(next_batch, enhanced)
    enhanced, kind_notes = refuse_the_wrong_kind_of_answer(next_batch, enhanced)
    enhanced, work_stage_source_notes = (
        refuse_a_licence_record_in_the_work_stage_row(
            enhanced,
            accepted_fields=context.get('accepted_field_summary') or (),
        )
    )
    numeric_notes = [*absence_notes, *numeric_notes, *work_stage_source_notes]
    enhanced, reading_notes = a_reading_is_not_a_computation(enhanced)
    enhanced, unit_notes = refuse_a_unit_the_source_contradicts(enhanced)
    numeric_notes = [*numeric_notes, *kind_notes, *reading_notes, *unit_notes]
    enhanced = promote_assemble_conclusions(
        next_batch,
        enhanced,
        context.get('accepted_field_summary') or [],
    )
    enhanced, fallback_ref_notes = register_locator_only_sources(
        next_batch,
        enhanced,
        run_id=run_id,
    )
    enhanced['run_id'] = run_id
    if validate_owner_envelope(next_batch, enhanced, object_name=scope_name or [object_name]):
        return _stamped_with_chunk_provenance(
            fallback, next_batch, specialist_round_log
        )
    for note in (
        *fallback_notes,
        *unanswerable_notes,
        *radius_notes,
        *numeric_notes,
        *fallback_ref_notes,
        *spatial_divergence_notes(enhanced),
    ):
        if note not in degradations:
            degradations.append(note)
    return _stamped_with_chunk_provenance(
        enhanced, next_batch, specialist_round_log
    )


def record_gis_proposal_rejections(
    log: list[dict[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    *,
    batch_id: str,
) -> None:
    """Every computed proposal the run did not use, in one run-level list.

    Appends each `unusable_field_proposals` entry and each `deferred_field_keys`
    key (as reason `not_this_batch`), tagged with `batch_id`.
    """
    for item in evidence:
        for rejection in item.get('unusable_field_proposals') or []:
            if isinstance(rejection, Mapping):
                log.append({**dict(rejection), 'batch_id': batch_id})
        for field_key in item.get('deferred_field_keys') or []:
            log.append(
                {
                    'field_key': str(field_key),
                    'reason': 'not_this_batch',
                    'batch_id': batch_id,
                }
            )


def mark_rejections_answered_elsewhere(
    log: Sequence[MutableMapping[str, Any]],
    fields: Sequence[Mapping[str, Any]],
) -> None:
    """Say which refused keys another batch went on to answer.

    Sets `answered_elsewhere` (the cell is `filled`) and `answered_status` on each
    entry from the finalized fields; a key with no cell gets `no_such_cell`.
    """
    answered = {
        str(field.get('field_key') or ''): str(field.get('status') or '')
        for field in fields
    }
    for entry in log:
        status = answered.get(str(entry.get('field_key') or ''))
        if status is None:
            entry['answered_elsewhere'] = False
            entry['answered_status'] = 'no_such_cell'
            continue
        entry['answered_elsewhere'] = status == 'filled'
        entry['answered_status'] = status


def _unanswerable_spatial_rows(
    contributor_evidence: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The rows the linked project has no layer to measure, from the evidence."""
    return [
        item
        for evidence in contributor_evidence
        for item in evidence.get('unanswerable_field_keys') or []
        if isinstance(item, Mapping)
    ]


async def _deterministic_infrastructure_evidence(
    *,
    next_batch: Mapping[str, Any],
    run_id: str,
    allowed_field_keys: Sequence[str],
    gis_call: GisCall,
    cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not _receives_deterministic_gis(next_batch):
        return []
    deterministic = cache.get(run_id) if cache is not None else None
    if deterministic is None:
        deterministic = await gis_call(
            {
                'action': 'infrastructure_proposals',
                'run_id': run_id,
            }
        )
        if deterministic.get('workflow_status') not in {'ready', 'partial'}:
            raise GeotizerGisError(
                {
                    'code': 'gis_infrastructure_unavailable',
                    'workflow_status': deterministic.get('workflow_status'),
                    'returned': (
                        'error'
                        if deterministic.get('error')
                        else 'violations'
                        if deterministic.get('violations')
                        else 'state'
                    ),
                    'error': deterministic.get('error'),
                    'violations': list(deterministic.get('violations') or []),
                }
            )
        if cache is not None:
            cache[run_id] = deterministic
    evidence_payload = {
        key: value for key, value in deterministic.items() if key != 'layer_manifest'
    }
    serialized = json.dumps(evidence_payload, ensure_ascii=False)
    accepted, rejected = normalize_gis_field_proposals_with_rejections(
        serialized,
        allowed_field_keys=allowed_field_keys,
    )
    return [
        {
            'route_id': 'GIS-INFRASTRUCTURE-DETERMINISTIC',
            'producer': 'gis_service',
            'source_domain': 'gis',
            'relation_to_object': 'direct',
            'output': serialized,
            'field_proposals': [proposal.as_dict() for proposal in accepted],
            'unanswerable_field_keys': [
                item
                for item in deterministic.get('unanswerable_field_keys') or []
                if isinstance(item, Mapping) and str(item.get('field_key') or '') in set(allowed_field_keys)
            ],
            'gis_execution_trace': [
                dict(item)
                for item in deterministic.get('gis_execution_trace') or []
                if isinstance(item, Mapping)
            ],
            'deferred_field_keys': sorted(
                {
                    rejection['field_key']
                    for rejection in rejected
                    if rejection['reason'] == 'not_this_batch'
                }
            ),
            'unusable_field_proposals': [
                dict(rejection)
                for rejection in rejected
                if rejection['reason'] != 'not_this_batch'
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
