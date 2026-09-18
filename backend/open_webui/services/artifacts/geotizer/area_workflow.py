"""An area fill is the object fill run per member, and nothing new per member.

`geotizer_area_scope` resolves an area into members with a hierarchy between
them. Filling one is a separate question, and this module is the composition
that answers it — deliberately *not* a mode inside `run_geotizer_workflow`.

**Why composition and not `if area:`.** The single-object path is the measured
one: four clean runs of one build filled 207, 191, 219 and 137 of 351 cells, and
three pairs since have measured status agreement at 202, 183 and 193. Every
refusal in that path is tuned against that behaviour. A branch inside it puts
the measured path one step from an unmeasured one and makes the band describe
«a run in one of two modes», with the second mode instrumented by nothing.

The inventory behind this split is
`GMM/operations/design/2026-09-04__what-in-the-fill-assumes-one-object.md`. Its
short form: identity, the batch loop, the owner calls, carry-forward and every
run-level record are already per object and are reused untouched. Four things
assume there is only one — the object-scope binding over four cells, the licence
polygon as source geometry, the envelope's expected object name, and the 351-cell
`completeness` denominator — and this module supplies its own for the first
three and refuses the fourth.

**It aggregates now, and it did not.** GTA-04 was held on two grounds and both
have moved — differently, which is worth stating because the difference is what
makes a partial area foldable at all. The 351 operators were **decided**: the
policy is committed, seventeen operators over 351 rows, and `gis_service`
carries it and checks its digest on every load. The variance was **measured**,
not decided: 202 of 351 cells were a draw across four runs of one build, and
rather than waiting for that to stop being true the fold answers it — every
figure an absent member could only have added to carries a `value_range`, so a
total over a partly-filled area states its own bound instead of pretending to
be exact. A decision closed the first ground; a measurement made the second one
survivable.

So `aggregation` is performed when a fold is wired in, and still carries a
state and a reason when it is not — a missing key and a zero remain the two
things it must never be.

`link_status` is UNENFORCED in the dossier contract, and the component that
refuses a `candidate` link is the aggregator, which now exists: `fold_area`
takes the scope manifest and gates every reducing operator on its memberships.
Omit the manifest and the link guard is skipped and says so, which is the one
case where the double-count guard still does not run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

#: The single-object fill, injected rather than imported, for the same reason
#: `gis_call` is: this module composes an effect and performs none. It also
#: makes the composition testable without a GIS service, which is what lets the
#: ordering and the refusals be checked at all.
MemberFill = Callable[..., Awaitable[dict[str, Any]]]

#: The GIS service call, injected for the same reason. The fold reads the
#: members' cards out of the service's own run store, so this module sends run
#: ids and never assembles 351 cells per member to ship over a wire.
FoldCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


NOT_PERFORMED = 'not_performed'
PERFORMED = 'performed'

#: No fold was asked for. Not «the aggregator is held» — it is not, and a
#: reason that outlives its cause is how a reader infers a constraint that was
#: lifted months ago.
FOLD_NOT_REQUESTED = 'fold_not_requested'
#: A fold was asked for and the service refused or failed. The members stay in
#: the result: losing twenty-one filled cards because the roll-up failed would
#: cost more than the roll-up is worth.
FOLD_FAILED = 'fold_failed'
#: Nothing was filled, so there is nothing to aggregate. Not a fold failure:
#: the fold was never the thing that went wrong, and calling it one describes
#: an internal state where the situation is already on the screen -- the
#: per-member reasons are printed immediately above this line.
NOTHING_FILLED = 'nothing_filled'

#: Terminal states a member fill can end in, as this module distinguishes them.
#: `failed` is not `blocked`: one is an exception that escaped and the other is
#: a run that finished and refused to publish.
FILLED = 'filled'
FAILED = 'failed'
NOT_ATTEMPTED = 'not_attempted'

#: How a member's terminal state reaches the fold. The fold has its own
#: vocabulary for why a member has no card and this is the whole of the
#: translation: a mapping rather than a string built at the call site, because
#: `area_summary.member_status` renders an unrecognised reason as «unknown» and
#: a typo would therefore be silent.
_UNREACHED = {
    FAILED: 'member_run_failed',
    NOT_ATTEMPTED: 'member_not_attempted',
}

#: Why a member was never attempted. An unattempted member with no reason is
#: indistinguishable from one that was attempted and produced nothing.
NO_OBJECT_NAME = 'member_has_no_object_name'
AREA_DEADLINE_REACHED = 'area_deadline_reached'

#: How many members fill at once by default.
#
# Three, because each member fill makes roughly 75 specialist calls at up to
# `MAX_PARALLEL_SPECIALISTS` in flight against one vLLM instance. This bounds
# LOAD, and nothing here bounds the number of members: the two are different
# limits and only one of them is anybody's business. Seven licences means
# seven members, and how long to wait is the caller's decision.
DEFAULT_CONCURRENT_MEMBERS = 3


def _member_order(members: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The order members are filled in, named rather than inherited.

    It matters as soon as anything stops the run part-way: whichever members
    come last are the ones that do not get filled. Sorting by `rank` and then
    by `entity_id` makes that deterministic and re-runnable; dictionary order
    would make it an accident of how the manifest was built.

    Rank first because a parent that fails is more informative than a child
    that fails — if the area's root cannot be filled, the run has a different
    problem from a single member missing.
    """
    return sorted(
        members,
        key=lambda member: (int(member.get('rank') or 0), str(member.get('entity_id') or '')),
    )


