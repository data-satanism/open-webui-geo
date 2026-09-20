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

#: What the area reports about itself while it runs: one mapping of counts,
#: rewritten rather than appended to. A member's per-specialist lines carry
#: no member identity and seven members produce seven streams; how many
#: members are done is what a reader watching an area wants, and it is a
#: state rather than a stream.
ProgressCall = Callable[[Mapping[str, int]], Awaitable[None]]


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

#: The three a member can settle into, named as a set rather than inferred
#: from the counter's own keys. `state in counts` was the test, and `counts`
#: also holds `members` and `running` -- so a member reporting `state:
#: 'running'` would have incremented the in-flight counter and left it there
#: for the rest of the run. Unreachable from the four exits below and exactly
#: the kind of near-miss that survives a refactor.
_SETTLED = (FILLED, FAILED, NOT_ATTEMPTED)

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


def _crashed(member: Mapping[str, Any], error: BaseException) -> dict[str, Any]:
    """A member whose task raised outside the fill's own handler.

    The same shape as the handler's own failure entry, so a reader cannot tell
    which of the two produced it -- what matters is that the member failed and
    the other members still have their answers.
    """
    entity_id = str(member.get('entity_id') or '')
    return {
        'entity_id': entity_id,
        'object_name': str(member.get('licence_id') or member.get('object_name') or entity_id),
        'state': FAILED,
        'error': f'{type(error).__name__}: {error}',
    }


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
    # What the area's id is a digest of, beyond its members. Passed in rather
    # than dug out of `manifest`: the caller resolved both, the manifest
    # carries only one of them, and two places deciding what an area is
    # called is two directories its artefacts could land in.
    project_id: str | None = None,
    calculation_crs: str | None = None,
    area_display_name: str | None = None,
    # Called on every member transition with the counts below. The words are
    # not chosen here: this module knows how many members are in each state
    # and nothing else does, and choosing what a user reads is rendering.
    # `None` is «nobody is watching», which is most callers.
    on_progress: ProgressCall | None = None,
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
    # The names a member fill builds for itself, asked of the filler rather
    # than listed here. Without this the guard screened the five identity
    # fields and not the per-member effects -- so `member_arguments` carrying
    # `query_drain` would override the fresh instance with one object for the
    # whole area, which is the defect the per-member factory exists to stop,
    # reached through the parameter the guard appears to be guarding.
    per_member_names = set(getattr(member_fill, 'per_member_keys', ()) or ())
    collisions = sorted(
        set(arguments)
        & (
            per_member_names
            | {
                'object_name',
                'project_id',
                'started_run',
                # The member's own licence, which is what identifies it. Bound once
                # for the area it would be the same licence for every member --
                # the defect this loop was built to stop having.
                'licence_id',
                'licence_layer_id',
                # Set by this loop below, and by nothing else: it is what
                # tells the orchestrator a fill is one member of an area.
                # Unlisted, a caller who passed it got «got multiple values
                # for keyword argument» inside every member's own handler --
                # seven failed members where one area-level refusal names
                # the cause.
                'area_member',
            }
        )
    )
    if collisions:
        raise ValueError(
            f'member_arguments may not carry {", ".join(collisions)}: the member loop binds those itself'
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
    try:
        bound = max(1, int(concurrent_members))
    except (TypeError, ValueError):
        # Every valve in this system degrades with a note rather than raising,
        # and this is the core rather than the adapter: a second caller that
        # never went through `concurrent_members()` would otherwise get a bare
        # ValueError from inside an area fill.
        bound = DEFAULT_CONCURRENT_MEMBERS
    gate = asyncio.Semaphore(bound)

    # How many members are in each state, as a plain dict mutated in place.
    # Safe without a lock and not by luck: every write below happens between
    # two `await`s in one event loop, so no member can observe a half-applied
    # transition. A lock here would be a claim about threads that do not
    # exist.
    counts = {
        'members': len(members),
        'running': 0,
        'filled': 0,
        'failed': 0,
        'not_attempted': 0,
    }

    # One line delivered at a time, and the snapshot read under the same hold.
    # Without it two members settling while an emitter is awaiting each carry
    # their own snapshot into the socket and arrive in whichever order the
    # socket finishes them: a reader watching a seven-member area sees «готово
    # 6» replaced by «готово 5». The line is a state, and a state that moves
    # backwards is worse than one that arrives late.
    delivery = asyncio.Lock()

    # What the line could not say, and how often. A status line must not cost
    # the area, so the emitter's exception is swallowed -- but a rendering bug
    # in `area_progress_line` raises here exactly as a dead socket does, on
    # every call, for the rest of the run, and a bare `pass` makes those two
    # the same event: the line simply stops advancing and nothing anywhere
    # says why. This contour's server log cannot be exported, so a log line is
    # not the place to tell them apart; `round_usage_drain` in `workflow.py`
    # records its own swallowed failure in the run log for the same reason.
    #
    # `attempts` is what separates them: one failure in fifteen is a blip on
    # the wire, fifteen in fifteen is a defect in the sentence.
    progress: dict[str, Any] = {'attempts': 0, 'failures': 0}
    unaccounted: list[str] = []

    async def report() -> None:
        """The area's own line, after a transition rather than on a timer."""
        if on_progress is None:
            return
        async with delivery:
            progress['attempts'] += 1
            try:
                await on_progress(dict(counts))
            except Exception as error:  # noqa: BLE001 - a status line, not the area
                # A member that filled and an emitter that failed are not the
                # same event, and the second must not become the first. What
                # is recorded is the FIRST failure: the tenth is almost
                # always the first repeated, and the one that names the cause
                # is the one that happened before anything else changed.
                progress['failures'] += 1
                progress.setdefault('error', f'{type(error).__name__}: {error}')

    def settle(outcome: Mapping[str, Any]) -> None:
        """Move one member out of `running` into whatever it became.

        Keyed on the state the member actually reports rather than on which
        branch produced it: a member can leave `fill_member` as
        `not_attempted` from three different places, and a counter that
        tracked branches instead of states would drift from the document the
        same loop builds.
        """
        state = str(outcome.get('state') or '')
        if state in _SETTLED:
            counts[state] += 1
            return
        # A terminal state this counter does not know. Dropped silently, the
        # member stays in «ожидают» for the rest of the run and the line quietly
        # stops summing to the member count -- a gap wearing a guard's clothes.
        # The member's own entry in `members` still carries whatever it reported,
        # so the document is unharmed; what is recorded here is that the LINE is
        # short, and by which state.
        unaccounted.append(state)

    async def _fill_member(member: Mapping[str, Any]) -> dict[str, Any]:
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
            if area_deadline_seconds is not None and clock() - started >= float(area_deadline_seconds):
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
            # Running from here, not from being scheduled: with a bound
            # below the member count most members are waiting, and counting a
            # waiting member as running would make the line say three are
            # filling when three are queued.
            try:
                # Inside the `try`, not above it. The increment is one
                # statement and cannot fail, but `await report()` suspends,
                # and a `CancelledError` delivered while it is suspended
                # leaves the loop without ever reaching the `finally` --
                # leaking an in-flight member into a counter whose whole
                # comment claims the opposite. Latent today, because that
                # cancellation also takes the area down before anything reads
                # the counter; a defect the next refactor inherits.
                counts['running'] += 1
                await report()
                started_run: dict[str, Any] = {}
                try:
                    outcome = await member_fill(
                        object_name=object_name,
                        project_id=str(member.get('project_id') or '') or None,
                        licence_id=licence_id or None,
                        # The layer the area already resolved. The refusal
                        # that started this named
                        # `Sint_licences_2025exp_clp` as the project's
                        # licence layer, so the resolution had happened and
                        # was thrown away one hop before the fill that
                        # needed it.
                        licence_layer_id=licence_layer_id or None,
                        started_run=started_run,
                        # What the orchestrator cannot work out for itself:
                        # it sees one `run_agent_task` call and a member of
                        # an area looks exactly like a single fill. Set, it
                        # suppresses the per-specialist lines that carry no
                        # member identity and keeps the milestones that do.
                        area_member=True,
                        **arguments,
                    )
                except Exception as error:  # noqa: BLE001 - one member, not the area
                    # One member's failure is not the area's. The object
                    # path already hands back a `run_id` so a failed fill
                    # stays resumable, and this is where the area collects
                    # the same thing: by the time a fill can raise, the run
                    # usually exists, holds whatever was filled before the
                    # failure, and is the only handle anyone has on it.
                    # Losing it here would cost more than the failure did --
                    # which is what this loop did until the `started_run`
                    # above was threaded through.
                    failure: dict[str, Any] = {
                        'entity_id': entity_id,
                        'object_name': object_name or licence_id or entity_id,
                        'state': FAILED,
                        'error': f'{type(error).__name__}: {error}',
                    }
                    # Omitted, not blanked, when the fill died before a run
                    # existed. An empty `run_id` reads as a run nobody can
                    # find; no key says there is nothing to find, which is
                    # the true one.
                    if started_run.get('run_id'):
                        failure['run_id'] = started_run['run_id']
                    return failure
            finally:
                # Whichever way the gated section ends. Five exits and a
                # decrement at each of them is five places to forget one.
                counts['running'] -= 1
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

    def _with_licence(
        member: Mapping[str, Any], outcome: dict[str, Any]
    ) -> dict[str, Any]:
        """The member's licence, stamped onto whatever outcome it produced.

        Here rather than at each of `_fill_member`'s five exits, and taken
        from the REQUEST rather than from the outcome: the licence is what
        the caller sent, so an outcome cannot disagree with it, and one
        place cannot be four-fifths done.

        It travels because every area artefact keys on it and none of them
        had it. `_fold_member` sent `entity_id`, `run_id` and `object_name`
        and nothing else -- «a filled member is named by its run id and
        nothing else about it travels» -- so the fold received
        `licence_id: null` for all seven members, and it read back as `—` in
        the summary's licence column, as `null` in the state's members and
        in the content key's inputs, and as a missing licence in the source
        report. The value existed the whole time: `entity_id` was set to it.
        """
        licence = str(member.get('licence_id') or '').strip()
        if licence and not str(outcome.get('licence_id') or '').strip():
            return {**outcome, 'licence_id': licence}
        return outcome

    async def fill_member(member: Mapping[str, Any]) -> dict[str, Any]:
        """`_fill_member`, with every exit counted.

        It has five of them — two `not_attempted`, one `failed`, one
        `filled`, and raising — and a counter updated at each is five places
        to forget one. Counted here instead, from the state the member
        reports, so the line and the document the same loop builds cannot
        disagree about how many members are done.
        """
        try:
            outcome = _with_licence(member, await _fill_member(member))
        except Exception:  # noqa: BLE001 - counted, then re-raised unchanged
            # `gather` collects this and the loop below turns it into a
            # `failed` member, so the counter has to agree. Left uncounted,
            # the line's numbers would stop summing to the member count for
            # the rest of the run — and a reader watching «готово 6» on a
            # seven-member area would wait for a seventh that already ended.
            counts['failed'] += 1
            await report()
            raise
        settle(outcome)
        await report()
        return outcome

    # Before anything is scheduled, so a reader sees the area's size at once
    # rather than after the first member finishes. Seven members at three at
    # a time is about six hours; a first line six hours in is no line.
    await report()

    # `gather` keeps the order of its arguments, so `results` is still in
    # `_member_order` regardless of which member finished first. The fold, the
    # counts and the member list all read that order.
    #
    # `return_exceptions=True` because without it the FIRST exception out of
    # any member re-raises here and CANCELS every sibling still in flight --
    # members with real run ids and finished batches, lost from the answer
    # though the runs exist. `fill_member` catches around the fill itself, but
    # not around reading the member's identity or the outcome it returns, so
    # an outcome that is not a mapping would take the whole area down. This
    # module says «one member's failure is not the area's» in four places; the
    # loop that schedules them has to mean it too.
    settled = await asyncio.gather(*(fill_member(member) for member in members), return_exceptions=True)
    results: list[dict[str, Any]] = []
    for member, outcome in zip(members, settled):
        if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
            # Cancellation of the area is the area's, and is not a member
            # result. Re-raised rather than recorded as a failed member.
            raise outcome
        results.append(outcome if isinstance(outcome, dict) else _crashed(member, outcome))

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
        project_id=project_id,
        calculation_crs=calculation_crs,
        area_display_name=area_display_name,
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
        # Where the area's own files are, or why there are none. Carried
        # always when the fold answered, because an absent key and a
        # `written: false` record read alike to whoever is looking for a
        # download link, and only one of them names the field to send.
        if folded.get('artifacts') is not None:
            document['artifacts'] = folded['artifacts']
        if folded.get('area_run_id') is not None:
            document['area_run_id'] = folded['area_run_id']
    # Only when something went wrong with it. A key present on every area
    # would be «the line worked» written 15 times and read never; absent
    # means every attempt reached its emitter, which is the fact worth being
    # able to check. Written after the fold so a fold failure cannot discard
    # it, and before the return so it cannot be dropped the way the
    # concurrency note once was.
    if progress['failures'] or unaccounted:
        document['progress_line'] = {
            key: value
            for key, value in (
                ('attempts', progress['attempts']),
                ('failures', progress['failures']),
                ('error', progress.get('error')),
                # Which member states the counter did not know, in the order
                # they arrived. Deduplicated would hide that it happened
                # seven times.
                ('unaccounted_states', list(unaccounted) or None),
            )
            if value is not None
        }
    return document


async def _fold(
    *,
    fold_call: FoldCall | None,
    policy_version: str | None,
    dossier_run_id: str | None,
    manifest: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    project_id: str | None = None,
    calculation_crs: str | None = None,
    area_display_name: str | None = None,
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
            # The three the area's id is a digest of, beyond the members.
            # Without them the service folds and stores nothing, and says
            # which field it lacked -- the answer would carry a summary and
            # no link, which is the state this run was reported in.
            'project_id': project_id,
            'calculation_crs': calculation_crs,
            # The name, kept a name. It goes in the artefacts so a downloaded
            # workbook says which area it is; it never becomes a path
            # segment, which is what made the first area's links dead.
            'area_display_name': area_display_name,
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
    # And the licence. «Nothing else about it travels» was true and wrong:
    # the fold's own member record, the summary's licence column, the
    # content key's inputs and the source report all key on this, and all
    # four printed `null` for all seven members of `area_6c2d1043…` while
    # `entity_id` held the number the whole time.
    if item.get('licence_id'):
        member['licence_id'] = item['licence_id']
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

    # Read by `run_geotizer_area_workflow`'s collision guard. An attribute
    # rather than a second argument to the workflow: the filler is the only
    # thing that knows which effects it builds per member, and two places
    # holding that list is how one of them goes stale.
    call.per_member_keys = frozenset(per_member or ())
    return call
