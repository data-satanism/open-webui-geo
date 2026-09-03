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
    partition_owner_batch,
    promote_assemble_conclusions,
    recover_backend_owned_owner_envelope,
    xlsx_download_path,
)
from .prompts import (
    _contributor_prompt,
    _contributors_for_batch,
    _needs_deterministic_infrastructure,
    _receives_deterministic_gis,
    _object_profile_prompt,
    _owner_prompt,
)
from .terminal import StatusSettings, _emit_status, _terminal_outcome
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
#: Consecutive empty owner responses before the attempt loop stops.
#:
#: An empty response carries nothing to repair, so the next prompt is the same
#: prompt and the next call is the same call. `KB-GRR-FACTORS` on run
#: `6056e157` returned zero characters three times and spent three specialist
#: calls proving it. Two rather than one, because an empty first attempt is not
#: reliably terminal: `KB-RESOURCE-TECH` chunk 4/6 went 0 -> 10,851 -> 0, and
#: stopping after the first would have thrown away the only attempt that
#: produced an envelope -- and with it the 21 cells salvage took from it.
MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES = 2
MAX_BATCHES = 12
MAX_OWNER_FIELDS_PER_CALL = 18

#: The teaser's resource rows (44-56) are each exactly six contiguous fields,
#: and `partition_owner_batch` is a fixed-width slice that knows nothing about
#: rows. `_resource_row_consistency_violations` only sees the patches inside
#: one chunk, so a size that does not divide six cuts a row across a boundary
#: and the rule that stops one row reporting two different deposits silently
#: stops running. 18 and 12 divide it; 8 does not.
OWNER_ROW_WIDTH = 6


#: Six hours. A hang backstop, not a budget.
#:
#: An observed specialist answers in 26-44 s, a fill makes around seventy-five
#: specialist calls and about twenty-five owner chunks of up to three attempts
#: each, and a realistic fill lands between one and two hours. Six is three to
#: six times that, which is the headroom a backstop needs and a budget would
#: not have.
#:
#: **Lowering this toward realistic run times converts it into something that
#: truncates good runs.** It stops being the layer that rescues a hang and
#: becomes the layer that ends a slow-but-working fill early, and the card it
#: produces looks the same either way.
#:
#: A note on the sizing rule this did *not* follow. The obvious property --
#: "the deadline must exceed `specialist ceiling x specialist calls per fill`"
#: -- gives 1980 s x 75 = **41.2 hours** under v5.0.0's derived ceiling, and
#: obeying it would mean a genuine hang holds the request open for most of two
#: days. That product is the same arithmetic v4.7.0 retired from
#: `check_configuration`: it assumes every one of the seventy-five calls runs
#: to its own timeout, which observed specialists do not. The binding
#: comparison is against a realistic fill, not an arithmetic one, and against
#: Open WebUI's request timeout at the other end -- a deadline above that never
#: fires, because the request dies first and takes the artefacts with it.
DEFAULT_FILL_DEADLINE_SECONDS = 6 * 60 * 60