async def run_geotizer_area_workflow(
    *,
    manifest: Mapping[str, Any],
    member_fill: MemberFill,
    member_arguments: Mapping[str, Any] | None = None,
    area_deadline_seconds: float | None = None,
    concurrent_members: int = DEFAULT_CONCURRENT_MEMBERS,
    clock: Callable[[], float] | None = None,
    fold_call: FoldCall | None = None,
    policy_version: str | None = None,
    dossier_run_id: str | None = None,
) -> dict[str, Any]:
    """Fill every member of a resolved area, and refuse to roll the answers up.

    `manifest` is an `AreaScopeManifest` as `geotizer_area_scope` returns it.
    `member_fill` is `run_geotizer_workflow`, unchanged: this module passes each
    member's `object_name` and `project_id` and nothing else about the area, so
    a member fill is indistinguishable from a single-object fill of that member.

    `area_deadline_seconds` bounds the *area*, not a member. A member keeps its
    own deadline, which the object path already has; without an area-level one,
    twenty-one members can spend twenty-one member deadlines. When it expires
    the remaining members are recorded as `not_attempted` with the reason,
    because a member absent from the result reads as a member that succeeded and
    returned nothing.

    `concurrent_members` bounds how many fill AT ONCE. It is not a member cap
    and must never become one: a cap refuses work, this schedules it. Members
    are independent -- separate runs, separate `run_id`s, no shared state --
    and the fold waits for all of them either way, so it is unchanged.
    """
    clock = clock or asyncio.get_event_loop().time
    started = clock()
    members = _member_order(list(manifest.get('members') or []))
    arguments = dict(member_arguments or {})
    # `object_name` and `project_id` are the member's, always. Left in, they
    # collide with the keywords below and raise «got multiple values for
    # keyword argument» — caught by the per-member handler and reported as
    # that member failing, which is a true sentence about a false cause.
    collisions = sorted(
        set(arguments)
        & {
            'object_name',
            'project_id',
            'started_run',
            # The member's own licence, which is what identifies it. Bound once
            # for the area it would be the same licence for every member --
            # the defect this loop was built to stop having.
            'licence_id',
            'licence_layer_id',
        }
    )
    if collisions:
        raise ValueError(
            f'member_arguments may not carry {", ".join(collisions)}: '
            'those identify the member, not the area'
        )

    # Members run CONCURRENTLY, bounded by `concurrent_members`.
    #
    # They are independent by construction: each is a separate run with its own
    # `run_id`, its own `started_run` mapping and its own deadline, and nothing
    # is shared between them. Sequentially, seven members is about eighteen
    # hours; three at a time is about six, and the operator has seven licences.
    #
    # What makes this safe is not this loop. `_round_usage`, `_kb_scope_note`,
    # `_kb_resolved` and `_usage_fn_note` in the orchestrator are `ContextVar`s
    # rather than module state, converted because two chat sessions seconds
    # apart in one process would otherwise each get some of the other's rounds
    # -- silently, both reporting plausible distributions and neither its own.
    # A task started with `asyncio.gather` copies the current context, so each
    # member reads and writes its own. `test_each_member_keeps_its_own_rounds`
    # is the check that this still holds.
    #
    # The bound is on how many run AT ONCE, never on how many run at all. Each
    # member fill makes roughly 75 specialist calls at up to
    # `MAX_PARALLEL_SPECIALISTS` in flight, so seven concurrent members is up
    # to twenty-one concurrent calls against one vLLM instance; that queues
    # rather than fails, and the queueing eats the gain.
    gate = asyncio.Semaphore(max(1, int(concurrent_members or 1)))

    async def fill_member(member: Mapping[str, Any]) -> dict[str, Any]:
        entity_id = str(member.get('entity_id') or '')
        licence_id = str(member.get('licence_id') or '').strip()
        licence_layer_id = str(member.get('licence_layer_id') or '').strip()
        # A licence number is a complete identity on the object path and a name
        # is not: `resolve_project` finds the project either way, and without a
        # licence the fill meets a project holding seven licence polygons with
        # nothing to select by and refuses `gis_project_multi_licence`. That is
        # what three members did, identically, on the first area run.
        #
        # So a member with a licence is filled BY that licence and carries no
        # name at all. The name it used to carry was not a name: a licence row
        # from `find_licence_across_projects` has no `object_name` key, so
        # `_member`'s fallback made it the licence number, and passing that as
        # a name told the fill to look up an object called `МАГ04805БЭ`. A
        # member's own name arrives from evidence during the fill, the way
        # `r002` does on the licence-first path, or it does not arrive.
        object_name = '' if licence_id else str(member.get('object_name') or '').strip()
        if not object_name and not licence_id:
            # A member the dossier knows by id and the fill can neither name
            # nor select. Not an error for the area: it is one member that
            # cannot be filled, and the area says which and why.
            return {
                'entity_id': entity_id,
                'state': NOT_ATTEMPTED,
                'reason': NO_OBJECT_NAME,
            }
        async with gate:
            # Judged on acquiring a slot rather than on being scheduled: with a
            # bound below the member count most members wait, and a deadline
            # read before the wait would abandon members the area still had
            # time for.
            if (
                area_deadline_seconds is not None
                and clock() - started >= float(area_deadline_seconds)
            ):
                return {
                    'entity_id': entity_id,
                    'object_name': object_name or licence_id or entity_id,
                    'state': NOT_ATTEMPTED,
                    'reason': AREA_DEADLINE_REACHED,
                }
            # One mapping per member, never one for the area. The fill writes
            # the run id in here the moment the run exists, which is long
            # before it succeeds or fails; a mapping shared across members
            # would hand a member that died before starting the previous
            # member's id, and a run id on the wrong member is worse than no
            # run id at all. Concurrency makes that sharper, not softer.
            started_run: dict[str, Any] = {}
            try:
                outcome = await member_fill(
                    object_name=object_name,
                    project_id=str(member.get('project_id') or '') or None,
                    licence_id=licence_id or None,
                    # The layer the area already resolved. The refusal that
                    # started this named `Sint_licences_2025exp_clp` as the
                    # project's licence layer, so the resolution had happened
                    # and was thrown away one hop before the fill that needed
                    # it.
                    licence_layer_id=licence_layer_id or None,
                    started_run=started_run,
                    **arguments,
                )
            except Exception as error:  # noqa: BLE001 - one member, not the area
                # One member's failure is not the area's. The object path
                # already hands back a `run_id` so a failed fill stays
                # resumable, and this is where the area collects the same
                # thing: by the time a fill can raise, the run usually exists,
                # holds whatever was filled before the failure, and is the only
                # handle anyone has on it. Losing it here would cost more than
                # the failure did -- which is what this loop did until the
                # `started_run` above was threaded through.
                failure: dict[str, Any] = {
                    'entity_id': entity_id,
                    'object_name': object_name or licence_id or entity_id,
                    'state': FAILED,
                    'error': f'{type(error).__name__}: {error}',
                }
                # Omitted, not blanked, when the fill died before a run
                # existed. An empty `run_id` reads as a run nobody can find; no
                # key says there is nothing to find, which is the true one.
                if started_run.get('run_id'):
                    failure['run_id'] = started_run['run_id']
                return failure
        return {
            'entity_id': entity_id,
            # What the member is called in the area's own answer. The licence
            # number when that is the identity, because a member line reading
            # «— заполнен» with no subject names nothing.
            'object_name': object_name or licence_id or entity_id,
            'state': FILLED,
            'run_id': outcome.get('run_id'),
            'status': outcome.get('status'),
            # The member's own completeness, unaltered. There is no area
            # completeness here and there must not appear to be one.
            'completeness': (outcome.get('audit') or {}).get('completeness'),
        }

    # `gather` keeps the order of its arguments, so `results` is still in
    # `_member_order` regardless of which member finished first. The fold, the
    # counts and the member list all read that order.
    results: list[dict[str, Any]] = list(
        await asyncio.gather(*(fill_member(member) for member in members))
    )

    document: dict[str, Any] = {
        'schema_version': 1,
        'area_id': manifest.get('area_id'),
        # Which policy and which CRS this run used, and whether each was named
        # by the caller or resolved here. Carried through rather than left on
        # the incoming manifest: this document IS what a later reader gets, and
        # a provenance record that reaches nobody is the silent default the
        # refusal existed to prevent, written down where it cannot be read.
        'contract_resolution': manifest.get('contract_resolution'),
        'members': results,
        'counts': {
            'members': len(members),
            FILLED: sum(1 for item in results if item['state'] == FILLED),
            FAILED: sum(1 for item in results if item['state'] == FAILED),
            NOT_ATTEMPTED: sum(1 for item in results if item['state'] == NOT_ATTEMPTED),
        },
    }
    # A state and a reason, never a missing key and never a zero.
    aggregation, folded = await _fold(
        fold_call=fold_call,
        policy_version=policy_version,
        dossier_run_id=dossier_run_id,
        manifest=manifest,
        results=results,
    )
    document['aggregation'] = aggregation
    if folded is not None:
        # Only when there is one. An empty summary key would be a document a
        # renderer walks and finds nothing in, which reads as an area with no
        # rows rather than an area nobody folded.
        if folded.get('summary') is not None:
            document['summary'] = folded['summary']
        # Rendered by the service that owns the renderer. Carried rather than
        # rebuilt here: `services/` may not import the GIS package, and a
        # second renderer would be a second answer to what the area says.
        if folded.get('summary_markdown') is not None:
            document['summary_markdown'] = folded['summary_markdown']
    return document


