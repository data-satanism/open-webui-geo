"""An area fill is the object fill run per member, and it does not roll up."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from open_webui.services.artifacts.geotizer.area_workflow import (
    AREA_DEADLINE_REACHED,
    FAILED,
    FILLED,
    NO_OBJECT_NAME,
    NOT_ATTEMPTED,
    NOT_PERFORMED,
    FOLD_NOT_REQUESTED,
    run_geotizer_area_workflow,
)


def manifest(*members, area_id='area:tengkeli'):
    return {'area_id': area_id, 'members': list(members)}


def member(entity_id, *, object_name=None, rank=0, project_id=None):
    row: dict[str, Any] = {'entity_id': entity_id, 'rank': rank}
    if object_name is not None:
        row['object_name'] = object_name
    if project_id is not None:
        row['project_id'] = project_id
    return row


def recorder(outcome=None, fail_on=()):
    calls: list[dict[str, Any]] = []

    async def fill(**kwargs):
        calls.append(kwargs)
        identity = kwargs.get('licence_id') or kwargs.get('object_name')
        if identity in fail_on:
            raise RuntimeError('gis refused')
        return dict(
            outcome
            or {
                'run_id': f'run-{identity}',
                'status': 'ready',
                'audit': {'completeness': {'filled': 196, 'required': 351}},
            }
        )

    return fill, calls


def run(document, **kwargs):
    fill, calls = kwargs.pop('recorder', recorder())
    result = asyncio.run(
        run_geotizer_area_workflow(manifest=document, member_fill=fill, **kwargs)
    )
    return result, calls


def test_each_member_is_filled_by_the_call_a_single_object_request_makes():
    """A member fill receives only the arguments a single-object fill takes, plus
    `area_member`."""
    fill, calls = recorder()

    result, _ = run(
        manifest(
            member('e1', object_name='Нявленга', project_id='p1'),
            member('e2', object_name='Синтетическое-2'),
        ),
        recorder=(fill, calls),
    )

    assert [call['object_name'] for call in calls] == ['Нявленга', 'Синтетическое-2']
    assert calls[0]['project_id'] == 'p1'
    assert calls[1]['project_id'] is None
    assert all(
        set(call) == {
            'object_name', 'project_id', 'started_run',
            'licence_id', 'licence_layer_id', 'area_member',
        }
        for call in calls
    )
    assert result['counts'] == {'members': 2, FILLED: 2, FAILED: 0, NOT_ATTEMPTED: 0}


def test_the_flag_changes_what_is_said_and_nothing_else():
    """`area_member` is the literal `True` on every member fill."""
    fill, calls = recorder()

    run(
        manifest(
            member('e1', object_name='Нявленга', project_id='p1'),
            member('e2', object_name='Синтетическое-2'),
        ),
        recorder=(fill, calls),
    )

    assert [call['area_member'] for call in calls] == [True, True]
    assert all(call['area_member'] is True for call in calls)


def test_extra_member_arguments_are_passed_through_unchanged():
    """`member_arguments` reach every member fill unchanged."""
    fill, calls = recorder()

    run(
        manifest(member('e1', object_name='Нявленга')),
        recorder=(fill, calls),
        member_arguments={'allow_draft': True, 'run_mode': 'clean'},
    )

    assert calls[0]['allow_draft'] is True
    assert calls[0]['run_mode'] == 'clean'


def test_the_order_is_by_rank_then_id_rather_than_by_dictionary():
    """Members are filled in order of rank, then entity id."""
    fill, calls = recorder()

    run(
        manifest(
            member('z', object_name='Z', rank=2),
            member('a', object_name='A', rank=2),
            member('root', object_name='Root', rank=0),
        ),
        recorder=(fill, calls),
    )

    assert [call['object_name'] for call in calls] == ['Root', 'A', 'Z']


def test_a_member_with_no_object_name_is_recorded_rather_than_skipped():
    """A member with no object name is recorded as not attempted rather than omitted."""
    result, calls = run(manifest(member('e1'), member('e2', object_name='Нявленга')))

    unnamed = next(row for row in result['members'] if row['entity_id'] == 'e1')

    assert unnamed['state'] == NOT_ATTEMPTED
    assert unnamed['reason'] == NO_OBJECT_NAME
    assert [call['object_name'] for call in calls] == ['Нявленга']
    assert result['counts'] == {'members': 2, FILLED: 1, FAILED: 0, NOT_ATTEMPTED: 1}


def test_one_member_failing_is_not_the_area_failing():
    fill, calls = recorder(fail_on={'Синтетическое-2'})

    result, _ = run(
        manifest(
            member('e1', object_name='Нявленга'),
            member('e2', object_name='Синтетическое-2', rank=1),
            member('e3', object_name='Третье', rank=2),
        ),
        recorder=(fill, calls),
    )

    failed = next(row for row in result['members'] if row['entity_id'] == 'e2')

    assert failed['state'] == FAILED
    assert 'RuntimeError' in failed['error']
    assert result['counts'][FILLED] == 2
    assert [call['object_name'] for call in calls] == ['Нявленга', 'Синтетическое-2', 'Третье']


def test_the_area_deadline_stops_the_run_and_names_who_was_not_reached():
    """Members not reached before the area deadline are recorded as not attempted with
    the deadline reason."""
    ticks = iter([0.0, 0.0, 10.0, 10.0, 10.0, 10.0])
    fill, calls = recorder()

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                member('e1', object_name='Первое'),
                member('e2', object_name='Второе', rank=1),
                member('e3', object_name='Третье', rank=2),
            ),
            member_fill=fill,
            area_deadline_seconds=5.0,
            clock=lambda: next(ticks),
        )
    )

    assert [call['object_name'] for call in calls] == ['Первое']
    unreached = [row for row in result['members'] if row['state'] == NOT_ATTEMPTED]
    assert [row['entity_id'] for row in unreached] == ['e2', 'e3']
    assert all(row['reason'] == AREA_DEADLINE_REACHED for row in unreached)


def test_the_aggregation_that_does_not_exist_says_so():
    """Without a fold, the aggregation carries a not-performed state, the
    `fold_not_requested` reason and the missing inputs by name."""
    result, _ = run(manifest(member('e1', object_name='Нявленга')))

    assert result['aggregation']['state'] == NOT_PERFORMED
    assert result['aggregation']['reason'] == FOLD_NOT_REQUESTED
    assert result['aggregation']['missing'] == [
        'fold_call',
        'policy_version',
        'dossier_run_id',
    ]


def test_no_area_level_completeness_is_published():
    """Each member keeps its own completeness and the area publishes no total."""
    result, _ = run(
        manifest(
            member('e1', object_name='Нявленга'),
            member('e2', object_name='Синтетическое-2', rank=1),
        )
    )

    assert 'completeness' not in result
    assert all(
        row['completeness'] == {'filled': 196, 'required': 351}
        for row in result['members']
        if row['state'] == FILLED
    )


def test_a_member_run_id_survives_so_a_failed_area_stays_resumable():
    result, _ = run(manifest(member('e1', object_name='Нявленга')))

    assert result['members'][0]['run_id'] == 'run-Нявленга'
    assert result['area_id'] == 'area:tengkeli'


def test_an_area_with_no_members_is_not_an_error_and_not_a_success():
    result, calls = run(manifest())

    assert calls == []
    assert result['counts']['members'] == 0
    assert result['aggregation']['state'] == NOT_PERFORMED


def test_a_member_that_fails_part_way_keeps_the_run_that_holds_its_work():
    """A member that fails after its run started keeps that run's id."""

    async def fill(*, started_run, **kwargs):
        started_run['run_id'] = f'run-{kwargs["object_name"]}'
        raise RuntimeError('gis refused at batch 4')

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(member('e1', object_name='Нявленга')),
            member_fill=fill,
        )
    )

    failed = result['members'][0]
    assert failed['state'] == FAILED
    assert failed['run_id'] == 'run-Нявленга'
    assert 'RuntimeError' in failed['error']


