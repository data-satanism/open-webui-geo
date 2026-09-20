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
        # Keyed the way production keys a member: by its licence when it has
        # one. Deriving the run id from `object_name` alone produced the same
        # `run-` for every licence member, so an assertion across several of
        # them could not have told correct behaviour from all of them
        # collapsing onto one run — the shape of bug this file exists to catch,
        # one layer up.
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


# ------------------------------------------------- the member call is the object call


def test_each_member_is_filled_by_the_call_a_single_object_request_makes():
    """Nothing that changes the card reaches the member fill. A member's
    card and a single-object card of that member are the same card.

    `started_run` is in the set because the object path passes one too: it is
    the member's own run handle, not a fact about the area. So are
    `licence_id` and `licence_layer_id`: a member is identified by its licence,
    and the object path takes both.

    `area_member` is the one argument that says «area» out loud, and it is
    admitted on a narrower claim than the one this test used to make. It
    changes nothing the fill does: no batch, no prompt, no cell, no
    artefact. It changes what the ORCHESTRATOR says — a member's
    per-specialist lines carry no member identity, and seven members
    emitting them into one description field is seven interleaved streams.
    The tool sees one `run_agent_task` call and cannot tell a member from a
    single fill, so the caller is the only thing that can say which.

    The guarantee this test exists for is intact and is now stated as what
    it always meant: a member fill produces the card a single-object fill
    would. `test_the_flag_changes_what_is_said_and_nothing_else` below is
    the other half of it.
    """
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
    """`area_member` is true on every member and is the only area-shaped
    argument in the call.

    Asserted by name rather than by counting the set above: a future
    argument added to the fill would grow that set and this would still be
    checking the thing it is about.
    """
    fill, calls = recorder()

    run(
        manifest(
            member('e1', object_name='Нявленга', project_id='p1'),
            member('e2', object_name='Синтетическое-2'),
        ),
        recorder=(fill, calls),
    )

    assert [call['area_member'] for call in calls] == [True, True]
    # And it is the literal `True`, not a string. The orchestrator reads
    # `bool(scope.get('area_member'))`, for which `'False'` is true — so a
    # stringified flag is one `str()` away from being unable to say no.
    assert all(call['area_member'] is True for call in calls)


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


