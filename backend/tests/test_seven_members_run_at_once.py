"""Area members fill concurrently up to a bound that limits how many run at once, never
how many run."""

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
    _GIS_SCOPE,
    SCOPE_METADATA_KEY,
    current_gis_scope,
    gis_scope_recorded,
    scoped_metadata,
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
    """Three members are in flight at once under a bound of three."""
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
    """The area result lists members in member order, not completion order."""

    async def fill(*, licence_id=None, **_):
        await asyncio.sleep(0.005 * (len(SEVEN) - SEVEN.index(licence_id)))
        return filled(licence_id)

    answer = asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    assert [item['object_name'] for item in answer['members']] == list(SEVEN)


def test_each_member_gets_its_own_query_drain():
    """`member_filler` builds a fresh `query_drain` for each member."""
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
    """A `ContextVar` set inside each member fill stays private to that member under
    `gather`."""
    rounds: ContextVar[list | None] = ContextVar('rounds', default=None)
    drained: dict[str, list[str]] = {}

    async def fill(*, licence_id=None, **_):
        rounds.set([])
        for index in range(3):
            rounds.get().append(f'{licence_id}:{index}')
            await asyncio.sleep(0)
        drained[licence_id] = list(rounds.get())
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    assert set(drained) == set(SEVEN)
    for licence, own in drained.items():
        assert own == [f'{licence}:{index}' for index in range(3)], (licence, own)


def test_a_member_that_waited_past_the_deadline_is_not_attempted():
    """The area deadline is judged when a member acquires a slot, and members past it
    are not attempted."""
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
    """`DEFAULT_CONCURRENT_MEMBERS` is 3."""
    assert DEFAULT_CONCURRENT_MEMBERS == 3


def test_the_scope_rides_the_channel_every_build_already_takes():
    """`scoped_metadata` adds the recorded GIS scope to `__metadata__` under
    `SCOPE_METADATA_KEY`."""
    set_gis_scope(project_id='tengkeli', run_id='r-1')

    assert scoped_metadata({'chat_id': 'c-1'}) == {
        'chat_id': 'c-1',
        SCOPE_METADATA_KEY: {'project_id': 'tengkeli', 'run_id': 'r-1'},
    }


def test_the_caller_s_metadata_is_copied_and_not_written_into():
    """`scoped_metadata` returns a copy and leaves the caller's mapping unchanged."""
    set_gis_scope(project_id='tengkeli', run_id='r-1')
    original = {'chat_id': 'c-1'}

    produced = scoped_metadata(original)

    assert original == {'chat_id': 'c-1'}
    assert produced is not original


def test_no_fill_records_no_key_at_all():
    """With no scope set, nothing is recorded and `scoped_metadata` adds no key."""
    _GIS_SCOPE.set(None)

    assert not gis_scope_recorded()
    assert scoped_metadata({'chat_id': 'c-1'}) == {'chat_id': 'c-1'}


def test_a_fill_that_resolved_nothing_still_says_so():
    set_gis_scope(project_id='', run_id='')

    assert gis_scope_recorded()
    assert scoped_metadata({})[SCOPE_METADATA_KEY] == {}


def test_metadata_that_is_not_a_mapping_still_carries_the_scope():
    """Metadata that is not a mapping is replaced by a mapping carrying the scope."""
    set_gis_scope(project_id='tengkeli', run_id='r-1')

    assert scoped_metadata(None) == {
        SCOPE_METADATA_KEY: {'project_id': 'tengkeli', 'run_id': 'r-1'},
    }


def test_an_unresolved_project_records_nothing_rather_than_a_guess():
    assert set_gis_scope(project_id='', run_id='r-2') == {'run_id': 'r-2'}
    assert 'project_id' not in current_gis_scope()


def test_concurrent_members_do_not_share_a_scope():
    """Concurrent members each see their own GIS scope."""
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