def test_a_failed_member_never_borrows_the_previous_members_run_id():
    """A member that fails before its run starts carries no run id, not the previous
    member's."""
    seen: list[str] = []

    async def fill(*, started_run, **kwargs):
        name = kwargs['object_name']
        seen.append(name)
        if name == 'Второй':
            raise RuntimeError('refused at the door')
        started_run['run_id'] = f'run-{name}'
        return {'run_id': f'run-{name}', 'status': 'ready', 'audit': {}}

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                member('e1', object_name='Первый', rank=0),
                member('e2', object_name='Второй', rank=1),
            ),
            member_fill=fill,
        )
    )

    assert seen == ['Первый', 'Второй']
    assert result['members'][0]['run_id'] == 'run-Первый'
    second = result['members'][1]
    assert second['state'] == FAILED
    assert 'run_id' not in second


def test_member_arguments_may_not_carry_a_started_run_for_the_whole_area():
    """`member_arguments` carrying `started_run` is refused with a `ValueError`."""
    fill, _ = recorder()

    with pytest.raises(ValueError) as caught:
        asyncio.run(
            run_geotizer_area_workflow(
                manifest=manifest(member('e1', object_name='Нявленга')),
                member_fill=fill,
                member_arguments={'started_run': {}},
            )
        )

    assert 'started_run' in str(caught.value)


