"""The area tool's four outcomes, and the one that costs a day if it is wrong.

`fill_geoteaser_area` resolves licences, fills each as its own object, folds
the result and renders it. Three of its outcomes are answers a user reads and
never a run: a question when a name is ambiguous, a refusal when a number
resolves to nothing, and a refusal when the area is larger than the deadline.

That third one is the whole of §3 until the job model exists. A tool that
accepts twenty-one members and dies at hour four has lost a day and produced
nothing; one that refuses in a second has cost nothing and said why.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.area_request import (
    LICENCE_AMBIGUOUS,
    LICENCE_NOT_FOUND,
    MISSING_CONTRACT,
    REFUSED,
    RESOLVED,
    TOO_MANY_MEMBERS,
    ASK,
    cost_phrase,
    fill_area,
    member_ceiling,
    render_area_answer,
    resolve_area_members,
)

POLICY = 'geotizer_area_aggregation.v1'
CRS = 'EPSG:32642'


#: The actions `geotizer_fill` actually declares, copied from
#: `gis_service/arcgis_mcp/geotizer/api.py::GeotizerFillRequest`. The area
#: actions are deliberately absent, because they are absent there.
FILL_ACTIONS = frozenset({
    'start',
    'resolve_scope',
    'infrastructure_proposals',
    'grr_schedule_proposals',
    'validate_batch',
    'submit_batch',
    'finalize',
    'get',
    'list_runs',
})


class Service:
    """Three operations on the tool server, each refusing what the real one does.

    The first version of this fake was one callable that answered any action,
    which let `fill_area` send `resolve_area_scope` and `fold_area` to
    `geotizer_fill` and be answered. In production that is a 422 at the second
    call of every area fill: those are separate operations with separate
    request models, and `geotizer_fill`'s action set contains neither.

    A fake that accepts what the real endpoint refuses is not a stand-in for
    it; it is a second bug agreeing with the first. So each call here refuses
    an action that does not belong to it, and the original defect fails this
    file rather than passing it.
    """

    def __init__(self, **entries):
        self.entries = entries
        self.fold_payload = None
        self.scope_payload = None

    async def fill(self, payload):
        action = payload['action']
        if action not in FILL_ACTIONS:
            raise AssertionError(f'geotizer_fill has no action {action!r}')
        if action == 'resolve_scope':
            return {
                'workflow_status': 'ok',
                'scope_resolution': {
                    'candidates': self.entries.get(payload['query'], []),
                    'searched_projects': 49026,
                },
            }
        raise AssertionError(f'unexpected fill action {action!r}')

    async def scope(self, payload):
        assert payload['action'] == 'resolve_area_scope', payload['action']
        self.scope_payload = payload
        return {
            'area_id': payload['area_scope_id'],
            'members': [
                {'entity_id': m['entity_id'], 'name': m['name']}
                for m in payload['members']
            ],
            'relations': [],
        }

    async def fold(self, payload):
        assert payload['action'] == 'fold_area', payload['action']
        self.fold_payload = payload
        return {
            'policy_version': POLICY,
            'aggregation': {'counts': {'aggregated': 7}},
            'summary': {'members': payload['members']},
            'summary_markdown': '## Свод площади\n\n7 строк сведено.',
        }


def registry(**entries):
    return Service(**entries)


def licence(number, project='p1', name=''):
    record = {'project_id': project, 'licence_id': number, 'licence_layer_id': 'L1'}
    if name:
        record['object_name'] = name
    return record


async def fill(*, object_name, project_id=None, **_):
    if object_name == 'СЛХ025834ТП':
        raise RuntimeError('specialist timeout')
    return {
        'run_id': f'run-{object_name}',
        'status': 'finalized',
        'audit': {'completeness': {'filled': 190, 'of': 351}},
    }


@pytest.mark.asyncio
async def test_supplied_numbers_are_not_searched_for_and_not_asked_about():
    """«заполни область из лицензий А, Б, В» is three numbers and no ambiguity.

    A tool that searched anyway would turn an unambiguous request into a
    question, which is the same discourtesy as guessing pointed the other way.
    """
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], СЛХ025834ТП=[licence('СЛХ025834ТП')])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'СЛХ025834ТП']
    )

    assert answer['status'] == RESOLVED
    assert answer['resolved_from'] == 'supplied'
    assert [m['entity_id'] for m in answer['members']] == ['МАГ03394БЭ', 'СЛХ025834ТП']


@pytest.mark.asyncio
async def test_one_number_that_resolves_to_nothing_refuses_the_whole_area():
    """Filling two of three gives an area whose `members_total` is 2 when three
    were asked for, and every folded figure is then honest about a membership
    the user did not choose. The fold would be right and the answer wrong."""
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], АНД99999БЭ=[])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'АНД99999БЭ']
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert answer['licence_id'] == 'АНД99999БЭ'
    # Both are named, so a reader can see which of the two failed.
    assert 'МАГ03394БЭ — найдена' in answer['message']
    assert 'АНД99999БЭ — не найдена' in answer['message']


@pytest.mark.asyncio
async def test_a_number_in_several_layers_refuses_rather_than_picking():
    gis = registry(ДВА00000БЭ=[licence('ДВА00000БЭ'), licence('ДВА00000БЭ')])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['ДВА00000БЭ'])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS


@pytest.mark.asyncio
async def test_a_name_matching_several_asks_and_says_what_all_of_them_costs():
    """The cost line is load-bearing. A user choosing «all of them» should know
    it is days rather than hours, and this project measured that."""
    gis = registry(**{
        'Лекын-Тальбейская площадь': [
            licence('МАГ03394БЭ', name='Лекын-Тальбейское'),
            licence('СЛХ025834ТП', name='Восточно-Лекынское'),
            licence('АНД01313БП'),
        ]
    })

    answer = await resolve_area_members(
        gis_call=gis.fill, object_name='Лекын-Тальбейская площадь'
    )

    assert answer['status'] == ASK
    question = answer['question']
    # Found, and their numbers.
    assert 'найдено 3 лицензии' in question
    for number in ('МАГ03394БЭ', 'СЛХ025834ТП', 'АНД01313БП'):
        assert number in question
    # The object name where one is known, and no dangling dash where none is.
    assert 'МАГ03394БЭ — Лекын-Тальбейское' in question
    assert 'АНД01313БП — ' not in question
    # What «all of them» would cost.
    assert cost_phrase(3) in question


@pytest.mark.asyncio
async def test_an_area_larger_than_the_deadline_refuses_before_anything_runs():
    numbers = [f'X{i:05d}БЭ' for i in range(21)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == REFUSED
    assert answer['reason'] == TOO_MANY_MEMBERS
    assert answer['members_total'] == 21
    assert answer['ceiling'] == member_ceiling()
    # The figure the user is being spared, in the words they would have read
    # four hours in.
    assert '21 участник, примерно 55 часов' in answer['message']


@pytest.mark.asyncio
async def test_the_two_contract_fields_are_refused_by_name_and_never_picked():
    gis = registry()

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=['МАГ03394БЭ'],
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == MISSING_CONTRACT
    assert 'policy_version' in answer['message']
    assert 'calculation_crs' in answer['message']


@pytest.mark.asyncio
async def test_a_three_member_area_fills_folds_and_summarises():
    """The run this task exists to make possible.

    Three members, one of which fails. The failure does not become an absence:
    it reaches the fold as `member_run_failed`, because a member missing from
    the fold reads as a member that contributed nothing, and those are
    different facts about a 351-row card.
    """
    numbers = ['МАГ03394БЭ', 'СЛХ025834ТП', 'АНД01313БП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-lekyn',
        dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    result = answer['result']
    assert result['counts'] == {
        'members': 3,
        'filled': 2,
        'failed': 1,
        'not_attempted': 0,
    }
    assert result['aggregation']['state'] == 'performed'
    assert result['aggregation']['link_guard'] == 'enforced'

    sent = {member['entity_id']: member for member in gis.fold_payload['members']}
    assert sent['МАГ03394БЭ']['run_id'] == 'run-МАГ03394БЭ'
    assert sent['СЛХ025834ТП']['unreached'] == 'member_run_failed'
    # The manifest goes with it, because the one case the double-count guard
    # does not run is the case where nobody sends it.
    assert gis.fold_payload['scope']['area_id'] == 'area-lekyn'
    assert gis.fold_payload['policy_version'] == POLICY

    rendered = render_area_answer(answer)
    assert 'run-МАГ03394БЭ' in rendered
    assert 'не заполнен' in rendered
    assert 'Свод площади' in rendered


@pytest.mark.asyncio
async def test_each_service_call_goes_to_the_operation_that_declares_it():
    """The bug this file did not catch the first time.

    `fill_area` makes three service calls to three operations. The first
    version passed one handle to all of them, so `resolve_area_scope` and
    `fold_area` were sent to `geotizer_fill` — whose action set contains
    neither and whose request forbids the fields they carry. Every area fill
    would have been refused at its second call, and nothing said so, because
    the fake answered any action.

    `Service.fill` now raises on an action `geotizer_fill` does not declare, so
    reverting `fill_area` to one handle fails here instead of shipping.
    """
    numbers = ['МАГ03394БЭ', 'СЛХ025834ТП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='dossier-1',
    )

    # Each operation saw its own action and no other.
    assert gis.scope_payload['action'] == 'resolve_area_scope'
    assert gis.fold_payload['action'] == 'fold_area'


@pytest.mark.asyncio
async def test_sending_an_area_action_to_the_fill_operation_is_refused():
    """The positive control for the fake itself.

    A guard that has never rejected anything is not evidence of anything, so
    this proves `Service.fill` really does refuse an area action rather than
    passing everything through.
    """
    gis = registry()

    with pytest.raises(AssertionError, match='geotizer_fill has no action'):
        await gis.fill({'action': 'fold_area'})
