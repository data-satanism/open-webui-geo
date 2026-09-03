"""An area fill is the object fill run per member, and it does not roll up.

The single-object path is the measured one — four runs of one build at 207,
191, 219 and 137 of 351, and three pairs since at 202, 183 and 193 statuses
identical. A branch inside it would put that path one step from an unmeasured
one. So the area path composes it: each member is filled by exactly the call a
single-object request makes, and the area supplies only what a member cannot —
its own scope, its own order, and its own bound.

What is asserted here is the composition, not the fill: that the member call is
indistinguishable from a single-object call, that nothing is silently dropped,
and that the aggregation that does not exist says so rather than reading as
zero.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from open_webui.services.artifacts.geotizer.area_workflow import (
    AGGREGATOR_HELD,
    AREA_DEADLINE_REACHED,
    FAILED,
    FILLED,
    NO_OBJECT_NAME,
    NOT_ATTEMPTED,
    NOT_PERFORMED,
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
        if kwargs['object_name'] in fail_on:
            raise RuntimeError('gis refused')
        return dict(
            outcome
            or {
                'run_id': f'run-{kwargs["object_name"]}',
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


# ------------------------------------------------- the member call is the object call


def test_each_member_is_filled_by_the_call_a_single_object_request_makes():
    """No area argument reaches the member fill. A member fill and a
    single-object fill of that member are the same call."""
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
    assert all(set(call) == {'object_name', 'project_id'} for call in calls)
    assert result['counts'] == {'members': 2, FILLED: 2, FAILED: 0, NOT_ATTEMPTED: 0}


def test_extra_member_arguments_are_passed_through_unchanged():
    """The contour's own arguments — the drain, the registry, the KB scope —
    belong to every member fill and are not the area's to reinterpret."""
    fill, calls = recorder()

    run(
        manifest(member('e1', object_name='Нявленга')),
        recorder=(fill, calls),
        member_arguments={'allow_draft': True, 'run_mode': 'clean'},
    )

    assert calls[0]['allow_draft'] is True
    assert calls[0]['run_mode'] == 'clean'


def test_the_order_is_by_rank_then_id_rather_than_by_dictionary():
    """It matters the moment anything stops the run part-way: whichever members
    come last are the ones that never get filled."""
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


# ------------------------------------------------------ nothing is silently dropped


def test_a_member_with_no_object_name_is_recorded_rather_than_skipped():
    """A member absent from the result reads as one that succeeded and returned
    nothing."""
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
    """Without an area bound, twenty-one members spend twenty-one member
    deadlines. With one, the members past it are named, not omitted."""
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


# ------------------------------------------------------------ it does not roll up


def test_the_aggregation_that_does_not_exist_says_so():
    """A missing key reads as an oversight and a zero reads as a measurement.
    GTA-04 is held on two grounds that have not moved."""
    result, _ = run(manifest(member('e1', object_name='Нявленга')))

    assert result['aggregation']['state'] == NOT_PERFORMED
    assert result['aggregation']['reason'] == AGGREGATOR_HELD
    assert result['aggregation']['double_count_guard'] == 'unenforced'
    assert 'UNENFORCED' in result['aggregation']['double_count_guard_note']


def test_no_area_level_completeness_is_published():
    """Each member keeps its own; there is no total, and none must look like
    there is one."""
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