def test_a_member_with_a_licence_is_filled_by_it_and_carries_no_name():
    """A member with a licence is filled by that licence and its layer, with an empty
    object name."""
    fill, calls = recorder()

    run(
        manifest(
            dict(member('МАГ04805БЭ', object_name='Тенгкели-Березовская площадь',
                        project_id='p1'),
                 licence_id='МАГ04805БЭ',
                 licence_layer_id='Sint_licences_2025exp_clp'),
        ),
        recorder=(fill, calls),
    )

    assert calls[0]['licence_id'] == 'МАГ04805БЭ'
    assert calls[0]['licence_layer_id'] == 'Sint_licences_2025exp_clp'
    assert calls[0]['project_id'] == 'p1'
    assert calls[0]['object_name'] == ''


def test_each_member_carries_its_own_licence_and_not_a_shared_one():
    """Each member fill carries that member's own licence."""
    fill, calls = recorder()

    run(
        manifest(
            dict(member('a', project_id='p1'), licence_id='МАГ04805БЭ'),
            dict(member('b', rank=1, project_id='p1'), licence_id='МАГ05018БР'),
            dict(member('c', rank=2, project_id='p1'), licence_id='МАГ05252БР'),
        ),
        recorder=(fill, calls),
    )

    assert [call['licence_id'] for call in calls] == [
        'МАГ04805БЭ', 'МАГ05018БР', 'МАГ05252БР',
    ]


def test_a_member_without_a_licence_is_still_filled_by_its_name():
    """A member without a licence is filled by its object name."""
    fill, calls = recorder()

    run(
        manifest(member('e1', object_name='Лекын-Тальбейское', project_id='p1')),
        recorder=(fill, calls),
    )

    assert calls[0]['object_name'] == 'Лекын-Тальбейское'
    assert calls[0]['licence_id'] is None


def test_a_member_with_neither_a_name_nor_a_licence_is_not_attempted():
    """A member with neither a name nor a licence is not attempted."""
    result, calls = run(manifest(member('e1', project_id='p1')))

    assert calls == []
    assert result['members'][0]['state'] == NOT_ATTEMPTED
    assert result['members'][0]['reason'] == NO_OBJECT_NAME