def test_a_refused_concurrency_valve_reaches_the_markdown():
    """`render_area_answer` renders the `area_concurrency_note`."""
    from open_webui.services.artifacts.geotizer.area_request import render_area_answer

    payload = {
        'status': 'resolved',
        'resolved_from': 'licence_ids',
        'area_concurrency_note': 'GEOMAS_AREA_CONCURRENT_MEMBERS=seven — не целое число.',
        'result': {
            'area_id': 'area:tengkeli',
            'members': [],
            'counts': {'members': 0, 'filled': 0, 'failed': 0, 'not_attempted': 0},
            'aggregation': {'state': 'not_performed', 'reason': 'fold_not_requested'},
        },
    }
    rendered = render_area_answer(payload)
    assert 'GEOMAS_AREA_CONCURRENT_MEMBERS=seven' in rendered


def test_an_area_argument_may_not_override_a_per_member_effect():
    """`member_arguments` naming a per-member effect of the filler is refused with a
    `ValueError`."""

    async def fill(**_):
        return filled()

    call = member_filler(fill=fill, per_member={'query_drain': object})
    assert call.per_member_keys == frozenset({'query_drain'})

    async def run():
        return await run_geotizer_area_workflow(
            manifest=manifest(SEVEN[:2]),
            member_fill=call,
            member_arguments={'query_drain': 'one for the whole area'},
        )

    try:
        asyncio.run(run())
    except ValueError as error:
        assert 'query_drain' in str(error), error
    else:
        raise AssertionError('the area accepted a shared per-member effect')


def test_a_filler_with_no_per_member_effects_still_declares_the_empty_set():
    """`member_filler` without `per_member` declares an empty `per_member_keys`."""

    async def fill(**_):
        return filled()

    assert member_filler(fill=fill).per_member_keys == frozenset()


def test_a_member_whose_task_raises_does_not_cancel_the_others():
    """A member whose task raises outside the fill's handler fails alone and the other
    members fill."""

    async def fill(*, licence_id=None, **_):
        if licence_id == SEVEN[2]:
            return 'not a mapping'
        return filled(licence_id)

    answer = asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    states = {item['object_name']: item['state'] for item in answer['members']}
    assert states[SEVEN[2]] == 'failed', states
    assert answer['counts'][FILLED] == 6, answer['counts']
    assert all(item.get('run_id') for item in answer['members'] if item['state'] == FILLED)


def test_a_crashed_member_still_names_itself():
    async def fill(*, licence_id=None, **_):
        return None if licence_id == SEVEN[0] else filled(licence_id)

    answer = asyncio.run(
        run_geotizer_area_workflow(manifest=manifest(SEVEN[:2]), member_fill=fill, concurrent_members=2)
    )
    crashed = answer['members'][0]
    assert crashed['object_name'] == SEVEN[0]
    assert crashed['state'] == 'failed'
    assert 'AttributeError' in crashed['error']


def test_a_bound_that_is_not_a_number_degrades_rather_than_raising():
    """A non-numeric `concurrent_members` falls back to the default rather than raising."""

    async def fill(*, licence_id=None, **_):
        return filled(licence_id)

    answer = asyncio.run(
        run_geotizer_area_workflow(manifest=manifest(SEVEN[:3]), member_fill=fill, concurrent_members='three')
    )
    assert answer['counts'][FILLED] == 3


def test_the_real_round_usage_wrapper_keeps_each_members_rounds_apart():
    """The drain `round_usage_scope` builds keeps each concurrent member's rounds apart."""
    from open_webui.services.artifacts.geotizer.workflow import round_usage_scope

    class Orchestrator:
        """A build shaped like the installed one: a ContextVar per fill."""

        def __init__(self):
            self.rounds: ContextVar[list | None] = ContextVar('rounds', default=None)

        def open_round_usage(self):
            self.rounds.set([])

        def record(self, item):
            held = self.rounds.get()
            if held is not None:
                held.append(item)

        def drain_round_usage(self):
            return list(self.rounds.get() or [])

    orchestrator = Orchestrator()
    drain = round_usage_scope(orchestrator)
    assert drain is not None, 'a build with both halves must yield a drain'
    taken: dict[str, list[str]] = {}

    async def fill(*, licence_id=None, **_):
        drain.open()
        for index in range(3):
            orchestrator.record(f'{licence_id}:{index}')
            await asyncio.sleep(0)
        taken[licence_id] = drain.drain()
        return filled(licence_id)

    asyncio.run(run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=7))
    for licence, own in taken.items():
        assert own == [f'{licence}:{index}' for index in range(3)], (licence, own)