def test_the_fold_is_told_what_the_area_s_id_is_a_digest_of():
    """`project_id`, `calculation_crs` and the display name.

    Without the first two the service can compute no area id and writes no
    artefacts, and the answer reaches the reader with a summary and no link —
    which is the state the first seven-member area was reported in. The name
    travels too, and never as the path: the service digests the other three
    and keeps this one for the title.
    """
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
    """Carried, not recomputed. `render_area_answer` reads it from here, and
    a record that stopped at the fold would be a link the reader never
    sees."""
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
    """Two independent facts, and «нечего сворачивать» is true of both.

    A run that would not have folded a filled member either has one fact worth
    knowing — that no fold was configured at all — and the zero-filled reason
    hid it. The module's own header forbids exactly this: a reason true of two
    situations is a reason a reader cannot act on.
    """
    async def fill(**kwargs):
        raise RuntimeError('gis refused')

    result = asyncio.run(
        run_geotizer_area_workflow(
            manifest=manifest(
                dict(member('e1', project_id='p1'), licence_id='МАГ04805БЭ'),
            ),
            member_fill=fill,
            # Nothing wired: no call, no policy, no dossier run.
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
    """Its `entity_id` is a dossier id and its name is empty, so without the
    fallback the area reports «— не начинался» about nothing."""
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
    # The licence, not the dossier id and not an empty string.
    assert unreached[0]['object_name'] == 'МАГ05018БР'


def test_a_licence_member_that_fails_is_named_by_its_licence():
    """Same fallback, the branch a real run reaches first."""
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
    """The fake used to derive every licence member's run id from an empty
    name, so three members shared one — invisible to every assertion."""
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


# -- The area's progress, as a state rather than a stream ---------------------


def progress_of(document, **kwargs):
    """Every counts mapping the loop reported, in order."""
    seen: list[dict[str, int]] = []

    async def on_progress(counts):
        seen.append(dict(counts))

    result, calls = run(document, on_progress=on_progress, **kwargs)
    return seen, result, calls


def test_the_area_reports_its_size_before_anything_is_scheduled():
    """Seven members at three at a time is about six hours. A first line six
    hours in is no line."""
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
    # And the line agrees with the document the same loop built.
    assert seen[-1]['filled'] == result['counts'][FILLED]


def test_the_terms_always_sum_to_the_member_count():
    """Every intermediate state too, not only the ends: a transition that
    decremented one counter without incrementing another would show as a
    member that briefly belongs to no state."""
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
    """It never enters `running`, and it must still leave `waiting` — a
    member stuck in a state it can never leave makes the line wrong for the
    rest of the run."""
    seen, _result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2'))
    )

    assert seen[-1] == {
        'members': 2, 'running': 0, 'filled': 1, 'failed': 0, 'not_attempted': 1,
    }


def test_it_costs_one_report_per_transition_and_not_one_per_round():
    """The whole point. Two members: one line before, then start and settle
    for each."""
    seen, _result, _calls = progress_of(
        manifest(member('e1', object_name='A'), member('e2', object_name='B'))
    )

    assert len(seen) == 5


def test_an_emitter_that_raises_does_not_fail_a_member():
    """A member that filled and an emitter that failed are not the same
    event, and the second must not become the first."""
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
    """`_fill_member` catches around the fill; it does not catch around
    reading the member's identity. `gather` turns that into a `failed`
    member, so the counter has to agree — a member left in `running` makes
    every later line wrong for the rest of the run.
    """
    class Hostile(dict):
        # Raises on a key read BEFORE the gate, which is the region the
        # inner `except Exception` does not cover. `licence_layer_id`
        # specifically: `_crashed` does not read it, so the failure being
        # measured is the member's and not the recorder's.
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


# -- The line under real concurrency, and what it costs when it fails ---------
#
# Everything above reports through a `member_fill` that never suspends, and a
# coroutine with no suspension point runs to completion in one scheduler step:
# `gather` then runs them one after another whatever the bound says, and
# `running` never exceeds one. So the counters have been measured only
# sequentially, and the line's whole reason to exist is seven members at once.


def gated_recorder():
    """A `member_fill` that genuinely suspends, and a handle to release it.

    `asyncio.Event` rather than `sleep`: a sleep makes the interleaving a
    function of the scheduler's timing, and a test whose overlap depends on
    timing reports its own flakiness as a defect in the counter.
    """
    release = asyncio.Event()
    inside: list[str] = []

    async def fill(**kwargs):
        inside.append(str(kwargs.get('object_name') or ''))
        await release.wait()
        return {'run_id': f'run-{kwargs.get("object_name")}', 'status': 'ok', 'audit': {}}

    return fill, release, inside


async def until(reached, *, steps: int = 2000) -> bool:
    """Yield to the loop until `reached()`, or give up and say so.

    Bounded, because a mutation that stops the counter advancing would
    otherwise hang the suite rather than fail a test — and a hang reports
    every defect as the same one.
    """
    for _ in range(steps):
        if reached():
            return True
        await asyncio.sleep(0)
    return False


def test_the_counters_hold_while_members_genuinely_overlap():
    """Three members, two slots, every one of them suspended at once.

    The bound is what makes this measurable: with two slots the third member
    is waiting, so a correct line reads «заполняется 2 · ожидают 1» and a
    counter that counted queued members as running would read three.
    """
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
        # Let both slots fill and the third member queue behind them.
        assert await until(lambda: len(inside) >= 2), inside
        held = [dict(counts) for counts in seen]
        release.set()
        return held, await task

    held, result = asyncio.run(drive())

    # Two really were in flight together, which is what nothing above measured.
    assert max(counts['running'] for counts in held) == 2, held
    # And the third was NOT counted as running while it waited for a slot.
    assert held[-1] == {
        'members': 3, 'running': 2, 'filled': 0, 'failed': 0, 'not_attempted': 0,
    }
    assert result['counts'][FILLED] == 3
    assert seen[-1] == {
        'members': 3, 'running': 0, 'filled': 3, 'failed': 0, 'not_attempted': 0,
    }


def test_no_member_is_ever_in_none_of_the_states_while_the_others_run():
    """The invariant `total <= members` cannot see this and says it does.

    A member that has left `running` before it is counted as filled is
    absent from every term for the length of one report, and a ceiling
    comparison tolerates any shortfall. What pins it is that the four terms
    only ever move FORWARD: a member that has started is in exactly one of
    them at every later line, so `filled + failed + not_attempted` never
    decreases and `running` never goes negative.
    """
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
        # Three members entered, so the line has reported the size once and
        # a start three times. A count rather than a sleep: the point is the
        # state, and a sleep would make the test's own timing part of it.
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
    """One `description` field, rewritten. Two members settling while an
    emitter is awaiting each take their own snapshot and arrive in whichever
    order the socket finishes them — and «готово 2» replaced by «готово 1»
    is the line reporting a member un-filling itself.

    The slow delivery is picked by CONTENT rather than by call order, and
    the members do not suspend: the whole scenario then hangs on one
    assumption, that fifty milliseconds outlasts a handful of steps that
    never yield. An earlier version gated the members on an `asyncio.Event`
    and released it a step later, and whether the two reports overlapped at
    all depended on where that step landed — it caught the missing lock run
    alone and did not when the file ran beside three others. A test whose
    subject is an ordering must not have an ordering of its own.
    """
    delivered: list[int] = []

    async def on_progress(counts):
        # The first member's SETTLE line, and only it. Its start line
        # carries the same `filled` a moment earlier, so the count alone
        # would slow both and serialise the thing under test by accident.
        if counts['filled'] == 1 and counts['running'] == 0:
            await asyncio.sleep(0.05)
        delivered.append(counts['filled'])

    run(
        manifest(member('e1', object_name='A'), member('e2', object_name='B')),
        concurrent_members=2,
        on_progress=on_progress,
    )

    assert delivered == sorted(delivered), delivered
    # And every line was delivered, rather than the slow one being dropped:
    # a lock that swallowed a report would also satisfy «never backwards».
    assert delivered == [0, 0, 1, 1, 2], delivered


def test_a_member_cancelled_while_reporting_does_not_leak_into_the_in_flight_count():
    """`report()` suspends between «this member is running» and the guard
    that says it stopped.

    A `CancelledError` delivered there is not caught by `report`, correctly —
    masking cancellation is worse. What must not happen is that it skips the
    decrement: the counter's own comment promises the section is balanced
    whichever way it ends, and the next member would then be reported as the
    second of two in flight when it is the only one.
    """
    seen: list[dict[str, int]] = []
    cancelled: list[int] = []

    async def on_progress(counts):
        seen.append(dict(counts))
        # On the FIRST member's running-transition only, so the second
        # member's own line is what carries the answer.
        if counts['running'] == 1 and not cancelled:
            cancelled.append(1)
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        run(
            manifest(member('e1', object_name='A'), member('e2', object_name='B')),
            concurrent_members=1,
            on_progress=on_progress,
        )

    # The second member ran alone, and the area ended with nobody in
    # flight. Leaked, the decrement never happens: the second member is
    # reported as the second of two filling, and the last line of an area
    # that has stopped still says one member is working.
    assert max(counts['running'] for counts in seen) == 1, seen
    assert seen[-1]['running'] == 0, seen


def test_a_reporter_that_keeps_raising_says_so_in_the_answer():
    """A dead socket and a broken sentence raise here identically, and a
    bare `pass` makes them the same event: the line stops advancing and
    nothing anywhere says why. This contour's server log cannot be exported,
    so the record has to travel in the document."""
    async def on_progress(counts):
        raise KeyError('area_progress')

    result, _calls = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    record = result['progress_line']
    # Every attempt failed, which is what separates a defect in the sentence
    # from a blip on the wire.
    assert record['failures'] == record['attempts'] == 3
    assert record['error'] == "KeyError: 'area_progress'"
    # And the members were filled anyway.
    assert result['counts'][FILLED] == 1


def test_a_line_that_reached_every_time_leaves_no_record():
    """«The line worked» written fifteen times is read never, and a key
    present on every area cannot say anything by being there."""
    async def on_progress(counts):
        return None

    result, _calls = run(
        manifest(member('e1', object_name='A')), on_progress=on_progress
    )

    assert 'progress_line' not in result


def test_nobody_watching_is_not_a_failed_line():
    """`on_progress=None` is most callers. A record saying the line failed
    would send whoever reads it after a socket that was never opened."""
    result, _calls = run(manifest(member('e1', object_name='A')))

    assert 'progress_line' not in result


def test_the_line_counts_the_same_three_states_the_document_does():
    """`state in counts` was the membership test, and `counts` also holds
    `members` and `running` — so a member reporting `state: 'running'` would
    have incremented the in-flight counter and left it there for the rest of
    the run. Unreachable from the four exits today, and one refactor from
    reachable, which is why the two lists are compared rather than trusted.
    """
    from open_webui.services.artifacts.geotizer.area_workflow import _SETTLED

    result, _calls = run(manifest(member('e1', object_name='A')))

    assert set(_SETTLED) == set(result['counts']) - {'members'}
    assert 'running' not in _SETTLED


def test_the_licence_reaches_the_fold_through_the_member_loop():
    """Through the real loop, not by calling `_fold_member` with a dict that
    already has the licence on it. `_fill_member` has five exits and none of
    them carried one, so a test of the last step alone would pass while the
    fold still received `licence_id: null` for every member — which is what
    `area_6c2d1043…` recorded for all seven of them, in four places."""
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