def test_a_filled_member_is_named_by_its_licence_in_the_area_result():
    """A filled licence member is named by its licence in the area result."""
    result, _ = run(
        manifest(dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'))
    )

    assert result['members'][0]['object_name'] == 'МАГ04805БЭ'
    assert result['members'][0]['state'] == FILLED


def test_member_arguments_may_not_carry_a_licence_for_the_whole_area():
    """`member_arguments` carrying `licence_id` or `licence_layer_id` is refused with a
    `ValueError`."""
    fill, _ = recorder()

    for field in ('licence_id', 'licence_layer_id'):
        with pytest.raises(ValueError) as caught:
            asyncio.run(
                run_geotizer_area_workflow(
                    manifest=manifest(member('e1', object_name='X')),
                    member_fill=fill,
                    member_arguments={field: 'МАГ04805БЭ'},
                )
            )
        assert field in str(caught.value)


def test_nothing_filled_is_not_a_fold_that_failed():
    """With nothing filled, a wired fold is not called and the reason is
    `nothing_filled`."""
    async def fill(**kwargs):
        raise RuntimeError('gis refused')

    async def fold(payload):
        raise AssertionError('the fold must not be called with nothing to fold')

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
            ),
            member_fill=fill,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
        )
    )

    assert result['aggregation']['state'] == NOT_PERFORMED
    assert result['aggregation']['reason'] == 'nothing_filled'
    assert result['aggregation']['members_total'] == 1
    assert result['aggregation']['members_filled'] == 0


def test_the_fold_is_told_what_the_area_s_id_is_a_digest_of():
    """The fold payload carries `project_id`, `calculation_crs` and `area_display_name`."""
    fill, _calls = recorder()
    seen: list[dict[str, Any]] = []

    async def fold(payload):
        seen.append(payload)
        return {'aggregation': {'fields': []}, 'summary_markdown': '#'}

    asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(dict(member('e1', object_name='X'), licence_id='МАГ04805БЭ')),
            member_fill=fill,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
            project_id='tengkeli',
            calculation_crs='EPSG:32653',
            area_display_name='Тенгкели-Березовская площадь',
        )
    )

    assert seen[0]['project_id'] == 'tengkeli'
    assert seen[0]['calculation_crs'] == 'EPSG:32653'
    assert seen[0]['area_display_name'] == 'Тенгкели-Березовская площадь'


def test_where_the_area_s_files_are_reaches_the_document():
    """The fold's `area_run_id` and `artifacts` are carried into the area document."""
    fill, _calls = recorder()

    async def fold(payload):
        return {
            'aggregation': {'fields': []},
            'summary_markdown': '#',
            'area_run_id': 'area_' + 'b' * 64,
            'artifacts': {'written': True, 'files': {}, 'missing_inputs': []},
        }

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(dict(member('e1', object_name='X'), licence_id='МАГ04805БЭ')),
            member_fill=fill,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
        )
    )

    assert result['area_run_id'] == 'area_' + 'b' * 64
    assert result['artifacts']['written'] is True


def test_an_unwired_fold_says_so_even_when_nothing_was_filled():
    """An unwired fold reports `fold_not_requested` even when nothing was filled."""
    async def fill(**kwargs):
        raise RuntimeError('gis refused')

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
            ),
            member_fill=fill,
        )
    )

    aggregation = result['aggregation']
    assert aggregation['reason'] == FOLD_NOT_REQUESTED
    assert sorted(aggregation['missing']) == [
        'dossier_run_id', 'fold_call', 'policy_version',
    ]


def test_a_wired_fold_with_nothing_filled_still_says_nothing_was_filled():
    """The other side of the same order: wiring present, nothing to fold."""
    async def fill(**kwargs):
        raise RuntimeError('gis refused')

    async def fold(payload):
        raise AssertionError('the fold must not be called with nothing to fold')

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
            ),
            member_fill=fill,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
        )
    )

    assert result['aggregation']['reason'] == 'nothing_filled'


def test_a_licence_member_past_the_deadline_is_named_by_its_licence():
    """A licence member past the area deadline is named by its licence."""
    ticks = iter([0.0, 0.0, 10.0, 10.0])
    fill, calls = recorder()

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
                dict(member('e2', rank=1, project_id='p1'),
                     licence_id='МАГ05018БР'),
            ),
            member_fill=fill,
            area_deadline_seconds=5.0,
            clock=lambda: next(ticks),
        )
    )

    unreached = [row for row in result['members'] if row['state'] == NOT_ATTEMPTED]
    assert [row['entity_id'] for row in unreached] == ['e2']
    assert unreached[0]['object_name'] == 'МАГ05018БР'