def test_a_build_that_drains_without_opening_is_refused():
    """`round_usage_scope` returns None for a build with `drain_round_usage` and no
    `open_round_usage`."""
    from open_webui.services.artifacts.geotizer.workflow import round_usage_scope

    class HalfBuild:
        def drain_round_usage(self):
            return []

    assert round_usage_scope(HalfBuild()) is None


def test_the_scope_default_is_not_one_mutable_object_everyone_shares():
    """`_GIS_SCOPE` defaults to None and `current_gis_scope` returns a copy."""
    import contextvars

    from open_webui.services.artifacts.geotizer import run_scope as module

    assert contextvars.Context().run(module._GIS_SCOPE.get) is None

    set_gis_scope(project_id='tengkeli', run_id='r-9')
    handed_out = current_gis_scope()
    handed_out['project_id'] = 'scribbled on'
    assert current_gis_scope()['project_id'] == 'tengkeli'


def test_the_deadline_is_read_when_a_queued_member_gets_its_slot():
    """Members queued behind the bound when the clock passes the deadline are recorded
    as not attempted."""
    now = [0.0]

    async def run():
        released = asyncio.Event()
        first_two = []

        async def fill(*, licence_id=None, **_):
            first_two.append(licence_id)
            if len(first_two) <= 2:
                await asyncio.wait_for(released.wait(), timeout=5)
            now[0] += 20.0
            return filled(licence_id)

        async def tick():
            while len(first_two) < 2:
                await asyncio.sleep(0)
            now[0] = 99.0
            released.set()

        area = run_geotizer_area_workflow(
            manifest=manifest(SEVEN[:5]),
            member_fill=fill,
            concurrent_members=2,
            area_deadline_seconds=50.0,
            clock=lambda: now[0],
        )
        answer, _ = await asyncio.gather(area, tick())
        return answer

    answer = asyncio.run(run())
    states = [item['state'] for item in answer['members']]
    assert states[:2] == [FILLED, FILLED], states
    assert states[2:] == [NOT_ATTEMPTED] * 3, states
    assert {item['reason'] for item in answer['members'][2:]} == {AREA_DEADLINE_REACHED}
    assert answer['counts'] == {
        'members': 5,
        FILLED: 2,
        'failed': 0,
        NOT_ATTEMPTED: 3,
    }


def test_a_member_raising_while_others_are_in_flight_costs_only_itself():
    """A member that raises while three members overlap fails alone."""

    async def run():
        three_here = asyncio.Event()
        arrived = []

        async def fill(*, licence_id=None, **_):
            arrived.append(licence_id)
            if len(arrived) >= 3:
                three_here.set()
            await asyncio.wait_for(three_here.wait(), timeout=5)
            if licence_id == SEVEN[1]:
                raise RuntimeError('this member and no other')
            return filled(licence_id)

        return await run_geotizer_area_workflow(manifest=manifest(SEVEN), member_fill=fill, concurrent_members=3)

    answer = asyncio.run(run())
    by_name = {item['object_name']: item for item in answer['members']}
    assert by_name[SEVEN[1]]['state'] == 'failed'
    assert 'RuntimeError' in by_name[SEVEN[1]]['error']
    assert answer['counts'][FILLED] == 6, answer['counts']


def test_an_area_of_one_and_an_area_of_none_take_the_valve_too():
    async def fill(*, licence_id=None, **_):
        return filled(licence_id)

    for licences in ((), SEVEN[:1]):
        for bound in (1, 3, 7):
            answer = asyncio.run(
                run_geotizer_area_workflow(manifest=manifest(licences), member_fill=fill, concurrent_members=bound)
            )
            assert answer['counts']['members'] == len(licences), (licences, bound)
            assert answer['counts'][FILLED] == len(licences)