def resolve_fill_deadline(requested: Any) -> tuple[float, str | None]:
    """The wall-clock backstop for one fill, and a note when a value was refused.

    Read from `GEOMAS_FILL_DEADLINE_SECONDS` for the same reason as
    `resolve_owner_fields_per_call` reads its own: the GeoTeaser shim exposes
    no valves by design, and adding one would mean a Workspace re-paste to
    change a number. The task that asked for this specified a valve with a
    description saying it is a hang backstop rather than a budget; there is no
    valve to put that description in, so it is above, where the value is.

    **Not refused for being small**, which is the one place this deliberately
    parts company with its sibling. A chunk size of 8 silently disables a
    validation rule, so running it would report a lower failure count for the
    wrong reason and refusing is right. A short deadline has no such cliff --
    it produces a partial card that says on its face which batches were never
    requested, which is the artefact this whole layer exists to produce. An
    operator capping a smoke test at ten minutes is using it correctly.

    Garbage is still refused: a deadline that cannot be parsed is not a
    deadline of zero, and zero means "no deadline" rather than "expire
    immediately".
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

    The size has to be settable to be measurable. The five chunks that failed
    run `6056e157` are the population the chunk-size question needs, and
    rerunning them at 18, 12 and 8 was impossible while the value was a module
    constant: the valve lives in the retired monolith and the deployed shim
    exposes no budgets, so an operator could not vary it without editing code
    and redeploying between arms.

    Refusals rather than silent clamping, because an experiment that quietly
    ran a different arm than it reported is worse than one that would not
    start. A refused value falls back to the default and says so in the run's
    notes, where the card shows it.

    The adapter reads it from `GEOMAS_OWNER_FIELDS_PER_CALL`, an environment
    variable rather than a valve, for two reasons that are both about not
    breaking something to enable a measurement. The orchestrator's stored valve
    row is fetched exactly once, deliberately -- two reads could be served from
    either side of an edit and narrate half a run in the wrong language -- and
    the GeoTeaser shim exposes no budgets by design, so giving it one would
    mean a Workspace re-paste per experiment arm on a contour where deploys are
    manual.

    A size that does not divide `OWNER_ROW_WIDTH` is refused rather than run,
    and 8 is the value the question most wants to try. That is not an
    obstruction: at 8 a resource row straddles a chunk boundary and
    `_resource_row_consistency_violations` -- which only sees the patches
    inside one chunk -- stops catching a row that reports two different
    deposits. Measuring 8 honestly needs a row-aware partitioner first, and an
    arm that silently disabled a validation rule would report a lower failure
    count for the wrong reason.
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

# The synthetic GIS object-profile call's one name, serving as both its producer
# and its task id. GeoTeaser issues this call; `gis_service` never plans it, so
# it appears in no `assignment_policy.json` evidence route -- which is why its
# agent is named at the call site rather than arriving from a batch. It borrowed
# a service producer name until recently, which tied a call this repository owns
# to a string the contract can rename, and made it indistinguishable from a
# planned GIS batch in any transcript grouped by producer. One constant rather
# than two literals, so the by-producer and by-task views cannot end up
# describing different calls.
OBJECT_PROFILE_TASK_ID = 'GIS-OBJECT-PROFILE'


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


class QueryDrain(Protocol):
    """What a specialist actually searched for, collected where it happens.

    Written as a protocol for the same reason `RagDispatcher` is: the core may
    be handed one and may not reach for one. The implementation lives in
    `open_webui.utils.geotizer_query_sink`, because the queries are issued by
    the KB builtins and `services/` may not import `open_webui`.

    `recording` is a context manager. Everything a specialist searches inside
    it is attributed to that call; a search issued outside every scope — a
    person chatting with their own documents — records nothing.
    """

    def recording(self, *args: Any, **kwargs: Any) -> Any: ...

    def drain(self) -> list[dict[str, Any]]: ...

    #: How many searches the run made, how many are in `drain()`, how many were
    #: dropped by the cap. A sibling of the list, never an entry in it: runs
    #: `82365089` and `26aaf34a` both ended with a `{"recorded": 400,
    #: "truncated": true}` object sitting among the query records, which made
    #: the count meaningless as a measurement (401 in both meant only that both
    #: exceeded 400) and made the array heterogeneous for every consumer that
    #: groups by agent or iterates tools.
    def stats(self) -> dict[str, Any]: ...


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


async def _start_gis_run(
    gis_call: GisCall,
    *,
    object_name: str,
    project_id: str | None,
    model_run_id: str | None,
    run_mode: str = 'clean',
    kb_scope_status: str | None = None,
    kb_configured_collections: Sequence[str] = (),
) -> dict[str, Any]:
    """The `start` call, in one place because it is now made from two."""
    return await gis_call(
        {
            'action': 'start',
            'object_name': object_name,
            'project_id': project_id,
            'model_run_id': model_run_id,
            'linked_gis_project_is_object_scope': True,
            # GT-GIS-01. `clean` is the default at every layer, so a caller that
            # says nothing gets a run built from its own evidence.
            'run_mode': run_mode,
            # The KB collection allowlist this contour was *configured* with,
            # sent at start because that is when it is known and complete. What
            # the KB specialist actually searched is not sent because it does
            # not exist to send: `run_agent_task` returns a string, and tool
            # results never come back structurally.
            #
            # `None` means the caller did not say, which GIS records as
            # `unknown`. It is not `unconfigured` -- claiming no allowlist was
            # set on behalf of a caller that never mentioned one is the same
            # substitution that let `run_mode` default to `clean` over runs that
            # had carried a third of their card.
            'kb_scope_status': kb_scope_status,
            'kb_configured_collections': list(kb_configured_collections),
        }
    )


# What a caller sees when the run they named is not there. It names the two
# recoveries rather than only the fault, because the fault is almost always a
# misunderstanding about what `run_id` is for: a user or a model reaching for it
# to "start over" has picked the one lever that does not do that, and telling
# them the run is missing without telling them what to send instead leaves them
# exactly where they started.
UNRESOLVABLE_RUN_ID = (
    'That run does not exist. Omit run_id to start a new run for this object, '
    'or supply run_mode="carry_forward" to reuse the previous card\'s values.'
)


def _run_is_missing(state: Mapping[str, Any] | None, raised: Exception | None) -> bool:
    """Whether GIS is saying "no such run" rather than something else.

    Deliberately narrow in two directions. A 502, a timeout or a malformed reply
    must not be reported as a missing run -- telling someone to start over when
    the service is merely unreachable throws away a run that is still there. And
    on the state side only the error-bearing keys are read, not the whole
    document: `404` occurs by chance in run ids and digests, and a run state
    also carries `not_found` on every field the run could not fill, so scanning
    the body would find the word in the healthiest possible reply.
    """
    if raised is not None:
        text = str(raised)
    else:
        # The shape `_raise_for_gis_error` reads: an `error` and no
        # `workflow_status`. Anything else is a state, whatever it says.
        text = json.dumps(
            {key: (state or {}).get(key) for key in ('error', 'detail', 'message')},
            ensure_ascii=False,
        )
    lowered = text.lower()
    if '404' in lowered or 'not found' in lowered or 'no such file' in lowered:
        return True
    return 'invalid run_id' in lowered


# Statuses that mean the run has produced its card and will not produce another.
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
    # Not an error: the card is real and is what `run_id` promises. Marked on
    # the state so the adapter can say so beside it, and marked here rather than
    # in the adapter because this is the only place that knows the caller
    # supplied a `run_id` at all -- a run that reaches `finalized` in the normal
    # way must not carry the note.
    status = str(state.get('status') or state.get('workflow_status') or '')
    if status in FINISHED_STATUSES:
        state = {**state, 'resumed_run_was_already_finalized': True}
    return state


# Where an attached source keeps its identity, in the order worth trying. Open
# WebUI hands `__files__` through as `metadata['files']` verbatim, and the items
# are not one shape: a plain upload carries `id`, a knowledge collection carries
# `id` with `type: 'collection'`, and several producers nest it under `file` or
# report it as `file_id`.
_SOURCE_ID_PATHS = (('id',), ('file_id',), ('file', 'id'), ('source', 'id'), ('collection', 'id'))


def attached_source_fingerprints(items: Sequence[Any] | None) -> list[str]:
    """A stable identity per attached source, whatever shape it arrived in.

    The first version read `item['id']` and nothing else. Anything without a
    top-level `id` produced an empty string, the empty strings were filtered
    out, and the key came out identical to the no-attachment case -- so asking
    again *with a map attached* replayed the earlier workbook and never opened
    the map, which is precisely the defect that adding attachments to the key
    was meant to fix.

    An item with no recognised id path is hashed whole rather than dropped.
    That is the safe direction: an unknown shape produces a new key and a fresh
    run, where dropping it produces a stale answer. It also means a producer
    that stamps a timestamp into the item defeats reuse for attached runs --
    accepted, because a missed reuse costs time and a wrong reuse costs a wrong
    workbook.

    Sorted and de-duplicated: attaching two maps is one question however the
    client ordered them, and attaching the same map twice is not two questions.
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


# This workflow produces one artefact. The audit and the source report are
# parts of that run, not separate asks -- a caller wanting the CPR would come
# with a different `artifact_set` and get a different key, which is the whole
# point of the set being in the key.
GEOTIZER_ARTIFACT_SET = ('geotizer_object',)