async def _fold(
    *,
    fold_call: FoldCall | None,
    policy_version: str | None,
    dossier_run_id: str | None,
    manifest: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """`(aggregation, folded)`, and `folded` is None unless a fold happened.

    Three things are needed and any of them absent means no fold: the call, the
    policy the caller expects, and the dossier run the result belongs to. Which
    ones were missing is named rather than counted -- «fold_not_requested» with
    no list is a reason a reader cannot act on.
    """
    if fold_call is None or not policy_version or not dossier_run_id:
        # Checked explicitly rather than by iterating a heterogeneous tuple:
        # the list comprehension that used to stand here could not narrow
        # `fold_call` for a type checker, so the `await` below read as a call
        # on `None`. Naming what is missing is still the point, and it is
        # derived from the same three checks rather than replacing them.
        missing = [
            name
            for name, value in (
                ('fold_call', fold_call),
                ('policy_version', policy_version),
                ('dossier_run_id', dossier_run_id),
            )
            if not value
        ]
        return {'state': NOT_PERFORMED, 'reason': FOLD_NOT_REQUESTED, 'missing': missing}, None

    # AFTER the wiring check, not before it. «Нечего сворачивать» about a run
    # that would not have folded a filled member either answers a question
    # nobody asked and hides the one fact worth knowing -- that no fold was
    # configured at all. Those are independent, and a reason that is true of
    # both cases is true of neither.
    if results and not any(item.get('state') == FILLED for item in results):
        # A fold of zero cards is not a fold that failed and not a fold that
        # was not requested: there was nothing to aggregate. The fold is not
        # called, because calling it would be asking the service to roll up
        # nothing and then reporting its answer as the area's.
        return (
            {
                'state': NOT_PERFORMED,
                'reason': NOTHING_FILLED,
                'members_total': len(results),
                'members_filled': 0,
            },
            None,
        )

    try:
        # Built inside the guard, not above it. `_fold_member` and `dict()` run
        # here, and a bug in either escaped `_fold` entirely -- discarding
        # every member already filled, which is the one thing this module's
        # docstring promises not to do: «losing twenty-one filled cards because
        # the roll-up failed would cost more than the roll-up is worth».
        payload = {
            'action': 'fold_area',
            'area_scope_id': str(manifest.get('area_id') or ''),
            'dossier_run_id': dossier_run_id,
            'policy_version': policy_version,
            'members': [_fold_member(item) for item in results],
            # The manifest gates every reducing operator on its memberships.
            # Sent always, because the one case the double-count guard does not
            # run is the case where nobody sends it.
            'scope': dict(manifest),
        }
        folded = await fold_call(payload)
    except Exception as error:  # noqa: BLE001 - the roll-up, not the members
        # The members stay in the document. Losing twenty-one filled cards
        # because the roll-up failed would cost more than the roll-up is worth,
        # and every one of them is still readable by its own run id.
        return (
            {
                'state': NOT_PERFORMED,
                'reason': FOLD_FAILED,
                'error': f'{type(error).__name__}: {error}',
            },
            None,
        )
    if not isinstance(folded, Mapping) or folded.get('aggregation') is None:
        # Returning without raising is not the same as having folded. A
        # `PERFORMED` state carrying `result: None` is indistinguishable from a
        # genuine empty fold, and this is the shape the module header forbids:
        # never a missing key, never a zero, always a state and a reason.
        return (
            {
                'state': NOT_PERFORMED,
                'reason': FOLD_FAILED,
                'error': 'the fold answered without an aggregation',
            },
            None,
        )
    return (
        {
            'state': PERFORMED,
            'policy_version': folded.get('policy_version'),
            'result': folded['aggregation'],
            # Enforced because the manifest above is always sent.
            'link_guard': 'enforced',
        },
        folded,
    )


def _fold_member(item: Mapping[str, Any]) -> dict[str, Any]:
    """One member as the fold request references it.

    A filled member is named by its run id and nothing else about it travels.
    An unfilled one carries the fold's own word for why, translated through
    `_UNREACHED` rather than spelled at this call site.
    """
    member: dict[str, Any] = {'entity_id': str(item.get('entity_id') or '')}
    if item.get('state') == FILLED and item.get('run_id'):
        member['run_id'] = item['run_id']
    else:
        member['unreached'] = _UNREACHED.get(str(item.get('state')), 'member_not_attempted')
    if item.get('object_name'):
        member['object_name'] = item['object_name']
    return member


def member_filler(
    *,
    fill: Callable[..., Awaitable[dict[str, Any]]],
    per_member: Mapping[str, Callable[[], Any]] | None = None,
    **injected: Any,
) -> MemberFill:
    """A `MemberFill` over the single-object workflow, with its context bound.

    Every member fill needs the same eight injected effects — the GIS call, the
    agent call, the RAG dispatcher, the vision call and the drains — and they
    are resolved once per area rather than once per member. Built here rather
    than at the adapter because the adapter's job is to resolve those effects,
    not to know which of them a member fill takes: that list is this layer's,
    and it has changed twice.

    `per_member` is for the effects that must NOT be shared: a factory per
    keyword, called once for each member. `query_drain` is the whole reason it
    exists. `QueryDrain` accumulates into an instance list, `drain()` returns
    everything recorded since the instance was built and never clears, and the
    run log reads the whole drain — so one instance across an area gave every
    member after the first the queries of the members before it. That was true
    while members ran one after another; running them at once also breaks the
    `[queries_before:]` slice the per-batch record uses, because another member
    is appending between the two reads.

    The round-usage collection needs no factory: the orchestrator holds it in a
    `ContextVar` that each fill opens for itself, and a task started by
    `gather` gets its own copy of the context.

    `object_name` and `project_id` come from the member and override anything
    bound here, so a member is filled as itself and not as the area.
    """

    async def call(*, object_name: str, project_id: str | None = None, **overrides: Any):
        arguments = dict(injected)
        # Before `overrides`: an explicit argument from the caller still wins,
        # and a fresh instance is built for this member either way.
        for name, build in (per_member or {}).items():
            arguments[name] = build()
        arguments.update(overrides)
        arguments['object_name'] = object_name
        arguments['project_id'] = project_id
        return await fill(**arguments)

    return call
