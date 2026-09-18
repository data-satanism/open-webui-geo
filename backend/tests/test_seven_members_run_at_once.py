"""Seven licences is seven members, and they do not wait for each other.

A three-member area completed sequentially with no errors, which is the
baseline this is measured against. Seven members one after another is about
eighteen hours; the operator has seven licences. Members are independent —
separate runs, separate `run_id`s, nothing shared — so they run at once, and
what is bounded is how many at a time, never how many at all.

That distinction is the point of this file. A member cap refuses work; a
concurrency bound schedules it. `AREA_MAX_MEMBERS` was the first kind and is
gone from all three repositories; `concurrent_members` is the second kind and
must not quietly become the first, which is why the first test fills more
members than the bound and counts them.

The other half is what concurrency breaks rather than what it speeds up. One
`QueryDrain` shared across an area put every earlier member's searches into
every later member's run log — already true while members ran one at a time,
and made worse by running them at once, because the per-batch record isolates
a batch by slicing `[queries_before:]` and another member appends between the
two reads.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

from open_webui.services.artifacts.geotizer.area_request import concurrent_members
from open_webui.services.artifacts.geotizer.area_workflow import (
    AREA_DEADLINE_REACHED,
    DEFAULT_CONCURRENT_MEMBERS,
    FILLED,
    NOT_ATTEMPTED,
    member_filler,
    run_geotizer_area_workflow,
)
from open_webui.services.artifacts.geotizer.run_scope import (
    current_gis_scope,
    scoped_arguments,
    set_gis_scope,
)

SEVEN = (
    'МАГ04805БЭ',
    'МАГ03394БЭ',
    'МАГ03395БЭ',
    'СЛХ025834ТП',
    'СЛХ025835ТП',
    'ТЮМ16123НЭ',
    'ТЮМ16124НЭ',
)


def manifest(licences, area_id='area:tengkeli'):
    return {
        'area_id': area_id,
        'members': [
            {'entity_id': f'e{index}', 'rank': index, 'licence_id': licence} for index, licence in enumerate(licences)
        ],
    }


def filled(licence_id=None, **_):
    return {'run_id': f'run-{licence_id}', 'status': 'ok', 'audit': {'completeness': 0.5}}


# -- The bound is on load, not on work ---------------------------------------


def test_the_bound_does_not_bound_the_work():
    seen = []

    async def fill(*, licence_id=None, **_):
        seen.append(licence_id)
        return filled(licence_id)

    answer = asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=3))
    assert len(seen) == 7, seen
    assert answer['counts']['members'] == 7
    assert answer['counts'][FILLED] == 7


def test_members_are_in_flight_together():
    """Decisive: one at a time and the third member never arrives.

    Each member waits until three have started. Sequentially the first would
    wait for a second that cannot start until the first returns, and the
    timeout below is what that deadlock looks like.
    """
    state = {'arrived': 0}

    async def run():
        three_here = asyncio.Event()

        async def fill(*, licence_id=None, **_):
            state['arrived'] += 1
            if state['arrived'] >= 3:
                three_here.set()
            await asyncio.wait_for(three_here.wait(), timeout=5)
            return filled(licence_id)

        return await run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=3)

    answer = asyncio.run(run())
    assert answer['counts'][FILLED] == 7


def test_no_more_than_the_bound_run_at_once():
    peak = {'now': 0, 'max': 0}

    async def fill(*, licence_id=None, **_):
        peak['now'] += 1
        peak['max'] = max(peak['max'], peak['now'])
        await asyncio.sleep(0.01)
        peak['now'] -= 1
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=2))
    assert peak['max'] == 2, f'peak in flight was {peak["max"]}'


def test_one_at_a_time_is_still_available():
    peak = {'now': 0, 'max': 0}

    async def fill(*, licence_id=None, **_):
        peak['now'] += 1
        peak['max'] = max(peak['max'], peak['now'])
        await asyncio.sleep(0)
        peak['now'] -= 1
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN[:3]), member_fill=fill, concurrent_members=1))
    assert peak['max'] == 1


def test_the_answer_is_in_member_order_not_completion_order():
    """The fold reads this order; finishing first must not reorder it."""

    async def fill(*, licence_id=None, **_):
        await asyncio.sleep(0.005 * (len(SEVEN) - SEVEN.index(licence_id)))
        return filled(licence_id)

    answer = asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    assert [item['object_name'] for item in answer['members']] == list(SEVEN)


# -- Each member keeps its own ------------------------------------------------


def test_each_member_gets_its_own_query_drain():
    """One drain across an area puts member one's searches in member seven's log."""
    built = []

    class Drain:
        def __init__(self):
            built.append(self)

    seen = []

    async def fill(*, query_drain=None, **_):
        seen.append(query_drain)
        return filled()

    async def run():
        call = member_filler(fill=fill, per_member={'query_drain': Drain})
        for licence in SEVEN[:3]:
            await call(object_name='', licence_id=licence)

    asyncio.run(run())
    assert len(built) == 3
    assert len({id(item) for item in seen}) == 3, 'members shared a drain'


def test_an_explicit_argument_still_wins_over_the_factory():
    supplied = object()
    seen = []

    async def fill(*, query_drain=None, **_):
        seen.append(query_drain)
        return filled()

    async def run():
        call = member_filler(fill=fill, per_member={'query_drain': object})
        await call(object_name='x', query_drain=supplied)

    asyncio.run(run())
    assert seen == [supplied]


def test_each_member_keeps_its_own_rounds():
    """The property the orchestrator's ContextVars rest on.

    `open_round_usage` does `_round_usage.set([])` inside the fill. A task
    started by `gather` copies the context at creation, so each member writes
    into its own list. This asserts that directly: the module-level list the
    tool replaced would fail it.
    """
    rounds: ContextVar[list | None] = ContextVar('rounds', default=None)
    drained: dict[str, list[str]] = {}

    async def fill(*, licence_id=None, **_):
        rounds.set([])  # what open_round_usage does
        for index in range(3):
            rounds.get().append(f'{licence_id}:{index}')
            await asyncio.sleep(0)  # let the others interleave
        drained[licence_id] = list(rounds.get())
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    assert set(drained) == set(SEVEN)
    for licence, own in drained.items():
        assert own == [f'{licence}:{index}' for index in range(3)], (licence, own)


# -- The deadline still bounds ------------------------------------------------


def test_a_member_that_waited_past_the_deadline_is_not_attempted():
    """Judged on acquiring a slot, not on being scheduled.

    With a bound below the member count most members wait; reading the
    deadline before the wait would abandon members the area still had time
    for.
    """
    now = [0.0]

    async def fill(*, licence_id=None, **_):
        now[0] += 10.0
        return filled(licence_id)

    answer = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(SEVEN),
            member_fill=fill,
            concurrent_members=1,
            area_deadline_seconds=25.0,
            clock=lambda: now[0],
        )
    )
    states = [item['state'] for item in answer['members']]
    assert states[0] == FILLED
    assert NOT_ATTEMPTED in states
    reasons = {item.get('reason') for item in answer['members'] if item['state'] == NOT_ATTEMPTED}
    assert reasons == {AREA_DEADLINE_REACHED}


# -- The valve ----------------------------------------------------------------


def test_an_unset_valve_is_the_default():
    assert concurrent_members(None) == (DEFAULT_CONCURRENT_MEMBERS, None)
    assert concurrent_members('') == (DEFAULT_CONCURRENT_MEMBERS, None)


def test_a_number_is_honoured():
    assert concurrent_members('7') == (7, None)
    assert concurrent_members(' 2 ') == (2, None)


def test_a_mistyped_valve_is_not_silently_the_default():
    value, note = concurrent_members('seven')
    assert value == DEFAULT_CONCURRENT_MEMBERS
    assert note and 'seven' in note


def test_zero_and_negative_are_refused_with_a_note():
    for raw in ('0', '-1'):
        value, note = concurrent_members(raw)
        assert value == DEFAULT_CONCURRENT_MEMBERS
        assert note and raw in note


def test_the_default_is_three():
    """Named here so a change to it has to change a test that says why."""
    assert DEFAULT_CONCURRENT_MEMBERS == 3


# -- The GIS scope the fork records -------------------------------------------


def test_nothing_is_forwarded_to_a_build_that_takes_no_scope():
    """Which is every orchestrator shipped so far."""
    set_gis_scope(project_id='tengkeli', run_id='r-1')
    assert scoped_arguments({'agent': 1, 'prompt': 1, 'mode': 1}) == {}


def test_what_a_build_accepts_is_forwarded():
    set_gis_scope(project_id='tengkeli', run_id='r-1')
    assert scoped_arguments({'agent': 1, 'gis_project_id': 1, 'geomas_run_id': 1}) == {
        'gis_project_id': 'tengkeli',
        'geomas_run_id': 'r-1',
    }


def test_an_unresolved_project_records_nothing_rather_than_a_guess():
    assert set_gis_scope(project_id='', run_id='r-2') == {'run_id': 'r-2'}
    assert 'project_id' not in current_gis_scope()


def test_concurrent_members_do_not_share_a_scope():
    """The reason it is a ContextVar and not a module value."""
    seen: dict[str, dict[str, str]] = {}

    async def fill(*, licence_id=None, **_):
        set_gis_scope(project_id=f'project-{licence_id}', run_id=f'run-{licence_id}')
        await asyncio.sleep(0)
        seen[licence_id] = current_gis_scope()
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    for licence, scope in seen.items():
        assert scope == {
            'project_id': f'project-{licence}',
            'run_id': f'run-{licence}',
        }, (licence, scope)