def test_a_licence_member_that_fails_is_named_by_its_licence():
    """A licence member whose fill fails is named by its licence."""
    fill, _ = recorder(fail_on=('МАГ04805БЭ',))

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
            ),
            member_fill=fill,
        )
    )

    failed = result['members'][0]
    assert failed['state'] == FAILED
    assert failed['object_name'] == 'МАГ04805БЭ'


def test_each_licence_member_gets_its_own_run_id():
    """Each licence member records its own run id."""
    fill, _ = recorder()

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
                dict(member('e2', rank=1, project_id='p1'),
                     licence_id='МАГ05018БР'),
            ),
            member_fill=fill,
        )
    )

    assert [row['run_id'] for row in result['members']] == [
        'run-МАГ04805БЭ', 'run-МАГ05018БР',
    ]


def progress_of(document, **kwargs):
    """Every counts mapping the loop reported, in order."""
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    result, calls = run(document, on_progress=on_progress, **kwargs)
    return seen, result, calls


def test_the_area_reports_its_size_before_anything_is_scheduled():
    """The first progress report carries the member count before any member starts."""
    seen, _result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2', object_name='B'))
    )

    assert seen[0] == {
        'members': 2, 'running': 0, 'filled': 0, 'failed': 0, 'not_attempted': 0,
    }


def test_it_ends_with_every_member_accounted_for():
    seen, result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2', object_name='B'))
    )

    assert seen[-1] == {
        'members': 2, 'running': 0, 'filled': 2, 'failed': 0, 'not_attempted': 0,
    }
    assert seen[-1]['filled'] == result['counts'][FILLED]


def test_the_terms_always_sum_to_the_member_count():
    """No progress report counts more members than the area has."""
    seen, _result, _calls = progress_of(
        manifest(
            member('e1', object_name='A'),
            member('e2', object_name='B'),
            member('e3', object_name='C'),
        ),
        concurrent_members=2,
    )

    for counts in seen:
        total = (
            counts['running'] + counts['filled']
            + counts['failed'] + counts['not_attempted']
        )
        assert total <= counts['members'], counts


def test_a_failed_member_is_counted_as_failed_and_not_as_done():
    fill, calls = recorder(fail_on=('B',))
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    run(
        manifest(member('e1', object_name='A'), member('e2', object_name='B')),
        recorder=(fill, calls),
        on_progress=on_progress,
    )

    assert seen[-1]['filled'] == 1
    assert seen[-1]['failed'] == 1


def test_a_member_with_no_identity_is_counted_as_not_attempted():
    """A member with no identity ends counted as not attempted."""
    seen, _result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2'))
    )

    assert seen[-1] == {
        'members': 2, 'running': 0, 'filled': 1, 'failed': 0, 'not_attempted': 1,
    }


def test_it_costs_one_report_per_transition_and_not_one_per_round():
    """Progress is reported once before scheduling and once per member start and settle."""
    seen, _result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2', object_name='B'))
    )

    assert len(seen) == 5


def test_an_emitter_that_raises_does_not_fail_a_member():
    """A raising progress emitter does not fail a member."""
    async def on_progress(counts):
        raise RuntimeError('the socket went away')

    result, _calls = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    assert result['counts'][FILLED] == 1


def test_no_reporter_is_the_ordinary_case_and_changes_nothing():
    without, _calls = run(manifest(member('e1', object_name='A')))

    async def on_progress(counts):
        return None

    with_reporter, _calls2 = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    assert without['counts'] == with_reporter['counts']


def test_a_member_that_raises_past_the_inner_guard_is_still_counted():
    """A member that raises outside the fill's own handler is counted as failed in the
    progress line."""
    class Hostile(dict):
        def get(self, key, default=None):
            if key == 'licence_layer_id':
                raise RuntimeError('the manifest is not what it claimed')
            return super().get(key, default)

    fill, calls = recorder()
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    result, _calls = run(
        {'area_id': 'area:x', 'members': [Hostile(entity_id='e1', rank=0)]},
        recorder=(fill, calls),
        on_progress=on_progress,
    )

    assert result['counts'][FAILED] == 1
    assert seen[-1] == {
        'members': 1, 'running': 0, 'filled': 0, 'failed': 1, 'not_attempted': 0,
    }