def geotizer_run_identity(
    *,
    requester_id: str,
    object_name: str,
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
) -> RunKey:
    """The persistent identity of "fill GeoTeaser for X", formed before GIS runs.

    Everything a caller can vary that changes the answer, and nothing else. Two
    commands that differ in any of these are different runs; two that differ in
    none of them are the same run and must return the same workbook.

    **`requester_id` is first because leaving it out was a data leak.** The
    binding lives in one deployment-wide `DATA_DIR`, and the run collects KB,
    GIS and web evidence as the *requesting user*, bounded by their knowledge
    grants and by the ACL decision recorded in the dossier's `project_scope`.
    Without the requester in the key, the second person to ask the same question
    is handed the first person's run -- including whatever they could see and the
    asker cannot. Idempotency is per asker, and a shared answer is not a saving
    worth that.

    `project_id` is the scope when the caller pins one. When they do not, GIS
    resolves the project from the object name -- after `start`, which is too
    late to key on -- so the scope is the object they named, marked `object:` so
    it can never be mistaken for a GIS project id. A pinned request is checked
    against the resolved project on reuse; see
    `_refuse_a_reused_run_that_answers_a_different_question` for what an
    unpinned one is and is not protected from.

    `attached_file_ids` is the other half of the vision input.
    `vision_collection_url` was in the key from the start and `__files__` was
    not, which meant asking again *with a map attached* replayed the earlier
    workbook and never opened the map. See `attached_source_fingerprints` for
    why the items are fingerprinted rather than read for an `id`.

    **`attempt_key` is the request, and leaving it out meant an object could be
    filled exactly once.** Everything else here describes *what was asked*, and
    nothing described *when it was asked*, so two identical commands a week apart
    produced one key: the second bound to the first run and `finalize` replayed
    its card -- same id, same coverage, same link, no error and no explanation.
    A user reading that concluded the system could not re-fill an object, and was
    right about the behaviour.

    Idempotency is meant to stop a duplicate *execution* -- a dropped stream, a
    second replica taking the same work -- not to declare an object filled
    forever. Those two are only distinguishable by request identity, and Open
    WebUI already injects one: `__message_id__`. A retry of one tool call carries
    the same id and is still idempotent, which is what `UAT` lost-stream covers;
    a new user message carries a new id and refills.

    `None` is a value like any other here, so a caller with no request identity
    keys exactly as before -- input-only, and reused forever. That is the old
    behaviour rather than a new hazard, and the adapter logs when it happens,
    because falling back silently is the shape of every defect in this file.

    **Not in the key, and it matters.** The GIS template and assignment-policy
    versions arrive in the `start` response, so a run frozen against
    `geotizer_object.v1` keeps its key after GIS moves to v2 and would be reused
    across the change. Closing that needs either a pre-`start` version probe or a
    version recorded beside the binding; neither is done here. Attention register
    A-63.
    """
    if not str(requester_id or '').strip():
        raise GeotizerOrchestrationError(
            'a run identity needs the requesting user; an unattributed key would be '
            'shared across every caller'
        )
    return run_key(
        project_id=(project_id or '').strip() or f'object:{object_name.strip()}',
        artifact_set=GEOTIZER_ARTIFACT_SET,
        frozen_inputs_hash=frozen_inputs_hash(
            {
                'requester_id': str(requester_id).strip(),
                'object_name': object_name.strip(),
                'project_id': (project_id or '').strip() or None,
                'model_run_id': (model_run_id or '').strip() or None,
                'allow_draft': bool(allow_draft),
                # A clean run and a carry-forward run over the same object are
                # different questions and must not share a binding: reusing the
                # carry-forward run's answer for a clean request would hand back
                # the very carried card the request asked to avoid.
                'run_mode': run_mode,
                # The request, not the question. See the note above: without it
                # two identical commands are one key forever.
                'attempt_key': (attempt_key or '').strip() or None,
                'vision_collection_url': (vision_collection_url or '').strip() or None,
                'attached_sources': attached_source_fingerprints(attached_file_ids),
                # A different index answers different questions from the same
                # sources, so a run frozen against one is not an answer for the
                # other. `None` when retrieval v2 is off, which is itself part
                # of the identity.
                'rag': (
                    {
                        'index_version': _rag_v2_index_version(rag_dispatcher),
                        'collections': list(_rag_v2_collections(rag_dispatcher)),
                        'mode': rag_dispatcher.settings.mode,
                    }
                    if rag_dispatcher is not None
                    else None
                ),
                # For the same reason `rag.collections` is here: a run bounded
                # to two geology collections and a run that fell through to the
                # fifty most recently touched knowledge bases are not the same
                # question, and reusing the second's card for the first hands
                # back exactly the unpinned corpus the allowlist was turned on
                # to stop. Adding this key changes every existing binding, which
                # is the safe direction -- the next command starts a fresh run
                # rather than replaying one from before the scope existed.
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
    """Check the reused run against the one thing that compares like with like.

    A pinned request names a GIS project id; GIS reports the project id it
    resolved. Two ids, one comparison, and a mismatch means the binding points
    at another project's workbook -- the worst thing this mechanism could
    return, because it is indistinguishable from a correct answer.

    **The object name is deliberately not compared, and the first version of
    this function did compare it.** That was a permanent break of the ordinary
    path: `state['object_name']` is not what the caller typed. GIS sets it to
    `resolved.name or object_name`, and its resolver casefolds, folds `ё` to
    `е`, strips `площадь`/`участок`/`объект` and trims adjective endings before
    matching. So the run for "Лекын-Тальбейская площадь" comes back holding the
    project's canonical name, a byte-exact `!=` fires, and every repeat of the
    command is refused forever -- worse than having no idempotency, because the
    first call succeeds and only the retries fail.

    Reimplementing that normalisation here to compare properly is the other
    trap: it is `gis_service`'s rule, it changes when GIS changes, and a
    caller-side copy of it is the drift `validation.py` already argues about at
    length.

    What is left unguarded, said plainly: an unpinned request scoped
    `object:<typed name>` where GIS resolves the same typed name to a
    *different* project than it did before. That needs a GIS-side change to the
    project set or the resolver between two runs. It is narrower than it looked
    -- resolution is deterministic for a fixed project set -- and it is
    registered as A-64 rather than papered over.
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
    object_name: str,
    project_id: str | None,
    model_run_id: str | None,
    run_id: str | None,
    allow_draft: bool,
    gis_call: GisCall,
    agent_call: AgentCall,
    rag_dispatcher: RagDispatcher | None = None,
    query_drain: QueryDrain | None = None,
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
) -> dict[str, Any]:
    """Effect shell around the pure GeoTeaser planner and validators.

    `run_registry` is the persistent key -> run binding. `None` means no
    idempotency and every command starts a run, which is what every command did
    before CORE-BOUNDARY-01 action 6 had an implementation; the contour decides,
    and `build_run_registry` returns `None` when `DATA_DIR` is not writable.

    `requester_id`, `vision_collection_url` and `attached_file_ids` are used for
    one thing only: the run's identity. The vision call built from the last two
    arrives separately as `vision_evidence_call`, and a run that looked at a
    different collection, or at a different set of attached maps, is a different
    run. Without a `requester_id` there is no identity to form and the registry
    is bypassed -- an unattributed key would be shared across callers.

    `kb_scope_status` and `kb_configured_collections` are the contour's KB
    collection allowlist as *configured*, handed in as plain data because
    reading an environment variable is an effect and this module has none. They
    go into the run key and into the GIS run state. `None` means the caller did
    not say, which is recorded as `unknown` rather than as "no allowlist was
    set" -- the difference between a fact and a silence.

    `status` is the language and verbosity the progress lines are written in,
    read by the adapter off the orchestration tool's stored valve row so that
    the specialist half and this half of one run cannot disagree. `None` is the
    same pair that tool ships as its defaults, which is what a run driven from
    a test or from an unconfigured contour gets.
    """
    status = status or StatusSettings()
    # Run-level notes, threaded rather than returned. Every repair this code
    # makes to an owner envelope appended to a local list that nothing read --
    # `normalize_source_inventory`'s source rebuilds and the patch coercions
    # both -- while both docstrings said the notes "are surfaced as run
    # degradations". They were not surfaced anywhere. A card built on
    # reconstructed source metadata, or on a status this code overrode, has to
    # say so; that was the whole condition on making those repairs silent-safe.
    # Notes, not sentences. A cell-counting note stays as its rule and its
    # cells until `render_run_notes` turns the whole run's worth into one line
    # per rule; a note about the run itself is already a sentence and passes
    # through.
    run_notes: list[Any] = []
    # The searches the specialists were actually planned to issue. Two clean
    # runs against a pinned corpus moved 31 cells out of one batch and 28 into
    # another, and nothing in either `state.json` says what was searched --
    # `exact_query` appears zero times in both. A variance nobody can attribute
    # is a variance nobody can damp, and every measurement queued behind it is
    # uninterpretable until its size is known.
    query_log: list[dict[str, Any]] = []
    # `Расширение использования GIS` §5.2. What the GIS service actually did,
    # per role: the layer it resolved, the features it measured, the CRS it
    # measured in, the raw distance before formatting, and the reason a role
    # produced nothing. §3.3.2 is the defect -- a value in the card could not
    # be traced back to the operation that produced it, and an absent value
    # could not be explained at all. Every later stage's acceptance criteria
    # read this record, which is why it lands before the calculations change.
    gis_trace_log: list[dict[str, Any]] = []
    # What the deterministic calculation proposed and the run could not use.
    # `unusable_field_proposals` was added to end silent drops and reaches only
    # the batch's own evidence item, which no artefact carries: on run
    # `1c46b6ca` a reader asking «was a value computed for this empty cell and
    # thrown away?» had the same nothing to read as before the diagnostic
    # existed. A finding nobody can see has not been recorded.
    gis_rejection_log: list[dict[str, Any]] = []
    # One GIS calculation per run, not one per batch chunk. `GIS-DC` is
    # chunked and every chunk holding an infrastructure row asks for the
    # whole twelve-role calculation, which depends on the project and not on
    # the chunk. Run `08330f72` ran it twice: 24 trace entries for 12 roles,
    # pairwise identical `trace_id`s and two different `duration_ms`.
    infrastructure_cache: dict[str, Any] = {}
    owner_fields_per_call, chunk_size_note = resolve_owner_fields_per_call(owner_fields_per_call)
    if chunk_size_note:
        run_notes.append(chunk_size_note)
    # Started here, at the top of the run, rather than at the first batch: the
    # setup before batch one -- scope resolution, the DataCube review, the
    # retrieval plan -- is inside the fill and would otherwise be outside its
    # only bound.
    deadline_seconds, deadline_note = resolve_fill_deadline(fill_deadline_seconds)
    if deadline_note:
        run_notes.append(deadline_note)
    deadline = FillDeadline(deadline_seconds)
    deadline_stopped_at = ''
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
            # Deliberately not in the run key: a drain observes and changes
            # nothing a caller can vary about the answer. Two commands that
            # differ only in whether queries were recorded are one run.
            kb_scope_status=kb_scope_status,
            kb_configured_collections=kb_configured_collections,
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
            )
            # Before the binding, not after: a key bound to a run that failed to
            # start is a key that can never be satisfied and never be retried.
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
        )
    _raise_for_gis_error(state)
    active_run_id = str(state.get('run_id') or run_id or '')
    # Handed out the moment the run exists in the GIS store, because from here
    # an exception can escape and the id is the only thing that makes the run
    # recoverable. It used not to: an `AttributeError` on batch 2 reached the
    # caller as `run_id: null, resumable: false` on a run whose first batch had
    # already been applied. Losing the id is worse than the crash that lost it.
    #
    # A mapping the caller owns rather than an attribute on the exception: the
    # exception types that escape here are arbitrary -- `AttributeError` was
    # the one that did -- and not all of them accept attribute assignment.
    if started_run is not None:
        started_run['run_id'] = active_run_id
    if resolution is not None and resolution.abandoned_run_id:
        # Another caller bound the key while this one was starting. Its run is
        # real, sitting in the GIS store, and nothing will ever finish it.
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
            # A run reached through the key is a retry too. Keyed on the
            # `run_id` parameter alone, a reused run was written into the shadow
            # dataset as a first attempt, and the A/B comparison would have been
            # counting resumes as fresh runs.
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
        # The configured collections, so the plan states where to search and
        # not only what to search for. A-88: with only query terms in it, the
        # corpus and the phrase arrived as one list and the GIS project id in
        # that list was read as a corpus.
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

    # Read once, before the loop, not off each submit response. Every GIS
    # summary carries it, so per-iteration would be equivalent today -- and on
    # the day one response omits it the run counts «пакет 1 из 8», «пакет 2»,
    # «пакет 3 из 8». A denominator that appears and disappears mid-run reads as
    # the plan having changed, which is worse than never having had one.
    batches_total = state.get('batches_total')
    for batch_index in range(MAX_BATCHES):
        next_batch = state.get('next_batch')
        if not next_batch:
            break
        # Checked here, between batches, and again between the chunks inside
        # one -- never around a call. Expiry does not cancel anything: the
        # batch is still submitted, and submitted complete, because
        # `missing_owner_batches` refuses a finalize with a batch outstanding
        # whatever `allow_draft` says. What stops is the calling. A batch
        # closed this way costs no specialist and no owner call and reaches
        # the card saying which fields were never requested.
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
        state = await _produce_and_submit_owner_batch(
            current_state=state,
            next_batch=next_batch,
            owner_fields_per_call=owner_fields_per_call,
            run_notes=run_notes,
            query_log=query_log,
            gis_trace_log=gis_trace_log,
            gis_rejection_log=gis_rejection_log,
            infrastructure_cache=infrastructure_cache,
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
    # Sent *into* finalize, not attached to what finalize returns. The
    # orchestrator's record of a run -- the GIS execution protocol, the
    # retrieval queries actually issued, the run notes -- is not a property of
    # any patch, so it has never had a way into the state, and decorating the
    # terminal payload with it means the only reader is the model that gets one
    # look at it.
    #
    # Run `8a02f724` measured the cost: `gis_execution_trace`,
    # `raw_measurement`, `retrieval_queries` and `layer_not_found` all read zero
    # in the exported state, while `negative_findings` read 14 and
    # `semantic_role` 20 -- the two that ride on a patch's `source_locator`
    # arrived and every one that rode the payload did not. Stage 1 shipped onto
    # the second vehicle because it was placed beside `retrieval_queries`, which
    # had been failing the same way since it shipped.
    # One per run, read out of the cache the calculation already fills rather
    # than threaded through the chunk loop: the manifest is a property of the
    # linked project, so every chunk that asked got the same one.
    layer_manifest = next(
        (
            payload['layer_manifest']
            for payload in infrastructure_cache.values()
            if isinstance(payload, Mapping) and payload.get('layer_manifest')
        ),
        None,
    )
    # Resolved here and not where each rejection was recorded: at the moment a
    # batch defers a key, the batch that owns it has not run yet.
    mark_rejections_answered_elsewhere(gis_rejection_log, state.get('fields') or [])
    run_log = {
        key: value
        for key, value in (
            # Rendered here, once, and not where each rule fired. A rule fires
            # per chunk; the reader wants it per run. `render_run_notes` also
            # subsumes the deduplication this line used to do -- `dict.fromkeys`
            # could never merge «1 ячеек (r078)» with «1 ячеек (r084)», which is
            # why run `af707b17` shipped nine copies of one rule.
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
            # Beside the list, not inside it. `issued` counts every search the
            # run made and stays a measurement whether or not the cap bound.
            (
                'retrieval_query_stats',
                _query_stats(
                    query_drain,
                    query_drain.drain() if query_drain is not None else [],
                    kb_configured_collections,
                ),
            ),
            ('gis_execution_trace', gis_trace_log or None),
            # `Расширение использования GIS` Stage 3 is scoped by what the
            # linked project holds, and no run has ever said what that is: the
            # working inventory was cut by hand from seventeen exported states
            # and reached 22 of a reported 34 layers with no way to close the
            # gap.
            ('gis_layer_manifest', layer_manifest),
            # Beside the manifest, not inside the trace: the trace records what
            # the calculation did, and this records what the orchestration did
            # with the result. A cell empty because nothing was proposed and a
            # cell empty because a proposal was refused are different findings
            # and used to look identical from here.
            ('gis_proposal_rejections', gis_rejection_log or None),
            # §5.9. The trace says which roles found no layer and the cells
            # say where the run went instead; neither says the other, so
            # «did the run compensate for a missing layer, and did it work?»
            # was a question only a human reading the card could answer.
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
    # Carried from the resume rather than re-derived: `finalize` replays a
    # completed run and returns the same `finalized` state a first finalize
    # returns, so by this point the two are indistinguishable. Only the resume
    # branch knows the caller named a run that was already done.
    if state.get('resumed_run_was_already_finalized'):
        final = {**final, 'resumed_run_was_already_finalized': True}
    # From the resolution, not from the request. `resolution.reused` is the
    # registry saying it found this key already bound; nothing else in the run
    # can tell a first execution from a replay of one, because by this point
    # they produce the same terminal payload.
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
    if query_stats:
        final = {**final, 'retrieval_query_stats': query_stats}
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
    """How many batches the deadline stopped short of, counting the one it
    stopped on.

    From `batches_total` when GIS sent it, which every summary does, and from
    the applied count otherwise. Never from `MAX_BATCHES`: that is the loop's
    own safety ceiling at 12 and has nothing to do with how many batches this
    policy has, so a card built from it would report four phantom batches as
    unrequested on a run that never had them.
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
    deadline: FillDeadline | None = None,
) -> dict[str, Any]:
    chunks = partition_owner_batch(
        next_batch,
        max_fields=owner_fields_per_call,
    )
    # The resolved scope name, not the one the caller typed. On run
    # `6056e157` the request said `Лекын_Талбейское` and the subarea rows
    # carried `Лекын-Тальбейская площадь` -- `object_scope.object_name`
    # verbatim -- so a check against the request would have matched neither
    # spelling and passed the cells it exists to refuse.
    # Both names, because either can be the one a specialist echoes and the
    # rule that compares against only one of them passed `Участок 4` carrying
    # the object's own name on run `92661b9b`.
    scope_names = [
        str((current_state.get('object_scope') or {}).get('object_name') or ''),
        str(object_name or ''),
    ]
    scope_name = [name for name in scope_names if name.strip()]
    envelopes = []
    for chunk in chunks:
        # Between chunks, which is the check that does the work. A batch is up
        # to twenty-five chunks of contributors plus an owner, so a deadline
        # tested only between batches can overshoot by an hour. Here the
        # overshoot is one chunk, and it is the chunk already in flight -- this
        # returns before any call is made, never during one.
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

    Two carriers, both uuid-shaped: `source_locator.document_id`, and the
    `source_refs` that embed the same id inside a longer key
    (`kb-lic-legal__part_1__<uuid>__geotizer_object.v1.r001.a01`). Split on the
    separator rather than parsed, because the key's shape is the batch's and
    this only needs the parts.
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

    Two facts that belong beside the query list rather than inside it.

    The counts, because the previous cap reported itself as an *entry*:
    `{"recorded": 400, "truncated": true}` in the same array as the query
    records. Runs `82365089` and `26aaf34a` both ended at exactly 401 entries,
    which told a reader only that both exceeded 400 — the number stopped being
    a measurement at the moment it started mattering, and every comparison of
    those two query sets compares two truncated prefixes.

    The collections, because a run reads collections nobody attached and
    nothing in the artefact said so. Those two runs made 31 and 52 KB calls
    that named no collection at all, and **every** hit on another tenant's
    corpus — 350 and 400 of them across 24 documents — came from exactly those
    calls. This is a marker, not a fence: which collections a user attached is
    a statement about one run and must never become a permanent permitted set,
    so what is recorded is what was read and which of it was unmarked. Naming
    it is the point; refusing it is not.
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
    if read:
        stats['collections_read'] = sorted(read)
        stats['collections_marked'] = sorted(marked)
        # Read and not attached to this run. Not a violation — the answer may
        # genuinely live elsewhere, and the user may have attached the wrong
        # thing — but a reviewer should be able to see it without reading 400
        # query records.
        stats['collections_read_unmarked'] = sorted(read - marked) if marked else []
    return stats or None


def _queries_with_citations(
    issued: Sequence[Mapping[str, Any]],
    planned: Sequence[Mapping[str, Any]],
    fields: Sequence[Mapping[str, Any]],
    marked_collections: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The queries a run issued, each with how much of what it returned was cited.

    Issued first, then the RAG-v2 plans if any were recorded, and every entry
    says which it is. The two answer different questions — what a specialist
    was asked to look for, and what it actually asked — and a reader who cannot
    tell them apart would take a plan built from the batch, near-identical
    between runs, for the thing that varies.

    `citations` joins on the document id and on nothing else. The first pair of
    runs carried `citations_by_name`, a join on the filename, and it returned
    **0 on every one of the 406 entries that had results**: a KB result carries
    `Проект ГРР Лекын-Тальбейское 2025.pdf` and a cell's locator carries
    `document_id: cdd1bdf0-…`. The two sides share no token, so the join was not
    weak — it could not match, ever.

    The field is written only when both sides can be compared: the entry has
    document ids and the run has cited ids. A field that is always zero is
    worse than an absent one, because a reader takes it for a measurement and
    concludes nothing was cited. The same argument as `measured: false` beating
    a silently stale band.
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
            # Which collection each cited document came from, where the tool
            # knew. `grep_knowledge_files` builds the mapping as it collects
            # files; the vector path of `query_knowledge_files` gets a filename
            # and a file id from the store and no collection, so an unknown one
            # is left out rather than guessed at.
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

    The scope is entered *inside* the coroutine rather than around the gather
    that schedules them: `contextvars` are copied when a task is created, so a
    scope set before `asyncio.gather` would label all six contributors with
    whichever agent happened to be set last. Entered here, each contributor
    runs in its own task with its own scope.

    With no drain injected this is `agent_call` and nothing else, which is what
    every test that does not care about queries gets.
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
    allowed_field_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    evidence = await _deterministic_infrastructure_evidence(
        next_batch=next_batch,
        run_id=run_id,
        allowed_field_keys=allowed_field_keys,
        gis_call=gis_call,
        cache=infrastructure_cache,
    )
    # Appended at the run level rather than left inside the batch's evidence:
    # the record answers "what did GIS do on this run", and a reader comparing
    # two runs should not have to reassemble it from eight batches.
    #
    # Once per attempt, not once per chunk. `GIS-DC` is chunked, the
    # calculation is cached per run, and every chunk holding an infrastructure
    # row still receives the whole cached result -- so run `84afa9e2` recorded
    # 24 entries for 12 roles with pairwise identical `trace_id` *and*
    # identical `duration_ms`, which is one execution written down twice. The
    # per-run cache stopped the second call; this stops the second write.
    #
    # `trace_id` is a content hash over (project, run, role, layers), so it is
    # the identity of the attempt rather than of the write, which is exactly
    # what has to be unique here. A genuine second execution of the same role
    # in one run would collide with it -- and that is not a thing this workflow
    # does, because the cache is what guarantees it.
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
    # Collected beside the trace and for the same reason: the question is
    # «what did GIS propose on this run, and what became of it», and a reader
    # should not have to reassemble the answer from eight batches.
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
    # `contributor_results` is a gather over `contributors`, so the two are the
    # same length by construction; `strict` says so where it is relied on.
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
) -> dict[str, Any]:
    previous_output = ''
    feedback: Any = None
    # Repairs this code had to make to the owner's output, carried out of the
    # attempt loop so a run that needed one says so.
    # The caller's list when it threaded one, so a repair recorded here reaches
    # the run rather than a local that nothing reads.
    degradations: list[Any] = run_notes if run_notes is not None else []
    candidate_envelopes: list[Mapping[str, Any]] = []
    attempt_diagnostics: list[Mapping[str, Any]] = []
    # One entry per attempt. `feedback` is overwritten each round because the
    # prompt should show the model only what it did wrong last time; the record
    # of what the contract refused must not be overwritten with it.
    feedback_by_attempt: list[Mapping[str, Any]] = []
    # Reset by any attempt that returns characters, so only a *run* of empty
    # responses stops the loop.
    consecutive_empty = 0
    # The last attempt's violation set, so an attempt that changes nothing can
    # be recognised. Run `06fec58d` spent three attempts of 21 816, 19 532 and
    # 21 959 characters on one chunk, each producing the same violations, and
    # lost 25 cells. The empty-response path already stops after two because a
    # third is pointless; an identical violation set is pointless for the same
    # reason, and costs more because the contract *was* reached.
    previous_violations: frozenset[str] | None = None
    repeated_violations = False
    # Every specialist failure this batch saw, and how many ended it. Both,
    # because they answer different questions: chunk 1/3 of `KB-GRR-FACTORS`
    # failed in the specialist on its middle attempt only, and a list cleared
    # by the next attempt would have thrown that away -- which is how the run
    # came to report a contract violation for a batch that had lost a
    # specialist call.
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
        # This attempt's repairs, held here rather than appended to the run as
        # they happen. Every rule below runs on every attempt, and an attempt
        # that fails validation is discarded -- but its notes were not, so run
        # `84afa9e2` reported the lone-WEB resource refusal five times over
        # overlapping cell sets: «3 ресурсных ячеек (r045.a03, r046.a05,
        # r046.a06)» beside «4 ресурсных ячеек (r045.a05, r045.a06, r046.a05,
        # r046.a06)», two attempts at one chunk. Deduplication by exact text
        # cannot collapse those, because the text differs. Only the attempt
        # that ships has anything to report.
        attempt_notes: list[Any] = []
        prompt = _owner_prompt(
            context=context,
            attempt=attempt,
            # Bounded here rather than in `_owner_prompt`, because selecting
            # the patches a violation names means parsing the failed draft and
            # that parser is a layer above the prompt builder.
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
            # The round. An owner that searched again after a repair is the
            # case the attempt number exists to separate.
            attempt=attempt,
        )
        previous_output = raw
        diagnostic = owner_attempt_diagnostic(raw, attempt=attempt, request=prompt)
        attempt_diagnostics.append(diagnostic)

        # An empty response is not a contract failure, and retrying it is not a
        # repair. There is no output to quote back, so the next prompt is the
        # prompt that already produced nothing. Name it and stop rather than
        # spending another specialist call on the same question.
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

        # The specialist saying its own call failed. Not an owner response, and
        # validating it as one is what produced eighteen violations reading
        # `batch_id: expected 'KB-GRR-FACTORS', got None` -- feedback telling
        # the model to fix a field in a message it never wrote. The envelope
        # asks for at most one retry in as many words; the run made three.
        signal = specialist_failure_signal(raw)
        if signal is not None:
            specialist_failures.append(signal)
            consecutive_specialist_failures += 1
            diagnostic = {**diagnostic, 'specialist_failure': signal}
            attempt_diagnostics[-1] = diagnostic
            feedback = [
                f'{signal["agent"] or "specialist"} reported '
                f'{signal["code"] or "a failure"} on attempt {attempt}; '
                'no owner envelope was produced.'
            ]
            feedback_by_attempt.append({'attempt': attempt, 'violations': list(feedback)})
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
            # This record used to be written only at the bottom of the loop, so
            # an attempt that never produced an envelope contributed nothing to
            # it. On run `6056e157` that left `owner_attempt_feedback` empty for
            # `KB-GEO` and `KB-GRR-FACTORS` -- 20 of the 35 lost cells, and
            # exactly the two chunks whose failure was hardest to read.
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

        # Before anything else reads `source_refs`: make the inventory
        # submittable. An owner that wrote its contributor evidence under the
        # evidence schema instead of the submission schema passes every local
        # check and is rejected 422 at `submit_batch`, after the whole batch has
        # been built -- and the repair remaps the refs, so it has to run before
        # the enrichment passes that read them.
        envelope, source_repair_notes = normalize_source_inventory(envelope)
        for note in source_repair_notes:
            # A degradation, not a diagnostic: the card was built on source
            # metadata this code reconstructed, and a reader comparing two runs
            # needs that to be visible rather than inferable.
            if note not in degradations:
                degradations.append(note)

        # Before `repair_negative_provenance`, and the order is load-bearing.
        # That pass registers a synthetic source for `not_found` patches whose
        # `source_refs` are empty, so a patch coerced to `not_found` here still
        # gets one; coerced after it, the same patch dies on
        # `source_refs must be non-empty` instead -- one violation traded for
        # another, which is the failure mode this whole repair exists to avoid.
        envelope, coercion_notes = coerce_contradictory_patch_fields(envelope)
        for note in coercion_notes:
            if note not in degradations:
                degradations.append(note)

        # Before validation, because the point is that the contract should
        # never have asked for it: the row declares the stage and the backend
        # can read it off `row_id`. On run `05169ef1` this was three attempts
        # and eighteen cells of `work_stage is incompatible with row N; got
        # '(unset)'`, repeated identically because there was nothing the model
        # could learn from the feedback that it had not already been told.
        # Before every other repair, so each of them sees one shape. The
        # readers all parse now, but a repair that writes a key onto a locator
        # should not be the thing deciding what shape it was.
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

        # Beside it, because the two halves of a negative are the source that
        # searched and the reason the cell is empty, and only the first had a
        # repair. GT-POLICY-01 asks for the second.
        envelope, negative_notes = state_the_negative_search(next_batch, envelope)
        attempt_notes.extend(negative_notes)

        # And the third half of the same problem: a ref the owner recorded
        # inside a locator and never registered. Before validation, so the
        # contract's own check on nested refs is an invariant rather than a
        # rejection the owner has no way to repair.
        envelope, locator_ref_notes = register_locator_only_sources(
            next_batch,
            envelope,
            run_id=run_id,
        )
        attempt_notes.extend(locator_ref_notes)

        # After `repair_negative_provenance`, and the order is load-bearing for
        # the same reason the coercion runs before it. That pass registers a
        # synthetic source only for patches still reading `not_found`, so a
        # cell re-statused here first would lose its source and die on
        # `source_refs must be non-empty`.
        envelope, exclusion_notes = classify_rule_excluded_patches(next_batch, envelope)
        attempt_notes.extend(exclusion_notes)
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
        # After every applier, because the rule reads the sources a cell ended
        # up with rather than the ones any one pass proposed.
        envelope, lone_web_notes = refuse_lone_web_resource_values(envelope)
        attempt_notes.extend(lone_web_notes)
        envelope, spatial_notes = refuse_unanswerable_spatial_rows(
            envelope,
            _unanswerable_spatial_rows(combined_evidence),
        )
        attempt_notes.extend(spatial_notes)
        # After the divergence record exists and before it is counted: the rule
        # reads `spatial_divergence.measured` to find the replacement, so it
        # cannot run before the appliers, and a cell it fills from a
        # measurement is no longer a cell that declined one.
        envelope, radius_notes = refuse_out_of_radius_infrastructure(envelope)
        attempt_notes.extend(radius_notes)
        # After the radius rule, which *fills* infrastructure cells from a
        # measurement: a cell it repaired now holds a number and must not then
        # be refused for holding prose.
        envelope, numeric_notes = refuse_prose_in_numeric_rows(next_batch, envelope)
        # After the prose rule and before the value is weighed against anything
        # else: a value of the wrong kind is not a candidate for anything, and
        # letting it into conflict resolution would have the run choosing
        # between two answers to different questions.
        envelope, kind_notes = refuse_the_wrong_kind_of_answer(next_batch, envelope)
        # Relabel before refusing, so the figure kept as a candidate records
        # what it actually is. A number transcribed off a layer summary is
        # `direct`, and the refusal below then quotes it as such.
        envelope, reading_notes = a_reading_is_not_a_computation(envelope)
        envelope, unit_notes = refuse_a_unit_the_source_contradicts(envelope)
        numeric_notes = [*numeric_notes, *kind_notes, *reading_notes, *unit_notes]
        attempt_notes.extend(numeric_notes)
        attempt_notes.extend(spatial_divergence_notes(envelope))
        # Last, because the appliers above form conflicts of their own and
        # those do carry their sides. What is left after them is what the
        # owner declared for itself.
        envelope, unrecorded_conflict_notes = record_unrecorded_conflicts(envelope)
        # Beside it, and the pair covers the two ways a declared conflict can
        # have nothing to resolve: no sides recorded at all, and sides recorded
        # of which only one states a value.
        envelope, one_sided_notes = refuse_one_sided_conflicts(envelope)
        # §5.6's audit. Not a conflict between two sources -- a conflict
        # between what the card asserts and what it leaves empty.
        envelope, contradiction_notes = flag_model_contradictions(envelope)
        # Stage 6's GIS half: the licence polygon's own term is the outer
        # bound on anything the plan schedules.
        envelope, plan_term_notes = flag_plan_beyond_licence_term(
            envelope,
            accepted_fields=context.get('accepted_field_summary') or (),
        )
        # A-88's conclusion path. A cell closed `not_found` after searching
        # something that is not a corpus reports the knowledge base as
        # consulted and empty; it was never opened.
        # Read off the plan the owner was handed rather than threaded in as a
        # parameter: `corpus_scope` says what is not a corpus, and it already
        # travels with the context. A separate argument would be a second copy
        # of the same fact, free to disagree with the one the owner saw.
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
        # Last, because it is the only pass whose subject is what the passes
        # before it did. Every rule above may move a status, and a reason
        # projected for the status a cell used to have is worse than no reason
        # at all -- the reader trusts the sentence over the label.
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
            return envelope
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
        # The sentence turns on how the batch *ended*, the record on
        # everything it saw. A batch whose last attempt reached the owner
        # contract failed the owner contract, however it started.
        ended_in_specialist_failure=bool(consecutive_specialist_failures),
        # Two different failures, and a reader deciding whether to rerun needs
        # them apart: a contract failure may pass on a rerun, an unchanged
        # violation set will not.
        unactionable_feedback=repeated_violations,
        run_id=run_id,
        # Not `MAX_OWNER_ATTEMPTS`: a run of empty responses stops the loop
        # early, and a card claiming three attempts when two were made sends
        # the next reader looking for a third that does not exist.
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
    # The notes were discarded here while the attempt loop reported its own,
    # which is the wrong way round: no attempt shipped, so the only envelope a
    # reader will ever see is this one, and every refusal it makes is invisible.
    enhanced, fallback_notes = refuse_lone_web_resource_values(enhanced)
    enhanced, unanswerable_notes = refuse_unanswerable_spatial_rows(
        enhanced,
        _unanswerable_spatial_rows(combined_evidence),
    )
    enhanced, radius_notes = refuse_out_of_radius_infrastructure(enhanced)
    enhanced, numeric_notes = refuse_prose_in_numeric_rows(next_batch, enhanced)
    enhanced, kind_notes = refuse_the_wrong_kind_of_answer(next_batch, enhanced)
    enhanced, reading_notes = a_reading_is_not_a_computation(enhanced)
    enhanced, unit_notes = refuse_a_unit_the_source_contradicts(enhanced)
    numeric_notes = [*numeric_notes, *kind_notes, *reading_notes, *unit_notes]
    enhanced = promote_assemble_conclusions(
        next_batch,
        enhanced,
        context.get('accepted_field_summary') or [],
    )
    # The fallback carries locators forward from attempts that did not ship, so
    # it can hold a nested ref for a source no surviving inventory has.
    enhanced, fallback_ref_notes = register_locator_only_sources(
        next_batch,
        enhanced,
        run_id=run_id,
    )
    enhanced['run_id'] = run_id
    if validate_owner_envelope(next_batch, enhanced, object_name=scope_name or [object_name]):
        return fallback
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
    return enhanced


def record_gis_proposal_rejections(
    log: list[dict[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    *,
    batch_id: str,
) -> None:
    """Every computed proposal the run did not use, in one run-level list.

    `unusable_field_proposals` and `deferred_field_keys` are per-batch findings
    on a per-batch evidence item, and no artefact carries an evidence item. Run
    `1c46b6ca` finalized with both keys computed and neither readable: a reader
    holding the run log and asking «was a value computed for this empty cell
    and thrown away?» had exactly the nothing the diagnostic was written to
    replace.

    The batch id travels with each entry because `not_this_batch` is only
    meaningful against the batch that refused it -- the same key deferred by
    `GIS-DC` and used by `KB-STUDY` is routing working, and deferred by every
    batch is a key with no owner.
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

    Run `4ad8fd75` logged 39 rejections, every one `not_this_batch`, and two of
    them are `r037.a01` and `r037.a03` — keys `KB-STUDY` answered. A reader
    holding that list cannot tell a proposal that found its owner from one that
    found nobody, so all 39 read as loss and the log invites the question it
    was added to close.

    Resolved at the end of the run against the finalized cells rather than at
    the moment of refusal, because at that moment the answer does not exist
    yet: `GIS-DC` defers `r037.a01` before `KB-STUDY` has run.

    `answered_elsewhere` is about the cell, not about this proposal. A cell an
    owner filled from its own reading counts as answered — the key is not lost
    — and whether the *computation* reached it is the separate question
    `value_origin` records.
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
    # Which batch may *read* the calculation, not which batch it replaces the
    # GIS contributor for. `_needs_deterministic_infrastructure` answers the
    # second question and has a side effect in `_contributors_for_batch`;
    # `KB-STUDY` reads the study half of this payload and keeps its own GIS
    # contributor, which asks things this calculation does not.
    if not _receives_deterministic_gis(next_batch):
        return []
    # The calculation reads the run's linked project and measures twelve roles
    # against the licence polygon. Nothing in it depends on which chunk of
    # `GIS-DC` is asking, so a second chunk gets the first chunk's answer.
    # `allowed_field_keys` differs per chunk and is applied below, after the
    # call, so the cached result is still filtered to the chunk that asked.
    deterministic = cache.get(run_id) if cache is not None else None
    if deterministic is None:
        deterministic = await gis_call(
            {
                'action': 'infrastructure_proposals',
                'run_id': run_id,
            }
        )
        if deterministic.get('workflow_status') not in {'ready', 'partial'}:
            raise GeotizerGisError(deterministic.get('error') or deterministic.get('violations') or deterministic)
        if cache is not None:
            cache[run_id] = deterministic
    # The linked project's inventory is a fact about the run, not evidence for
    # a cell, and it is the largest block in the payload -- 34 layers against
    # the twelve roles a chunk asks about. It stays in the cache, where the run
    # reads it for `run_log`, and out of the blob the owner is given.
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
            # Structured, not left in the JSON blob above. `layer_not_found`
            # has always been in `warnings`; carrying it as data is what lets
            # a rule read it instead of a model.
            'unanswerable_field_keys': [
                item
                for item in deterministic.get('unanswerable_field_keys') or []
                if isinstance(item, Mapping) and str(item.get('field_key') or '') in set(allowed_field_keys)
            ],
            # Structured for the same reason. `Расширение использования GIS`
            # §5.2 requires the protocol to reach the run's state, and §3.3.2
            # is what it is for: a value in the card could not be traced to
            # the layer, feature, filter, CRS and operation that produced it,
            # and an *absent* value could not be explained at all.
            'gis_execution_trace': [
                dict(item)
                for item in deterministic.get('gis_execution_trace') or []
                if isinstance(item, Mapping)
            ],
            # What this batch was handed and does not own. One calculation
            # answers eighteen roles across two batches, so a proposal outside
            # `allowed_field_keys` is not lost -- it is another batch's, and
            # `_receives_deterministic_gis` delivers the study half to
            # `KB-STUDY` so the owner of the key gets asked. The finalized
            # backstop is the audit's `gis_proposals_reached_cells`: a key
            # that reaches no batch at all still has an empty cell, and that
            # check is what refuses to let it pass unremarked.
            #
            # Read from the filter now instead of re-derived here. The old
            # version rebuilt this set from its own copy of the
            # `field_key not in allowed` test, which meant a *malformed*
            # foreign proposal was reported as merely deferred -- and, worse,
            # a proposal for a key this batch did ask for, dropped for a bad
            # `value_origin` or a missing `source_id`, was reported nowhere at
            # all. Two copies of one test, free to disagree.
            'deferred_field_keys': sorted(
                {
                    rejection['field_key']
                    for rejection in rejected
                    if rejection['reason'] == 'not_this_batch'
                }
            ),
            # The other half, which routing cannot reach: this batch asked for
            # the key, a value was computed for it, and it was unusable. An
            # empty cell whose reason is «нечего было предложить» and one
            # whose reason is «предложено и отброшено» are different findings.
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