def test_the_identity_fields_are_all_refused_as_area_arguments():
    """Every member identity field and `area_member` is refused in `member_arguments`."""

    async def fill(**_):
        return filled()

    for name in (
        'object_name', 'project_id', 'started_run', 'licence_id',
        'licence_layer_id', 'area_member',
    ):
        try:
            asyncio.run(
                run_geotizer_area_workflow(
                    manifest=manifest(SEVEN[:1]),
                    member_fill=fill,
                    member_arguments={name: 'the area cannot say this'},
                )
            )
        except ValueError as error:
            assert name in str(error), (name, error)
        else:
            raise AssertionError(f'{name} was accepted as an area-wide argument')


def test_a_member_fill_says_so_on_the_scope():
    set_gis_scope(project_id='tengkeli', run_id='r-1', area_member=True)

    assert current_gis_scope()['area_member'] is True
    assert scoped_metadata({})[SCOPE_METADATA_KEY]['area_member'] is True


def test_a_single_object_fill_says_nothing_rather_than_false():
    """A single-object fill records no `area_member` key."""
    scope = set_gis_scope(project_id='tengkeli', run_id='r-1')

    assert 'area_member' not in scope
    assert 'area_member' not in scoped_metadata({})[SCOPE_METADATA_KEY]


def test_it_is_a_bool_and_not_the_string_that_looks_like_one():
    """`area_member` is recorded as the bool `True`, while `project_id` is a string."""
    set_gis_scope(project_id='tengkeli', run_id='r-1', area_member=True)
    scope = current_gis_scope()

    assert scope['area_member'] is True
    assert isinstance(scope['project_id'], str)


def test_the_key_is_the_one_the_tool_reads():
    """`AREA_MEMBER` is `'area_member'`."""
    from open_webui.services.artifacts.geotizer.run_scope import AREA_MEMBER

    assert AREA_MEMBER == 'area_member'