def gated_recorder():
    """Return a `member_fill` that suspends until released, the `asyncio.Event` that
    releases it, and the list of object names that entered it."""
    release = asyncio.Event()
    inside: list[str] = []

    async def fill(**kwargs):
        inside.append(str(kwargs.get('object_name') or ''))
        await release.wait()
        return {'run_id': f'run-{kwargs.get("object_name")}', 'status': 'ok', 'audit': {}}

    return fill, release, inside


async def until(reached, *, steps: int = 2000) -> bool:
    """Yield to the loop until `reached()` is true; return False after `steps` yields
    without it."""
    for _ in range(steps):
        if reached():
            return True
        await asyncio.sleep(0)
    return False


def test_the_counters_hold_while_members_genuinely_overlap():
    """With two slots and three suspended members, the progress line counts two running
    and does not count the queued member as running."""
    fill, release, inside = gated_recorder()
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    async def drive():
        task = asyncio.create_task(
            run_geotizer_area_workflow(
                manifest=manifest(
                    member('e1', object_name='A'),
                    member('e2', object_name='B'),
                    member('e3', object_name='C'),
                ),
                member_fill=fill,
                concurrent_members=2,
                on_progress=on_progress,
            )
        )
        assert await until(lambda: len(inside) >= 2), inside
        held = [dict(counts) for counts in seen]
        release.set()
        return held, await task

    held, result = asyncio.run(drive())

    assert max(counts['running'] for counts in held) == 2, held
    assert held[-1] == {
        'members': 3, 'running': 2, 'filled': 0, 'failed': 0, 'not_attempted': 0,
    }
    assert result['counts'][FILLED] == 3
    assert seen[-1] == {
        'members': 3, 'running': 0, 'filled': 3, 'failed': 0, 'not_attempted': 0,
    }


def test_no_member_is_ever_in_none_of_the_states_while_the_others_run():
    """Settled counts never decrease and `running` never goes negative while members
    overlap."""
    fill, release, _inside = gated_recorder()
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    async def drive():
        task = asyncio.create_task(
            run_geotizer_area_workflow(
                manifest=manifest(
                    member('e1', object_name='A'),
                    member('e2', object_name='B'),
                    member('e3', object_name='C'),
                ),
                member_fill=fill,
                concurrent_members=3,
                on_progress=on_progress,
            )
        )
        assert await until(lambda: len(seen) >= 4), seen
        release.set()
        return await task

    asyncio.run(drive())

    settled = -1
    for counts in seen:
        assert counts['running'] >= 0, counts
        done = counts['filled'] + counts['failed'] + counts['not_attempted']
        assert done >= settled, seen
        settled = done
        assert counts['running'] + done <= counts['members'], counts
    assert settled == 3


def test_the_line_never_moves_backwards_when_two_members_settle_at_once():
    """Progress reports arrive in order and none is dropped when two members settle at
    once."""
    delivered: list[int] = []

    async def on_progress(counts):
        if counts['filled'] == 1 and counts['running'] == 0:
            await asyncio.sleep(0.05)
        delivered.append(counts['filled'])

    run(
        manifest(member('e1', object_name='A'), member('e2', object_name='B')),
        concurrent_members=2,
        on_progress=on_progress,
    )

    assert delivered == sorted(delivered), delivered
    assert delivered == [0, 0, 1, 1, 2], delivered


def test_a_member_cancelled_while_reporting_does_not_leak_into_the_in_flight_count():
    """A cancellation during a member's start report does not leave that member counted
    as running."""
    seen: list[dict[str, int]] = []
    cancelled: list[int] = []

    async def on_progress(counts):
        seen.append(dict(counts))
        if counts['running'] == 1 and not cancelled:
            cancelled.append(1)
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        run(
            manifest(member('e1', object_name='A'), member('e2', object_name='B')),
            concurrent_members=1,
            on_progress=on_progress,
        )

    assert max(counts['running'] for counts in seen) == 1, seen
    assert seen[-1]['running'] == 0, seen


