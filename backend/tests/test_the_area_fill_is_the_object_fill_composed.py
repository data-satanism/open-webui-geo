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
    FOLD_NOT_REQUESTED,
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
    single-object fill of that member are the same call.

    `started_run` is in the set because the object path passes one too: it is
    the member's own run handle, not a fact about the area. So are
    `licence_id` and `licence_layer_id`: a member is identified by its licence,
    and the object path takes both."""
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
            'licence_id', 'licence_layer_id',
        }
        for call in calls
    )
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

    GTA-04's hold is lifted — the operators were decided and the variance was
    measured — so the reason is no longer «the aggregator does not exist». It
    is «no fold was asked for», which is true of this call: nothing was
    injected. A reason that outlives its cause is how a reader infers a
    constraint that was removed months earlier, so the constant changed with
    the fact rather than being left to age.
    """
    result, _ = run(manifest(member('e1', object_name='Нявленга')))

    assert result['aggregation']['state'] == NOT_PERFORMED
    assert result['aggregation']['reason'] == FOLD_NOT_REQUESTED
    # Named, not counted: which of the three was missing is what a caller acts
    # on, and «fold_not_requested» alone does not say.
    assert result['aggregation']['missing'] == [
        'fold_call',
        'policy_version',
        'dossier_run_id',
    ]


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


# ------------------------------- a member run exists and something names it


def test_a_member_that_fails_part_way_keeps_the_run_that_holds_its_work():
    """By the time a fill can raise, the run usually exists.

    It holds whatever was filled before the failure and is the only handle
    anyone has on it. Recording `state: failed` and the exception alone left
    that run in the store with nothing naming it — the caller could not resume
    it, the fold never saw it, and the answer did not mention it.
    """

    async def fill(*, started_run, **kwargs):
        # What `run_geotizer_workflow` does: the id is written as soon as the
        # run exists, which is long before the fill succeeds or fails.
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
    """One mapping per member, never one for the area.

    A shared mapping still holds the last member's id when the next one dies
    before starting, so the area would name a run that belongs to a different
    object. A run id on the wrong member is worse than no run id: it sends a
    caller to a card that is complete and about something else.
    """
    seen: list[str] = []

    async def fill(*, started_run, **kwargs):
        name = kwargs['object_name']
        seen.append(name)
        if name == 'Второй':
            # Died before the run was created — nothing to write.
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
    # The first member's id is recorded, so the second member's missing one is
    # a fact about that member and not about the capture being switched off.
    assert result['members'][0]['run_id'] == 'run-Первый'
    second = result['members'][1]
    assert second['state'] == FAILED
    # Omitted, not blanked and not inherited.
    assert 'run_id' not in second


def test_member_arguments_may_not_carry_a_started_run_for_the_whole_area():
    """One area-wide mapping is the defect the per-member one exists to avoid,
    so it is refused where the other two member identifiers are refused."""
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


# ------------------------------- a member is identified by its own licence


def test_a_member_with_a_licence_is_filled_by_it_and_carries_no_name():
    """The first area run: three members, three identical refusals.

    Each fill reached the object path with the project and no licence, met a
    seven-polygon project with nothing to select by, and refused
    `gis_project_multi_licence`. Three identical failures is what a shared
    argument looks like.

    The area's name is not a member's. Passing it down makes three cards that
    each claim to be the площадь; a member's own name arrives from evidence
    during the fill, or not at all.
    """
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
    # Not the area's name, and not a name at all.
    assert calls[0]['object_name'] == ''


def test_each_member_carries_its_own_licence_and_not_a_shared_one():
    """All three failed identically, which is the symptom this rules out."""
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
    """The name search resolves a project, not a licence. That member has a
    name and no number, and it must keep working."""
    fill, calls = recorder()

    run(
        manifest(member('e1', object_name='Лекын-Тальбейское', project_id='p1')),
        recorder=(fill, calls),
    )

    assert calls[0]['object_name'] == 'Лекын-Тальбейское'
    assert calls[0]['licence_id'] is None


def test_a_member_with_neither_a_name_nor_a_licence_is_not_attempted():
    """A member the fill can neither name nor select. One member, not the area."""
    result, calls = run(manifest(member('e1', project_id='p1')))

    assert calls == []
    assert result['members'][0]['state'] == NOT_ATTEMPTED
    assert result['members'][0]['reason'] == NO_OBJECT_NAME


def test_a_filled_member_is_named_by_its_licence_in_the_area_result():
    """It has no `object_name` to record until evidence gives it one, and a
    member line reading «— заполнен» with no subject names nothing."""
    result, _ = run(
        manifest(dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'))
    )

    assert result['members'][0]['object_name'] == 'МАГ04805БЭ'
    assert result['members'][0]['state'] == FILLED


def test_member_arguments_may_not_carry_a_licence_for_the_whole_area():
    """Bound once for the area it would be the same licence for every member —
    the defect this loop exists to stop having."""
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
    """Zero members filled, so there is nothing to aggregate. The fold was
    never the thing that went wrong."""
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