def test_a_real_fill_records_the_flag_where_the_adapter_reads_it():
    """`run_geotizer_workflow` records `area_member` on the GIS scope only when it is
    true."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    recorded: dict[str, object] = {}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'member-e2e',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'member-e2e',
            'xlsx': {'download_path': '/geotizer/files/member-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []}, ensure_ascii=False)

    async def drive(area_member):
        await run_geotizer_workflow(
            object_name='Лекын', project_id=None, model_run_id=None,
            run_id=None, allow_draft=True, gis_call=gis_call,
            agent_call=agent_call, area_member=area_member,
        )
        recorded[area_member] = scoped_metadata({}).get(SCOPE_METADATA_KEY)

    asyncio.run(drive(True))
    asyncio.run(drive(False))

    assert recorded[True]['area_member'] is True
    assert 'area_member' not in recorded[False]


def _lines_from_a_member_fill(*, area_member, object_name='', licence_id=None,
                              resolved_name=None):
    """Every status line one fill emits, through the real workflow."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    seen: list[str] = []

    async def emitter(event):
        seen.append(event['data']['description'])

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'member-lines',
                'object_name': resolved_name or object_name,
                'gis_project': {
                    'status': 'resolved',
                    'project_id': 'tengkeli',
                    'object_name': resolved_name or object_name,
                },
                'datacube': {},
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'member-lines',
            'xlsx': {'download_path': '/geotizer/files/member-lines/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []}, ensure_ascii=False)

    asyncio.run(
        run_geotizer_workflow(
            object_name=object_name, project_id=None, model_run_id=None,
            run_id=None, allow_draft=True, gis_call=gis_call,
            agent_call=agent_call, area_member=area_member,
            licence_id=licence_id, event_emitter=emitter,
        )
    )
    return seen


def test_a_member_s_lines_carry_the_member():
    lines = _lines_from_a_member_fill(
        area_member=True, licence_id='МАГ04805БЭ', object_name=''
    )

    assert lines, 'the fill emitted nothing'
    for line in lines:
        assert line.startswith('МАГ04805БЭ:'), line
        assert 'Геотизер' not in line, line


def test_a_resolved_name_reads_better_than_a_number_and_keeps_it():
    """A member with a resolved name prefixes its lines with the name and the licence."""
    lines = _lines_from_a_member_fill(
        area_member=True, licence_id='МАГ04805БЭ', resolved_name='Нявленга'
    )

    assert all(line.startswith('Нявленга (МАГ04805БЭ):') for line in lines), lines


def test_a_member_is_not_named_twice_in_one_line():
    """A member's start line drops the object-name tail that a single-object start line
    keeps."""
    member = _lines_from_a_member_fill(
        area_member=True, licence_id='МАГ04805БЭ', object_name=''
    )[0]
    named = _lines_from_a_member_fill(
        area_member=True, licence_id='МАГ04805БЭ', resolved_name='Нявленга'
    )[0]
    single = _lines_from_a_member_fill(area_member=False, object_name='Нявленга')[0]

    assert member == 'МАГ04805БЭ: запуск member-lines'
    assert named == 'Нявленга (МАГ04805БЭ): запуск member-lines'
    assert single == 'Геотизер: запуск member-lines — Нявленга'


def test_a_single_object_fill_still_says_what_it_always_said():
    """Every line of a single-object fill starts with `Геотизер:`."""
    lines = _lines_from_a_member_fill(area_member=False, object_name='Нявленга')

    assert lines
    for line in lines:
        assert line.startswith('Геотизер:'), line


def test_the_subject_is_one_decision_and_not_nine():
    """No phrase carries a literal subject, and the default subject comes from
    `SUBJECT_DEFAULT`."""
    from open_webui.services.artifacts.geotizer.terminal import (
        PHRASE,
        SUBJECT_DEFAULT,
        StatusSettings,
    )

    for language, table in PHRASE.items():
        for key, phrase in table.items():
            assert 'Геотизер:' not in phrase, (language, key)
            assert 'GeoTeaser:' not in phrase, (language, key)

    for language, expected in SUBJECT_DEFAULT.items():
        assert StatusSettings(language=language).subject_name == expected


def test_a_member_row_is_a_copy_and_not_an_edit():
    """`StatusSettings.about` returns a copy with the new subject and leaves the
    original unchanged."""
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    shared = StatusSettings(language='en', verbosity='technical')
    first = shared.about('МАГ04805БЭ')
    second = shared.about('МАГ05018БР')

    assert shared.subject == ''
    assert (first.subject, second.subject) == ('МАГ04805БЭ', 'МАГ05018БР')
    assert first.language == second.language == 'en'
    assert first.technical and second.technical


def test_the_member_subject_falls_back_rather_than_printing_a_gap():
    from open_webui.services.artifacts.geotizer.terminal import member_subject

    assert member_subject(object_name='Нявленга', licence_id='МАГ04805БЭ') == (
        'Нявленга (МАГ04805БЭ)'
    )
    assert member_subject(licence_id='МАГ04805БЭ') == 'МАГ04805БЭ'
    assert member_subject(object_name='Нявленга') == 'Нявленга'
    assert member_subject(object_name='МАГ04805БЭ', licence_id='МАГ04805БЭ') == (
        'МАГ04805БЭ'
    )
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    assert member_subject() == ''
    assert StatusSettings(subject=member_subject()).say(
        'batch', n=3, total=8, label=''
    ) == 'Геотизер: пакет 3 из 8'


def test_the_licence_travels_to_the_fold():
    """`_fold_member` carries the member's licence, and omits the key when there is
    none."""
    from open_webui.services.artifacts.geotizer.area_workflow import _fold_member

    filled = _fold_member(
        {
            'entity_id': 'МАГ04805БЭ',
            'licence_id': 'МАГ04805БЭ',
            'object_name': 'Нявленга',
            'state': 'filled',
            'run_id': 'r1',
        }
    )
    unreached = _fold_member(
        {'entity_id': 'e2', 'licence_id': 'МАГ05018БР', 'state': 'failed'}
    )

    assert filled['licence_id'] == 'МАГ04805БЭ'
    assert unreached['licence_id'] == 'МАГ05018БР'
    assert 'licence_id' not in _fold_member({'entity_id': 'e3', 'state': 'failed'})