def test_a_reporter_that_keeps_raising_says_so_in_the_answer():
    """A progress emitter that always raises is recorded in `progress_line` with its
    attempts, failures and first error."""
    async def on_progress(counts):
        raise KeyError('area_progress')

    result, _calls = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    record = result['progress_line']
    assert record['failures'] == record['attempts'] == 3
    assert record['error'] == "KeyError: 'area_progress'"
    assert result['counts'][FILLED] == 1


def test_a_line_that_reached_every_time_leaves_no_record():
    """A progress emitter that never fails leaves no `progress_line`."""
    async def on_progress(counts):
        return None

    result, _calls = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    assert 'progress_line' not in result


def test_nobody_watching_is_not_a_failed_line():
    """Without `on_progress` the document has no `progress_line`."""
    result, _calls = run(manifest(member('e1', object_name='A')))

    assert 'progress_line' not in result


def test_the_line_counts_the_same_three_states_the_document_does():
    """`_SETTLED` holds exactly the settled states the document counts, and not
    `running`."""
    from open_webui.services.artifacts.geotizer.area_workflow import _SETTLED

    result, _calls = run(manifest(member('e1', object_name='A')))

    assert set(_SETTLED) == set(result['counts']) - {'members'}
    assert 'running' not in _SETTLED


def test_the_licence_reaches_the_fold_through_the_member_loop():
    """Each member's licence reaches the fold payload through the member loop."""
    sent: dict = {}

    async def fill(**kwargs):
        return {'run_id': 'r1', 'status': 'ready', 'audit': {'completeness': {}}}

    async def fold(payload):
        sent.update(payload)
        return {'aggregation': {'fields': []}, 'policy_version': 'geotizer_area_aggregation.v1'}

    asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
                dict(member('e2', project_id='p1'), licence_id='МАГ05018БР'),
            ),
            member_fill=fill,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
            project_id='p1',
            calculation_crs='EPSG:32653',
        )
    )

    assert [m.get('licence_id') for m in sent['members']] == [
        'МАГ04805БЭ',
        'МАГ05018БР',
    ]


def test_the_licence_travels_even_when_the_member_crashes():
    """A member whose fill raises reaches the fold as unreached and carrying its
    licence."""
    sent: dict = {}

    async def fill(**kwargs):
        raise RuntimeError('boom')

    async def fold(payload):
        sent.update(payload)
        return {'aggregation': {'fields': []}, 'policy_version': 'geotizer_area_aggregation.v1'}

    async def half(**kwargs):
        if kwargs.get('licence_id') == 'МАГ05018БР':
            raise RuntimeError('boom')
        return {'run_id': 'r1', 'status': 'ready', 'audit': {'completeness': {}}}

    asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
                dict(member('e2', project_id='p1'), licence_id='МАГ05018БР'),
            ),
            member_fill=half,
            fold_call=fold,
            policy_version='geotizer_area_aggregation.v1',
            dossier_run_id='dossier-1',
            project_id='p1',
            calculation_crs='EPSG:32653',
        )
    )

    by_entity = {m['entity_id']: m for m in sent['members']}
    assert by_entity['e2'].get('licence_id') == 'МАГ05018БР'
    assert by_entity['e2'].get('unreached')


def test_a_member_that_crashed_outright_still_carries_its_licence():
    """`_crashed` carries the member's licence and adds none when the member has none."""
    from open_webui.services.artifacts.geotizer.area_workflow import _crashed

    rebuilt = _crashed(
        {'entity_id': 'e1', 'licence_id': 'МАГ04805БЭ'}, RuntimeError('boom')
    )

    assert rebuilt['licence_id'] == 'МАГ04805БЭ'
    assert 'licence_id' not in _crashed({'entity_id': 'e2'}, RuntimeError('boom'))
