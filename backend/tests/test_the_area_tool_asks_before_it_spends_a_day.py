"""Tests for the area tool: member resolution, its question and refusals, the
calculation contract, the rendered answer, and the adapter's call sites in
`tools/geotizer.py`."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest

from open_webui.services.artifacts.geotizer.area_workflow import (
    run_geotizer_area_workflow,
)
from open_webui.services.artifacts.geotizer.area_request import (
    LICENCE_AMBIGUOUS,
    LICENCE_NOT_FOUND,
    MANIFEST_WITHOUT_MEMBERS,
    MISSING_CONTRACT,
    ARG_ACCEPTED,
    ARG_NOT_CONFIRMED,
    ARG_NOT_FOUND,
    ARG_NOT_HONOURED,
    ARG_NOT_PASSED,
    NOTHING_TO_RESOLVE,
    POLICY_VERSION_UNKNOWN,
    PROJECT_NOT_FOUND,
    SCOPE_AMBIGUOUS,
    SCOPE_NOT_APPLIED,
    SCOPE_UNVERIFIABLE,
    SEARCH_UNREADABLE,
    received_line,
    LAYER_NOT_AMONG_CANDIDATES,
    CRS_NOT_RECOGNISED,
    NAME_SEARCH_HAS_NO_POLYGON,
    NO_CENTROID,
    REFUSED,
    RESOLVED,
    contract_line,
    epsg_code,
    is_projected,
    resolve_calculation_crs,
    utm_zone_for,
    ASK,
    ambiguous_licence,
    area_deadline_seconds,
    cost_notice,
    fill_area,
    render_area_answer,
    resolve_contract,
    resolve_area_members,
)
from open_webui.services.artifacts.geotizer.area_request import (
    _member_line,
    _scope_echo,
)

POLICY = 'geotizer_area_aggregation.v1'
CRS = 'EPSG:32642'


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
    """Fake tool server whose `fill`, `scope` and `fold` operations each reject
    an action the real operation does not declare."""

    def __init__(self, projects=None, scopes=True, **entries):
        self.entries = entries
        self._projects = None if projects is None else list(projects)
        self.scopes = scopes
        self.fold_payload = None
        self.scope_payload = None
        self.scope_queries: list[dict] = []

    def known_projects(self):
        """Return the store's projects, shaped as `nearest_projects` returns
        them, derived from the fixture rows unless `projects` was given."""
        if self._projects is not None:
            return [dict(item) for item in self._projects]
        seen: dict[str, dict] = {}
        for rows in self.entries.values():
            for item in rows:
                pid = str(item.get('project_id') or '').strip()
                if pid:
                    seen.setdefault(
                        pid, {'project_id': pid, 'name': pid, 'layers_count': 1}
                    )
        return list(seen.values())

    @staticmethod
    def _named(known, named):
        """Return the one project whose id equals `named`, else the one whose
        name or id matches it case-insensitively, else None."""
        for item in known:
            if str(item.get('project_id') or '') == named:
                return item
        folded = named.casefold()
        matches = [
            item for item in known
            if str(item.get('name') or '').casefold() == folded
            or str(item.get('project_id') or '').casefold() == folded
        ]
        return matches[0] if len(matches) == 1 else None

    def _nothing_matched(self, query, scope):
        """Return the service's «none» answer: an empty `candidates` when
        scoped, otherwise the known projects under `candidates` marked by
        `candidates_are`."""
        resolution = {
            'query': query,
            'status': 'none',
            'searched_projects': 1 if scope else 49026,
        }
        if scope:
            resolution['scoped_to_project'] = scope
            resolution['candidates'] = []
            resolution['known_project_count'] = len(self.known_projects())
            code = 'scope_not_found_in_project'
        else:
            resolution['candidates'] = self.known_projects()
            resolution['candidates_are'] = 'known_projects'
            resolution['known_project_count'] = len(self.known_projects())
            code = 'scope_not_found'
        return {
            'workflow_status': 'needs_input',
            'scope_resolution': resolution,
            'error': {'code': code, 'message': f'Nothing matched {query!r}.'},
        }

    async def fill(self, payload):
        action = payload['action']
        if action not in FILL_ACTIONS:
            raise AssertionError(f'geotizer_fill has no action {action!r}')
        if action == 'resolve_scope':
            self.scope_queries.append(dict(payload))
            known = self.known_projects()
            scope = str(payload.get('project_id') or '').strip()
            if scope and not self.scopes:
                found = list(self.entries.get(payload['query'], []))
                if not found:
                    return self._nothing_matched(payload['query'], '')
                resolution = {
                    'candidates': found,
                    'searched_projects': len(known),
                }
                if len(found) > 1:
                    resolution['status'] = 'several'
                    return {
                        'workflow_status': 'needs_input',
                        'scope_resolution': resolution,
                        'error': {
                            'code': 'scope_several_candidates',
                            'message': f'{payload["query"]} matched several rows.',
                        },
                    }
                return {'workflow_status': 'ok', 'scope_resolution': resolution}
            if scope:
                matched = self._named(known, scope)
                if matched is None:
                    return {
                        'workflow_status': 'needs_input',
                        'scope_resolution': {
                            'query': payload['query'],
                            'status': 'none',
                            'candidates': known,
                            'candidates_are': 'known_projects',
                            'requested_project_id': scope,
                            'searched_projects': 0,
                        },
                        'error': {
                            'code': 'scope_project_not_found',
                            'message': f'No project matches {scope!r}.',
                        },
                    }
                scope = str(matched.get('project_id') or '')
            found = list(self.entries.get(payload['query'], []))
            if scope:
                found = [
                    item for item in found
                    if str(item.get('project_id') or '') == scope
                ]
            if not found:
                return self._nothing_matched(payload['query'], scope)
            resolution = {
                'candidates': found,
                'searched_projects': 1 if scope else 49026,
            }
            if scope:
                resolution['scoped_to_project'] = scope
            return {'workflow_status': 'ok', 'scope_resolution': resolution}
        raise AssertionError(f'unexpected fill action {action!r}')

    async def scope(self, payload):
        """Return the manifest `resolve_area_scope` returns, with members under
        `entities` and the id under `area_scope_id`."""
        assert payload['action'] == 'resolve_area_scope', payload['action']
        self.scope_payload = payload
        return {
            'schema_version': 1,
            'area_scope_id': payload['area_scope_id'],
            'project_id': payload['project_id'],
            'policy_version': payload['policy_version'],
            'entities': [
                {
                    'entity_id': m['entity_id'],
                    'entity_type': m['entity_type'],
                    'name': m['name'],
                    'reality_status': 'real',
                    'geometry_ref': None,
                    'source_refs': [],
                }
                for m in payload['members']
            ],
            'relations': [],
            'root_entity_ids': [],
            'unresolved_entities': [],
            'totals': {'entities': len(payload['members']), 'relations': 0},
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


def registry(projects=None, scopes=True, **entries):
    """Return a `Service` over licence rows keyed by query; `projects` declares
    projects that own none of the rows."""
    return Service(projects=projects, scopes=scopes, **entries)


MAGADAN = (150.8, 61.6)


def licence(number, project='p1', name='', layer='L1', centroid=MAGADAN):
    """Return a candidate as `find_licence_across_projects` returns one, with
    `centroid_lon`/`centroid_lat` unless `centroid` is None."""
    record = {'project_id': project, 'licence_id': number, 'licence_layer_id': layer}
    if name:
        record['object_name'] = name
    if centroid is not None:
        record['centroid_lon'], record['centroid_lat'] = centroid
    return record


def project_match(project_id, name, layers=1):
    """Return a candidate as a name search returns one: `project_id`,
    `object_name` and `layers_count`, with no `licence_id`."""
    return {'project_id': project_id, 'object_name': name, 'layers_count': layers}


async def fill(*, object_name, project_id=None, licence_id=None, **_):
    """Fake single-object fill keyed on `licence_id`: raises for `СЛХ025834ТП`
    and otherwise returns a finalized run."""
    assert licence_id or object_name, 'a member fill needs an identity'
    if licence_id == 'СЛХ025834ТП':
        raise RuntimeError('specialist timeout')
    return {
        'run_id': f'run-{licence_id or object_name}',
        'status': 'finalized',
        'audit': {'completeness': {'filled': 190, 'of': 351}},
    }


@pytest.mark.asyncio
async def test_supplied_numbers_are_not_searched_for_and_not_asked_about():
    """Supplied licence numbers resolve as supplied, in order, without a
    question."""
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], СЛХ025834ТП=[licence('СЛХ025834ТП')])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'СЛХ025834ТП']
    )

    assert answer['status'] == RESOLVED
    assert answer['resolved_from'] == 'supplied'
    assert [m['entity_id'] for m in answer['members']] == ['МАГ03394БЭ', 'СЛХ025834ТП']


@pytest.mark.asyncio
async def test_one_number_that_resolves_to_nothing_refuses_the_whole_area():
    """One licence number that resolves to nothing refuses the whole area, and
    the message names each number's outcome."""
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], АНД99999БЭ=[])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'АНД99999БЭ']
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert answer['licence_id'] == 'АНД99999БЭ'
    assert 'МАГ03394БЭ — найдена' in answer['message']
    assert 'АНД99999БЭ — не найдена' in answer['message']


@pytest.mark.asyncio
async def test_a_named_project_scopes_the_search():
    """The registry hit is not a candidate when the caller named a project."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Тенгкели-Березовская площадь',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'Тенгкели-Березовская площадь'
    assert answer['members'][0]['licence_layer_id'] == 'Sint_licences_2025exp_clp'


@pytest.mark.asyncio
async def test_the_project_reaches_the_search_and_is_not_merely_recorded():
    """The caller's `project_id` is sent in the `resolve_scope` payload."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [licence(number, project='p-named')]})

    await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id='p-named',
    )

    assert gis.scope_queries[0]['project_id'] == 'p-named'


@pytest.mark.asyncio
async def test_without_a_project_the_multi_project_refusal_still_fires():
    """Without a `project_id`, a licence found in two projects is refused as
    ambiguous and the search is unscoped."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'project_id' not in gis.scope_queries[0]


@pytest.mark.asyncio
async def test_the_multi_project_refusal_names_the_argument_that_exists():
    """The multi-project refusal names `project_id` and both projects, and
    never `licence_layers`."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])
    message = answer['message']

    assert '`project_id`' in message
    assert 'licence_layers' not in message
    assert 'GIS_Data_RF' in message
    assert 'Тенгкели-Березовская площадь' in message
    assert 'общероссийский реестр' in message


@pytest.mark.asyncio
async def test_a_scoped_search_that_finds_nothing_does_not_fall_back_to_all():
    """A scoped search that finds nothing is refused as not found, naming the
    searched project, instead of falling back to all projects."""
    number = 'МАГ04805БЭ'
    gis = registry(
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'GIS_Data_RF'},
            {
                'project_id': 'Тенгкели-Березовская площадь',
                'name': 'Тенгкели-Березовская площадь',
            },
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id='Тенгкели-Березовская площадь',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'Тенгкели-Березовская площадь' in answer['message']


@pytest.mark.asyncio
async def test_a_number_in_several_layers_refuses_rather_than_picking():
    gis = registry(ДВА00000БЭ=[
        licence('ДВА00000БЭ', layer='Licenses_2024_2025'),
        licence('ДВА00000БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['ДВА00000БЭ'])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS


@pytest.mark.asyncio
async def test_the_multi_layer_refusal_names_its_layers():
    """The multi-layer refusal names each layer and its meaning, and does not
    name `licence_layers`."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
        licence('МАГ03395БЭ', layer='Juniors'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['layers'] == ['Licenses_2024_2025', 'Licenses_annul', 'Juniors']
    for layer in answer['layers']:
        assert layer in message
    assert 'действующие' in message and 'аннулированные' in message
    assert 'licence_layers' not in message
    assert 'состояния одной лицензии' in message
    assert 'параметра для этого у инструмента нет' in message


@pytest.mark.asyncio
async def test_two_rows_in_one_layer_do_not_get_a_layer_instruction():
    """One layer in two projects is refused with the row count and a
    `project_id` instruction, not a layer instruction."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', project='p1', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', project='p2', layer='Licenses_2024_2025'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'найдена 2 раз' in message
    assert 'p1' in message and 'p2' in message
    assert '`project_id`' in message
    assert 'licence_layers' not in message


@pytest.mark.asyncio
async def test_a_row_with_no_layer_name_is_listed_and_said_to_be_unselectable():
    """A row with no layer name is listed in the refusal and said to be
    unselectable."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer=''),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'слой не назван' in message
    assert 'выбрать нельзя' in message


@pytest.mark.asyncio
async def test_the_qualifier_is_read_before_the_count_is_judged():
    """`licence_layers` narrows the candidates before the ambiguity check."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ'],
        licence_layers={'МАГ03395БЭ': 'Licenses_annul'},
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['licence_layer_id'] == 'Licenses_annul'


@pytest.mark.asyncio
async def test_one_licences_layer_choice_does_not_reach_another():
    """A `licence_layers` choice for one licence does not apply to another."""
    gis = registry(
        МАГ03395БЭ=[
            licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
            licence('МАГ03395БЭ', layer='Licenses_annul'),
        ],
        МАГ03400БЭ=[
            licence('МАГ03400БЭ', layer='Licenses_2024_2025'),
            licence('МАГ03400БЭ', layer='Juniors'),
        ],
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ', 'МАГ03400БЭ'],
        licence_layers={'МАГ03395БЭ': 'Licenses_annul'},
    )

    assert answer['status'] == REFUSED
    assert answer['licence_id'] == 'МАГ03400БЭ'
    assert answer['layers'] == ['Licenses_2024_2025', 'Juniors']


@pytest.mark.asyncio
async def test_a_layer_this_licence_is_not_in_says_so_and_names_the_ones_it_is():
    """A chosen layer the licence is not in is refused with
    `LAYER_NOT_AMONG_CANDIDATES`, naming the chosen and the available
    layers."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ'],
        licence_layers={'МАГ03395БЭ': 'Juniors'},
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LAYER_NOT_AMONG_CANDIDATES
    assert 'Juniors' in answer['message']
    assert 'Licenses_annul' in answer['message']


@pytest.mark.asyncio
async def test_a_lone_candidate_in_the_wrong_layer_is_still_the_wrong_layer():
    """A single candidate outside the chosen layer is refused, not accepted."""
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ', layer='Licenses_annul')])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03394БЭ'],
        licence_layers={'МАГ03394БЭ': 'Licenses_2024_2025'},
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LAYER_NOT_AMONG_CANDIDATES
    assert answer['layers'] == ['Licenses_annul']
    assert 'Licenses_2024_2025' in answer['message']


def test_the_worked_examples_resolve_to_the_zones_the_task_names():
    """`utm_zone_for` resolves the worked examples to their EPSG codes,
    including the southern-hemisphere band."""
    assert utm_zone_for(150.8, 61.6) == 'EPSG:32656'
    assert utm_zone_for(66.5, 67.2) == 'EPSG:32642'
    assert utm_zone_for(132.0, 47.0) == 'EPSG:32653'
    assert utm_zone_for(150.8, -61.6) == 'EPSG:32756'


def test_an_area_spanning_several_zones_takes_one_and_records_the_span():
    """An area spanning several zones takes the zone of its centre and records
    the zones spanned."""
    members = [
        {'centroid_lon': 148.0, 'centroid_lat': 61.0},
        {'centroid_lon': 160.0, 'centroid_lat': 61.0},
    ]

    resolved = resolve_calculation_crs(members)

    assert resolved['crs'] == 'EPSG:32656'
    assert resolved['spans_several_zones'] is True
    assert resolved['zones_spanned'] == ['EPSG:32655', 'EPSG:32657']
    assert resolved['members_with_centroid'] == 2


def test_an_area_crossing_the_antimeridian_is_not_put_in_the_north_sea():
    """An area crossing the antimeridian takes EPSG:32660 with its centroid
    longitude at ±180°."""
    resolved = resolve_calculation_crs([
        {'centroid_lon': 179.5, 'centroid_lat': 66.0},
        {'centroid_lon': -179.5, 'centroid_lat': 66.0},
    ])

    assert resolved['crs'] == 'EPSG:32660'
    assert resolved['centroid'][0] in (180.0, -180.0)
    assert resolved['spans_several_zones'] is True


def test_a_single_zone_area_says_so_rather_than_saying_nothing():
    """A single-zone area reports `spans_several_zones` as False rather than
    omitting it."""
    resolved = resolve_calculation_crs([{'centroid_lon': 150.8, 'centroid_lat': 61.6}])

    assert resolved['spans_several_zones'] is False
    assert resolved['zones_spanned'] == ['EPSG:32656']


def test_a_member_without_a_centroid_is_counted_and_not_guessed():
    """A member without a centroid is counted in `members_total` and not in
    `members_with_centroid`."""
    resolved = resolve_calculation_crs([
        {'centroid_lon': 150.8, 'centroid_lat': 61.6},
        {'centroid_lon': 151.2, 'centroid_lat': 61.4},
        {'centroid_lon': None, 'centroid_lat': None},
    ])

    assert resolved['members_with_centroid'] == 2
    assert resolved['members_total'] == 3


def test_no_centroid_at_all_is_none_rather_than_a_zone():
    assert resolve_calculation_crs([{'centroid_lon': None, 'centroid_lat': None}]) is None
    assert resolve_calculation_crs([]) is None


def test_a_centroid_that_is_not_a_number_is_a_member_without_one():
    """NaN, infinite and non-numeric centroids count as members without a
    centroid instead of raising."""
    resolved = resolve_calculation_crs([
        {'centroid_lon': 150.8, 'centroid_lat': 61.6},
        {'centroid_lon': float('nan'), 'centroid_lat': 61.6},
        {'centroid_lon': float('inf'), 'centroid_lat': 61.6},
        {'centroid_lon': 'not-a-number', 'centroid_lat': 61.6},
    ])

    assert resolved['crs'] == 'EPSG:32656'
    assert resolved['members_with_centroid'] == 1
    assert resolved['members_total'] == 4


def test_a_one_shot_iterable_does_not_produce_a_self_contradicting_record():
    """A one-shot iterable of members yields consistent `members_with_centroid`
    and `members_total`."""
    resolved = resolve_calculation_crs(
        iter([{'centroid_lon': 150.8, 'centroid_lat': 61.6}])
    )

    assert resolved['members_with_centroid'] == 1
    assert resolved['members_total'] == 1


def test_the_no_centroid_refusal_states_a_cause_that_is_true_of_the_members():
    """The no-centroid refusal counts and names each member's reported cause."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='',
        members=[
            {'centroid_lon': None, 'centroid_lat': None,
             'centroid_unavailable': 'outside_the_world'},
            {'centroid_lon': None, 'centroid_lat': None,
             'centroid_unavailable': 'unreadable:OSError'},
        ],
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert answer['causes'] == {'outside_the_world': 1, 'unreadable:OSError': 1}
    assert 'проекция не выполнена' in answer['message']
    assert 'OSError' in answer['message']
    assert 'не читается' in answer['message']


def test_a_member_that_reported_no_cause_is_not_given_one():
    """A member with no reported cause is counted as `unknown` and described as
    «причина не сообщена»."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='',
        members=[{'centroid_lon': None, 'centroid_lat': None}],
    )

    assert answer['causes'] == {'unknown': 1}
    assert 'причина не сообщена' in answer['message']


def test_the_answer_states_both_values_and_which_was_the_systems():
    """`contract_line` states both contract values and that the system resolved
    them."""
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'geotizer_area_aggregation.v1' in line
    assert 'EPSG:32656' in line
    assert 'по центроиду площади' in line
    assert 'по умолчанию для этой сборки' in line


def test_every_geographic_crs_is_refused_however_it_is_spelled():
    """`is_projected` rejects every spelling of a geographic CRS and accepts
    every spelling of a projected one."""
    for spelling in ('4326', 'epsg:4326', 'EPSG: 4326', ' EPSG:4326 ',
                     '4284', '7683', '4979'):
        assert is_projected(spelling) is False, spelling

    for spelling in ('EPSG:32656', '32656', 'epsg:32642', 'EPSG: 32653'):
        assert is_projected(spelling) is True, spelling


def test_a_crs_this_tool_cannot_place_is_its_own_refusal():
    """A CRS that is not an EPSG code is refused with `CRS_NOT_RECOGNISED`
    without being called geographic."""
    assert epsg_code('WGS 84 / UTM zone 56N') is None

    answer = resolve_contract(
        policy_version='',
        calculation_crs='WGS 84 / UTM zone 56N',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == CRS_NOT_RECOGNISED
    assert answer['failed'] == 'calculation_crs'
    assert 'а это географическая' not in answer['message']
    assert 'не код EPSG' in answer['message']


def test_a_bare_number_reaches_the_geographic_refusal_not_the_unrecognised_one():
    """A bare geographic EPSG number is refused as geographic, not as
    unrecognised."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='4326',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['reason'] == MISSING_CONTRACT
    assert 'географическая' in answer['message']


def test_a_recognised_crs_is_recorded_as_the_caller_wrote_it():
    """A recognised CRS is judged normalised and recorded verbatim."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='epsg: 32656',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['status'] == RESOLVED
    assert answer['calculation_crs']['value'] == 'epsg: 32656'


@pytest.mark.asyncio
async def test_filling_by_name_without_a_crs_refuses_and_says_which_way_out():
    """Without a CRS, a name-search area is refused with `NO_CENTROID`, cause
    `NAME_SEARCH_HAS_NO_POLYGON`, and pointed to licence numbers."""
    async def search(payload):
        assert payload['action'] == 'resolve_scope'
        return {'scope_resolution': {'candidates': [
            project_match('p1', 'Лекын-Тальбейская площадь'),
        ]}}

    answer = await resolve_area_members(gis_call=search, object_name='Лекын')
    assert answer['status'] == RESOLVED
    assert answer['members'][0]['centroid_unavailable'] == NAME_SEARCH_HAS_NO_POLYGON

    refusal = resolve_contract(
        policy_version='', calculation_crs='', members=answer['members'],
    )

    assert refusal['status'] == REFUSED
    assert refusal['reason'] == NO_CENTROID
    assert refusal['causes'] == {NAME_SEARCH_HAS_NO_POLYGON: 1}
    assert 'номера лицензий' in refusal['message']
    assert 'причина не сообщена' not in refusal['message']


@pytest.mark.asyncio
async def test_filling_by_name_with_a_crs_is_not_refused():
    """A name-search area with a supplied CRS resolves and states its cost."""
    async def search(payload):
        assert payload['action'] == 'resolve_scope'
        return {'scope_resolution': {'candidates': [
            project_match('p1', 'Лекын-Тальбейская площадь'),
        ]}}

    answer = await resolve_area_members(gis_call=search, object_name='Лекын')
    contract = resolve_contract(
        policy_version='', calculation_crs='EPSG:32642', members=answer['members'],
    )

    assert contract['status'] == RESOLVED
    assert contract['calculation_crs'] == {'value': 'EPSG:32642', 'source': 'supplied'}
    assert '1 участник, примерно 3 часа' in answer['cost_notice']


def test_a_zone_taken_from_one_member_of_twenty_says_so():
    """`contract_line` states how many members the zone's centroid was taken
    from when it is fewer than all."""
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'members_with_centroid': 1, 'members_total': 20,
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'центроид по 1 из 20 участников' in line


def test_full_coverage_is_not_announced():
    """Full centroid coverage adds no clause to `contract_line`."""
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'members_with_centroid': 20, 'members_total': 20,
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'из 20' not in line


def test_a_supplied_value_is_not_described_as_a_resolved_one():
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'p.v1', 'source': 'supplied'},
        'calculation_crs': {'value': 'EPSG:32642', 'source': 'supplied'},
    })

    assert 'указана в запросе' in line
    assert 'по центроиду' not in line
    assert 'по умолчанию' not in line


@pytest.mark.asyncio
async def test_the_rendered_answer_carries_the_line_a_reader_sees():
    """`render_area_answer` carries the contract line."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number, name='Нявленга')]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )
    markdown = render_area_answer(answer)

    assert 'geotizer_area_aggregation.v1' in markdown
    assert 'EPSG:32656' in markdown
    assert 'по центроиду площади' in markdown


@pytest.mark.asyncio
async def test_the_manifest_the_workflow_receives_records_how_each_was_obtained():
    """The manifest passed to the workflow, and the workflow's result, record
    each contract value and its source."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})
    seen = {}

    async def spy(*, manifest, **kwargs):
        seen.update(manifest)
        return await run_geotizer_area_workflow(manifest=manifest, **kwargs)

    with mock.patch(
        'open_webui.services.artifacts.geotizer.area_request'
        '.run_geotizer_area_workflow',
        spy,
    ):
        answer = await fill_area(
            gis_call=gis.fill,
            scope_call=gis.scope,
            fold_call=gis.fold,
            member_fill=fill,
            licence_ids=[number],
            calculation_crs='EPSG:32642',
        )

    expected = {
        'policy_version': {
            'value': 'geotizer_area_aggregation.v1', 'source': 'resolved',
        },
        'calculation_crs': {'value': 'EPSG:32642', 'source': 'supplied'},
    }
    assert seen['contract_resolution'] == expected
    assert answer['result']['contract_resolution'] == expected


@pytest.mark.asyncio
async def test_the_workflow_receives_what_the_area_s_id_is_a_digest_of():
    """The workflow receives the resolved `calculation_crs`, the reconciled
    `project_id` and the area's display name."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})
    seen = {}

    async def spy(*, manifest, **kwargs):
        seen.update(kwargs)
        return await run_geotizer_area_workflow(manifest=manifest, **kwargs)

    with mock.patch(
        'open_webui.services.artifacts.geotizer.area_request'
        '.run_geotizer_area_workflow',
        spy,
    ):
        await fill_area(
            gis_call=gis.fill,
            scope_call=gis.scope,
            fold_call=gis.fold,
            member_fill=fill,
            licence_ids=[number],
            calculation_crs='EPSG:32642',
            object_name='Тенгкели-Березовская площадь',
        )

    assert seen['calculation_crs'] == 'EPSG:32642'
    assert seen['project_id'] == 'p1'
    assert seen['area_display_name'] == 'Тенгкели-Березовская площадь'


@pytest.mark.asyncio
async def test_the_area_s_own_line_reaches_the_emitter():
    """`fill_area` emits the area's member-count status line at the start and
    at the end of the work."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})
    seen = []

    async def emitter(event):
        seen.append(event)

    await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        calculation_crs='EPSG:32642',
        event_emitter=emitter,
    )

    lines = [
        event['data']['description']
        for event in seen
        if event.get('type') == 'status'
        and str(event['data'].get('description') or '').startswith('Площадь:')
    ]
    assert lines, seen
    assert lines[0] == 'Площадь: 1 участник · заполняется 0 · готово 0 · ожидают 1'
    assert lines[-1] == 'Площадь: 1 участник · заполняется 0 · готово 1 · ожидают 0'


@pytest.mark.asyncio
async def test_no_emitter_leaves_the_area_working_and_silent():
    """`fill_area` works without an event emitter."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        calculation_crs='EPSG:32642',
    )

    assert answer['result']['counts']['members'] == 1


def test_a_multi_zone_answer_says_how_many_zones():
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'p.v1', 'source': 'supplied'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'spans_several_zones': True,
            'zones_spanned': ['EPSG:32656', 'EPSG:32657'],
        },
    })

    assert '2 зоны' in line
    assert 'EPSG:32657' in line


@pytest.mark.asyncio
async def test_a_name_matching_several_asks_and_says_what_all_of_them_costs():
    """A name matching several candidates asks a question listing each one and
    the cost of filling all of them."""
    gis = registry(**{
        'Лекын-Тальбейская площадь': [
            project_match('p1', 'Лекын-Тальбейское'),
            project_match('p2', 'Восточно-Лекынское'),
            project_match('p3', ''),
        ]
    })

    answer = await resolve_area_members(
        gis_call=gis.fill, object_name='Лекын-Тальбейская площадь'
    )

    assert answer['status'] == ASK
    question = answer['question']
    assert 'найдено 3 лицензии' in question
    for project in ('p1', 'p2', 'p3'):
        assert project in question
    assert 'p1 — Лекын-Тальбейское' in question
    assert 'p3 — ' not in question
    assert '3 участника, примерно 8 часов' in question


@pytest.mark.asyncio
async def test_seven_members_are_accepted_and_the_cost_is_stated():
    """Seven members are accepted and the cost notice states their count and
    hours."""
    numbers = [f'X{i:05d}БЭ' for i in range(7)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 7
    assert '7 участников, примерно 18 часов' in answer['cost_notice']


@pytest.mark.asyncio
async def test_twenty_one_members_are_accepted_too():
    """Twenty-one members are accepted and the cost notice states their count
    and hours."""
    numbers = [f'X{i:05d}БЭ' for i in range(21)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 21
    assert '21 участник, примерно 55 часов' in answer['cost_notice']


@pytest.mark.asyncio
async def test_the_rendered_answer_opens_with_what_the_run_cost():
    """`render_area_answer` opens with the cost notice."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=fill, licence_ids=[number], calculation_crs=CRS,
    )
    rendered = render_area_answer(answer)

    assert rendered.startswith('1 участник, примерно 3 часа')
    assert 'продолжат заполняться' in rendered


def test_a_layer_this_tool_has_no_word_for_says_so():
    """A layer with no known state is listed as «состояние не определено» on
    its own line."""
    message = ambiguous_licence('МАГ04805БЭ', [
        licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence('МАГ04805БЭ', project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ])

    assert 'Licenses_2024_2025' in message and 'действующие' in message
    assert 'Sint_licences_2025exp_clp' in message
    assert 'состояние не определено' in message
    known, unknown = [
        line for line in message.splitlines() if 'Licenses_2024_2025' in line
    ][0], [
        line for line in message.splitlines() if 'Sint_licences' in line
    ][0]
    assert 'действующие' in known and 'состояние не определено' not in known
    assert 'состояние не определено' in unknown


def test_the_notice_says_the_request_ends_before_the_work_does():
    """`cost_notice` states the duration, that the request ends first, and that
    the members keep filling, without reading as a refusal."""
    notice = cost_notice(7)

    assert '7 участников, примерно 18 часов' in notice
    assert 'прервётся раньше' in notice
    assert 'продолжат заполняться' in notice
    assert 'Свод по площади соберётся' in notice
    assert 'не поддерживается' not in notice
    assert 'предел' not in notice


@pytest.mark.asyncio
async def test_neither_contract_field_has_to_be_supplied_any_more():
    """With neither contract field supplied, `fill_area` resolves both, names
    them, and sends them to the scope call."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )

    assert answer['status'] == RESOLVED
    contract = answer['contract']
    assert contract['policy_version'] == {
        'value': 'geotizer_area_aggregation.v1',
        'source': 'resolved',
    }
    assert contract['calculation_crs']['value'] == 'EPSG:32656'
    assert contract['calculation_crs']['source'] == 'resolved'
    assert gis.scope_payload['policy_version'] == 'geotizer_area_aggregation.v1'
    assert gis.scope_payload['calculation_crs'] == 'EPSG:32656'


@pytest.mark.asyncio
async def test_a_supplied_value_is_used_and_never_overridden():
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        policy_version='geotizer_area_aggregation.v1',
        calculation_crs='EPSG:32642',
    )

    contract = answer['contract']
    assert contract['calculation_crs'] == {
        'value': 'EPSG:32642',
        'source': 'supplied',
    }
    assert contract['policy_version']['source'] == 'supplied'
    assert gis.scope_payload['calculation_crs'] == 'EPSG:32642'


@pytest.mark.asyncio
async def test_a_member_whose_geometry_will_not_read_refuses_by_name():
    """A member without a centroid refuses on `calculation_crs` alone, without
    mentioning `policy_version`."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number, centroid=None)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert 'policy_version' not in answer['message']
    assert 'центроид' in answer['message']


@pytest.mark.asyncio
async def test_a_geographic_crs_is_refused_rather_than_replaced():
    """A supplied geographic CRS is refused, not replaced."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        calculation_crs='EPSG:4326',
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert 'EPSG:4326' in answer['message']


@pytest.mark.asyncio
async def test_a_three_member_area_fills_folds_and_summarises():
    """A three-member area with one failure fills, folds the failure as
    `member_run_failed`, and renders the summary."""
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
    assert gis.fold_payload['scope']['area_id'] == 'area-lekyn'
    assert gis.fold_payload['policy_version'] == POLICY

    rendered = render_area_answer(answer)
    assert 'run-МАГ03394БЭ' in rendered
    assert 'не заполнен' in rendered
    assert 'Свод площади' in rendered


@pytest.mark.asyncio
async def test_each_service_call_goes_to_the_operation_that_declares_it():
    """`fill_area` sends `resolve_area_scope` and `fold_area` to their own
    operations."""
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

    assert gis.scope_payload['action'] == 'resolve_area_scope'
    assert gis.fold_payload['action'] == 'fold_area'


@pytest.mark.asyncio
async def test_sending_an_area_action_to_the_fill_operation_is_refused():
    """`Service.fill` rejects an area action."""
    gis = registry()

    with pytest.raises(AssertionError, match='geotizer_fill has no action'):
        await gis.fill({'action': 'fold_area'})


@pytest.mark.asyncio
async def test_nothing_to_resolve_is_its_own_refusal():
    """Neither a name nor numbers is refused with `NOTHING_TO_RESOLVE`."""
    answer = await resolve_area_members(gis_call=registry().fill)

    assert answer['status'] == REFUSED
    assert answer['reason'] == NOTHING_TO_RESOLVE


@pytest.mark.asyncio
async def test_a_search_answer_that_is_not_one_does_not_become_not_found():
    """A reply without `scope_resolution` is refused as `SEARCH_UNREADABLE`,
    not as not found."""
    class Mute:
        async def fill(self, payload):
            return {'detail': 'Internal Server Error'}

    answer = await resolve_area_members(
        gis_call=Mute().fill, licence_ids=['МАГ03394БЭ']
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SEARCH_UNREADABLE
    assert 'не найдена' not in answer['message'].replace('«Не найдена» о ней не утверждается', '')


@pytest.mark.asyncio
async def test_a_manifest_that_lost_its_members_is_not_an_area_of_none():
    """An empty manifest is refused with `MANIFEST_WITHOUT_MEMBERS`."""
    numbers = ['МАГ03394БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def empty_scope(payload):
        return {'area_scope_id': payload['area_scope_id'], 'entities': [], 'relations': []}

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=empty_scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == MANIFEST_WITHOUT_MEMBERS


@pytest.mark.asyncio
async def test_a_fold_that_fails_keeps_every_member_that_was_filled():
    """A failed fold keeps the filled members and states `fold_failed` in place
    of a summary."""
    numbers = ['МАГ03394БЭ', 'АНД01313БП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def refusing_fold(payload):
        raise RuntimeError('422: policy_version mismatch')

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=refusing_fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    result = answer['result']
    assert result['counts']['filled'] == 2
    assert result['aggregation']['reason'] == 'fold_failed'
    assert 'summary' not in result

    rendered = render_area_answer(answer)
    assert 'Свод не построен: fold_failed' in rendered
    assert 'run-МАГ03394БЭ' in rendered


@pytest.mark.asyncio
async def test_a_fold_that_answers_without_an_aggregation_has_not_folded():
    """A fold reply without an aggregation is recorded as `not_performed` with
    `fold_failed`."""
    numbers = ['МАГ03394БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def hollow_fold(payload):
        return {'policy_version': POLICY}

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=hollow_fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    assert answer['result']['aggregation']['state'] == 'not_performed'
    assert answer['result']['aggregation']['reason'] == 'fold_failed'


def test_a_bad_deadline_valve_does_not_take_the_tool_down():
    """`area_deadline_seconds` returns None for an invalid value and the number
    for a valid one."""
    for bad in ('abc', '-5', '0', 'NaN-ish'):
        seconds, note = area_deadline_seconds(bad)
        assert seconds is None, bad

    assert area_deadline_seconds(str(6 * 2.6 * 3600)) == (6 * 2.6 * 3600, None)
    assert area_deadline_seconds(6 * 2.6 * 3600) == (6 * 2.6 * 3600, None)


def test_a_refused_valve_says_so_and_an_unset_one_stays_quiet():
    """An invalid deadline valve returns a note naming the variable and the
    value; an unset one returns no note."""
    for bad in ('abc', '-5', '0', 'NaN-ish', '3600s'):
        seconds, note = area_deadline_seconds(bad)
        assert seconds is None, bad
        assert note, bad
        assert repr(bad) in note, bad
        assert 'GEOMAS_AREA_DEADLINE_SECONDS' in note, bad

    for quiet in (None, ''):
        assert area_deadline_seconds(quiet) == (None, None), quiet


def test_no_valve_is_no_bound_and_not_a_bound_of_zero():
    """An unset or zero deadline valve means no deadline."""
    assert area_deadline_seconds(None)[0] is None
    assert area_deadline_seconds('0')[0] is None


TOOL_SOURCE = (
    Path(__file__).resolve().parents[1]
    / 'open_webui'
    / 'tools'
    / 'geotizer.py'
)


def _call_keywords(function_name: str, call_name: str) -> dict[str, str]:
    """Every keyword of `call_name(...)` inside `def function_name`, unparsed."""
    tree = ast.parse(TOOL_SOURCE.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Name) and func.id == call_name:
                return {
                    kw.arg: ast.unparse(kw.value)
                    for kw in call.keywords
                    if kw.arg
                }
    raise AssertionError(f'no {call_name}(...) call inside {function_name}')


def test_an_area_member_fill_is_given_the_event_emitter():
    """`fill_geoteaser_area` passes `__event_emitter__` to the member fill, as
    `fill_geotizer` does to its run."""
    keywords = _call_keywords('fill_geoteaser_area', 'member_filler')

    assert keywords.get('event_emitter') == '__event_emitter__', keywords

    assert _call_keywords('fill_geotizer', 'run_geotizer_workflow').get(
        'event_emitter'
    ) == '__event_emitter__'


def test_the_areas_own_line_is_wired_from_the_tool_into_the_fill():
    """`fill_geoteaser_area` passes the event emitter and the `status` settings
    to `fill_area`."""
    keywords = _call_keywords('fill_geoteaser_area', 'fill_area')

    assert keywords.get('event_emitter') == '__event_emitter__', keywords
    assert keywords.get('status') == 'status', keywords


def test_a_refused_deadline_valve_reaches_the_answer_a_user_reads():
    """`render_area_answer` prints the deadline valve note beside the cost
    notice."""
    answer = render_area_answer(
        {
            'status': RESOLVED,
            'cost_notice': 'стоимость',
            'area_deadline_note': 'GEOMAS_AREA_DEADLINE_SECONDS=\'3600s\' — не число;',
            'result': {
                'area_id': 'area:x',
                'counts': {'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0},
                'members': [],
                'aggregation': {},
            },
        }
    )

    assert 'GEOMAS_AREA_DEADLINE_SECONDS' in answer
    assert 'стоимость' in answer


def test_an_answer_with_a_usable_valve_says_nothing_about_it():
    """`render_area_answer` prints no valve note when none is given."""
    answer = render_area_answer(
        {
            'status': RESOLVED,
            'cost_notice': 'стоимость',
            'result': {
                'area_id': 'area:x',
                'counts': {'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0},
                'members': [],
                'aggregation': {},
            },
        }
    )

    assert 'GEOMAS_AREA_DEADLINE_SECONDS' not in answer


def test_a_failed_member_is_listed_with_the_run_that_holds_its_work():
    """`_member_line` lists a failed member with its run id and error."""
    line = _member_line(
        {
            'object_name': 'Нявленга',
            'state': 'failed',
            'error': 'RuntimeError: gis refused',
            'run_id': 'run-nyavlenga',
        }
    )

    assert 'run-nyavlenga' in line
    assert 'RuntimeError: gis refused' in line


def test_a_member_that_failed_before_a_run_existed_offers_no_handle():
    """`_member_line` prints no backticks for a failed member without a run id."""
    line = _member_line(
        {
            'object_name': 'Нявленга',
            'state': 'failed',
            'error': 'RuntimeError: refused at the door',
        }
    )

    assert '`' not in line
    assert 'RuntimeError: refused at the door' in line


@pytest.mark.asyncio
async def test_a_mistyped_project_id_never_becomes_a_filled_member():
    """A `project_id` matching no project is refused with `PROJECT_NOT_FOUND`,
    naming it and the known projects."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [licence(number, project='OnlyProject')]})

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='TYPO-project-id-that-does-not-exist',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND
    assert 'не найдена' not in answer['message']
    assert 'TYPO-project-id-that-does-not-exist' in answer['message']
    assert 'OnlyProject' in answer['message']


@pytest.mark.asyncio
async def test_a_mistyped_project_id_is_not_reported_as_an_ambiguous_licence():
    """A mistyped `project_id` with two known projects is refused with
    `PROJECT_NOT_FOUND`, not as an ambiguous licence."""
    number = 'МАГ04805БЭ'
    gis = registry(
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'GIS_Data_RF'},
            {
                'project_id': 'Тенгкели-Березовская площадь',
                'name': 'Тенгкели-Березовская площадь',
            },
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Совершенно другой проект XYZ 12345',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND
    assert answer['reason'] != LICENCE_AMBIGUOUS
    assert 'найдена 2 раз' not in answer['message']
    assert 'Совершенно другой проект XYZ 12345' in answer['message']


@pytest.mark.asyncio
async def test_a_name_search_with_a_mistyped_project_id_refuses_the_same_way():
    """A name search with a mistyped `project_id` is refused with
    `PROJECT_NOT_FOUND`."""
    gis = registry(
        projects=[{'project_id': 'p1', 'name': 'Первый проект'}],
        **{'Лекын-Тальбейская площадь': [project_match('p1', 'Лекын-Тальбейское')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        object_name='Лекын-Тальбейская площадь',
        project_id='нет такого проекта',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND


@pytest.mark.asyncio
async def test_a_licence_that_does_not_exist_anywhere_is_still_not_found():
    """An unscoped number that exists nowhere is refused as not found rather
    than filled from the suggested projects."""
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='OnlyProject')]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'НЕТ00000БЭ' in answer['message']


@pytest.mark.asyncio
async def test_a_project_named_by_its_human_name_scopes_the_search_too():
    """A `project_id` given as the project's name scopes the search to that
    project's id."""
    number = 'МАГ04805БЭ'
    gis = registry(
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'Единый реестр лицензий РФ'},
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Единый реестр лицензий РФ',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'GIS_Data_RF'


def test_the_area_deadline_valve_is_read_and_judged_before_the_workflow():
    """The adapter reads the deadline valve once through
    `area_deadline_seconds` and passes both the value and the note to
    `fill_area`."""
    source = TOOL_SOURCE.read_text(encoding='utf-8')

    assert 'return area_deadline_seconds(' in source

    keywords = _call_keywords('fill_geoteaser_area', 'fill_area')
    assert keywords.get('area_deadline_seconds') == 'area_deadline'
    assert keywords.get('area_deadline_note') == "area_deadline_note or ''"

    tree = ast.parse(source)
    unpacked = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and 'area_deadline' in ast.unparse(node)
        and '_area_deadline_seconds()' in ast.unparse(node)
    ]
    assert unpacked == [
        'area_deadline, area_deadline_note = _area_deadline_seconds()'
    ], unpacked


TENGKELI = 'Тенгкели-Березовская площадь'


def _both_projects(number):
    """Return the licence's rows in `GIS_Data_RF` and in `TENGKELI`."""
    return [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]


@pytest.mark.asyncio
async def test_a_named_project_is_honoured_even_when_the_search_ignores_it():
    """A named project is applied to the search answer when the service ignores
    `project_id`."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 1
    member = answer['members'][0]
    assert member['project_id'] == TENGKELI
    assert member['licence_layer_id'] == 'Sint_licences_2025exp_clp'


@pytest.mark.asyncio
async def test_the_registry_is_never_a_candidate_beside_a_named_project():
    """`GIS_Data_RF` rows are dropped when the caller named another project."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert [m['project_id'] for m in answer['members']] == [TENGKELI]
    assert 'GIS_Data_RF' not in [m['project_id'] for m in answer['members']]


@pytest.mark.asyncio
async def test_the_gate_applies_to_every_member_and_not_once_per_call():
    """The named project is sent with, and applied to, every member's search."""
    numbers = ['МАГ04805БЭ', 'МАГ05018БР', 'МАГ05252БР']
    gis = registry(
        scopes=False, **{number: _both_projects(number) for number in numbers}
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=numbers, project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert [m['project_id'] for m in answer['members']] == [TENGKELI] * 3
    assert [m['licence_id'] for m in answer['members']] == numbers
    assert len(gis.scope_queries) == 3
    assert all(q.get('project_id') == TENGKELI for q in gis.scope_queries)


@pytest.mark.asyncio
async def test_two_layers_of_one_project_still_refuses_after_the_gate():
    """Two layers within the named project are still refused as states of one
    licence."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: [
        licence(number, project=TENGKELI, layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Licenses_annul'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'Строки из разных проектов' not in answer['message']
    assert 'состояния одной лицензии' in answer['message']


@pytest.mark.asyncio
async def test_without_a_project_the_cross_project_ambiguity_is_unchanged():
    """Without a `project_id` the cross-project ambiguity refusal is unchanged."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'Строки из разных проектов' in answer['message']


def test_the_four_received_states_read_as_the_task_wrote_them():
    """`received_line` renders each argument state in its fixed wording."""
    assert received_line('project_id', '', ARG_NOT_PASSED) == 'project_id: (не передан)'
    assert received_line('project_id', TENGKELI, ARG_NOT_FOUND) == (
        f"project_id: '{TENGKELI}' — не найден среди проектов"
    )
    assert received_line('project_id', TENGKELI, ARG_ACCEPTED) == (
        f"project_id: '{TENGKELI}' — принят"
    )
    assert 'сервис его не применил' in received_line(
        'project_id', TENGKELI, ARG_NOT_HONOURED
    )


def test_an_unknown_received_state_raises_rather_than_picking_a_wording():
    """`received_line` raises ValueError on an unknown state."""
    with pytest.raises(ValueError):
        received_line('project_id', 'x', 'probably_fine')


@pytest.mark.asyncio
async def test_the_ambiguity_that_asks_for_a_project_says_what_it_received():
    """The ambiguity refusal that asks for `project_id` echoes that none was
    passed."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert 'project_id: (не передан)' in answer['message']


@pytest.mark.asyncio
async def test_an_accepted_project_is_echoed_on_the_refusal_that_remains():
    """A refusal after an accepted `project_id` echoes it as «принят»."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project=TENGKELI, layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Licenses_annul'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert f"project_id: '{TENGKELI}' — принят" in answer['message']


@pytest.mark.asyncio
async def test_a_project_the_search_dropped_and_no_row_carries_is_its_own_refusal():
    """A `project_id` the search ignored and no returned row carries is refused
    with `SCOPE_NOT_APPLIED`, listing the projects offered."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number],
        project_id='Единый реестр лицензий РФ',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_NOT_APPLIED
    assert 'сервис его не применил' in answer['message']
    assert 'не найдена' not in answer['message']
    assert sorted(answer['projects_offered']) == ['GIS_Data_RF', TENGKELI]


@pytest.mark.asyncio
async def test_one_project_in_the_answer_is_never_narrowed_here():
    """An unscoped answer holding only the named project resolves to it."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: [
        licence(number, project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == TENGKELI


def _fixed(rows, *, claims_scope=False):
    """Return a search that answers `rows` whatever it is asked, claiming
    `scoped_to_project` when `claims_scope` is set."""
    async def call(payload):
        resolution = {'candidates': list(rows), 'searched_projects': 49026}
        scope = str(payload.get('project_id') or '').strip()
        if scope and claims_scope:
            resolution['scoped_to_project'] = scope
            resolution['searched_projects'] = 1
        return {'workflow_status': 'ok', 'scope_resolution': resolution}
    return call


@pytest.mark.asyncio
async def test_one_row_from_a_project_the_caller_did_not_name_is_refused():
    """A single row from a project the caller did not name is refused with
    `SCOPE_NOT_APPLIED`."""
    rows = [licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025')]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_NOT_APPLIED
    assert 'GIS_Data_RF' in answer['message']


@pytest.mark.asyncio
async def test_a_claimed_scope_carrying_foreign_rows_is_not_believed():
    """A claimed `scoped_to_project` carrying foreign rows is confined to the
    named project and not echoed as «принят»."""
    rows = [
        licence('МАГ04805БЭ', project=TENGKELI, layer='Sint_licences_2025exp_clp'),
        licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025'),
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows, claims_scope=True),
        licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == TENGKELI
    assert 'принят' not in answer['scope_notice']


@pytest.mark.asyncio
async def test_two_project_ids_differing_only_in_case_are_several_not_one():
    """Two project ids that differ only in case are refused with
    `SCOPE_AMBIGUOUS`."""
    rows = [
        licence('МАГ04805БЭ', project='Project1', layer='L1'),
        licence('МАГ04805БЭ', project='PROJECT1', layer='L2'),
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id='project1',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_AMBIGUOUS
    assert sorted(answer['matched_project_ids']) == ['PROJECT1', 'Project1']
    assert 'Строки из разных проектов' not in answer['message']


@pytest.mark.asyncio
async def test_a_row_that_names_no_project_is_refused_rather_than_taken():
    """A row with no `project_id` is refused with `SCOPE_UNVERIFIABLE`."""
    rows = [{'licence_id': 'МАГ04805БЭ', 'licence_layer_id': 'L1',
             'centroid_lon': 150.8, 'centroid_lat': 61.6}]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_UNVERIFIABLE
    assert answer['rows_without_project'] == 1


@pytest.mark.asyncio
async def test_a_blank_project_beside_a_named_one_is_not_two_states_of_one_licence():
    """A blank-project row beside a named-project row is refused with
    `SCOPE_UNVERIFIABLE`, not as two states of one licence."""
    rows = [
        licence('МАГ04805БЭ', project=TENGKELI, layer='L1'),
        {'licence_id': 'МАГ04805БЭ', 'licence_layer_id': 'L2',
         'centroid_lon': 150.8, 'centroid_lat': 61.6},
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_UNVERIFIABLE
    assert 'состояния одной лицензии' not in answer['message']


@pytest.mark.asyncio
async def test_nothing_found_anywhere_does_not_claim_rows_from_other_projects():
    """A scoped search that returned no rows does not claim rows from other
    projects."""
    gis = registry(scopes=False, **{'МАГ04805БЭ': [
        licence('МАГ04805БЭ', project=TENGKELI, layer='L1')]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'строки из других проектов' not in answer['message']
    assert 'сужение по нему сервис не подтвердил' in answer['message']


@pytest.mark.asyncio
async def test_the_not_found_refusal_carries_the_echo_for_a_caller_with_no_project():
    """The not-found refusal echoes that no `project_id` was passed."""
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='p1')]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'])

    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'project_id: (не передан)' in answer['message']


@pytest.mark.asyncio
async def test_a_project_that_does_not_exist_echoes_not_found_at_the_refusal():
    """The project-not-found refusal echoes the `project_id` as not found among
    the projects."""
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='p1')]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ04805БЭ'], project_id='нет такого',
    )

    assert answer['reason'] == PROJECT_NOT_FOUND
    assert "project_id: 'нет такого' — не найден среди проектов" in answer['message']


@pytest.mark.asyncio
async def test_a_name_search_with_a_project_the_service_ignored_is_scoped_too():
    """A name search with a `project_id` the service ignored is confined to
    that project."""
    gis = registry(
        scopes=False,
        **{'Лекын': [project_match('p1', 'Лекын-Тальбейское'),
                     project_match('GIS_Data_RF', 'Реестр')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, object_name='Лекын', project_id='p1',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'p1'


@pytest.mark.asyncio
async def test_a_rescued_run_says_so_on_the_success_it_produces():
    """A resolved area whose scope was applied on the caller's side carries a
    `scope_notice`, and the rendered answer prints it."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert number in answer['scope_notice']
    assert 'компенсация' in answer['scope_notice']
    rendered = render_area_answer({
        'status': RESOLVED, 'cost_notice': answer['cost_notice'],
        'scope_notice': answer['scope_notice'],
        'result': {'area_id': 'a', 'counts': {'members': 1, 'filled': 1,
                   'failed': 0, 'not_attempted': 0}, 'members': [],
                   'aggregation': {}},
    })
    assert 'компенсация' in rendered


@pytest.mark.asyncio
async def test_a_run_the_service_scoped_itself_carries_no_rescue_notice():
    """A resolved area scoped by the service carries no `scope_notice`."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert 'scope_notice' not in answer


def test_the_echo_never_raises_for_any_shape_the_search_can_produce():
    """`_scope_echo` returns a line for every argument state and for an empty
    resolution."""
    for state in (ARG_NOT_PASSED, ARG_NOT_FOUND, ARG_ACCEPTED,
                  ARG_NOT_CONFIRMED, ARG_NOT_HONOURED):
        assert _scope_echo({'project_id_received': 'x', 'project_id_state': state})
    assert _scope_echo({}) == 'project_id: (не передан)'


def test_a_policy_version_nobody_has_is_refused_and_names_both_values():
    """An unknown `policy_version` is refused with `POLICY_VERSION_UNKNOWN`,
    naming the sent and the current value."""
    contract = resolve_contract(
        policy_version='2024', calculation_crs=CRS, members=[],
    )

    assert contract['status'] == REFUSED
    assert contract['reason'] == POLICY_VERSION_UNKNOWN
    assert contract['failed'] == 'policy_version'
    assert '`2024`' in contract['message']
    assert POLICY in contract['message']
    assert 'Не указывайте `policy_version`' in contract['message']


def test_the_one_policy_that_exists_is_accepted_as_supplied():
    """The current policy version supplied by the caller is accepted with
    source `supplied`."""
    contract = resolve_contract(
        policy_version=POLICY, calculation_crs=CRS, members=[],
    )

    assert contract['status'] == RESOLVED
    assert contract['policy_version'] == {'value': POLICY, 'source': 'supplied'}


def test_an_absent_policy_still_resolves_to_the_current_one():
    """An absent `policy_version` resolves to the current policy."""
    contract = resolve_contract(
        policy_version='', calculation_crs=CRS, members=[],
    )

    assert contract['status'] == RESOLVED
    assert contract['policy_version']['value'] == POLICY
    assert contract['policy_version']['source'] == 'resolved'


@pytest.mark.asyncio
async def test_a_guessed_policy_refuses_the_area_before_anything_is_filled():
    """An unknown `policy_version` refuses the area before anything is folded."""
    numbers = ['МАГ04805БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=fill, licence_ids=numbers,
        policy_version='2024', calculation_crs=CRS,
        area_scope_id='area-x', dossier_run_id='dossier-1',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == POLICY_VERSION_UNKNOWN
    assert gis.fold_payload is None, 'nothing may be folded under a policy nobody has'


def test_the_zero_member_summary_points_at_the_reasons_above_it():
    """A zero-member summary reports `nothing_filled` and points to the per-
    member reasons."""
    rendered = render_area_answer({
        'status': RESOLVED,
        'result': {
            'area_id': 'area-x',
            'counts': {'members': 3, 'filled': 0, 'failed': 3, 'not_attempted': 0},
            'members': [],
            'aggregation': {
                'state': 'not_performed',
                'reason': 'nothing_filled',
                'members_total': 3,
                'members_filled': 0,
            },
        },
    })

    assert 'ни один участник не заполнен (0 из 3)' in rendered
    assert 'Причины по участникам — выше.' in rendered
    assert 'fold_failed' not in rendered


@pytest.mark.asyncio
async def test_one_member_fills_end_to_end_with_its_own_licence():
    """A one-member area fills end to end, launching the member fill by licence
    with an empty `object_name`."""
    seen = {}

    async def member_fill(*, object_name, project_id=None, licence_id=None,
                          licence_layer_id=None, **_):
        seen.update({
            'object_name': object_name, 'project_id': project_id,
            'licence_id': licence_id, 'licence_layer_id': licence_layer_id,
        })
        return {
            'run_id': f'run-{licence_id}', 'status': 'finalized',
            'audit': {'completeness': {'filled': 196, 'of': 351}},
        }

    gis = registry(**{'МАГ04805БЭ': [
        licence('МАГ04805БЭ', project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=member_fill, licence_ids=['МАГ04805БЭ'],
        project_id=TENGKELI, calculation_crs=CRS,
        area_scope_id='area-tengkeli', dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    assert seen['licence_id'] == 'МАГ04805БЭ'
    assert seen['licence_layer_id'] == 'Sint_licences_2025exp_clp'
    assert seen['project_id'] == TENGKELI
    assert seen['object_name'] == ''
    result = answer['result']
    assert result['counts'] == {
        'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0,
    }
    rendered = render_area_answer(answer)
    assert 'run-МАГ04805БЭ' in rendered
    assert 'МАГ04805БЭ — заполнен' in rendered


@pytest.mark.asyncio
async def test_an_area_where_every_member_fails_says_so_from_end_to_end():
    """An area whose every member fails reports `nothing_filled`, folds
    nothing, and renders the member reasons above the summary."""
    numbers = ['МАГ04805БЭ', 'МАГ05018БР']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def always_fails(**kwargs):
        raise RuntimeError('specialist timeout')

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=always_fails, licence_ids=numbers,
        calculation_crs=CRS, area_scope_id='area-x', dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    aggregation = answer['result']['aggregation']
    assert aggregation['reason'] == 'nothing_filled'
    assert aggregation['members_total'] == 2
    assert gis.fold_payload is None

    rendered = render_area_answer(answer)
    assert 'ни один участник не заполнен (0 из 2)' in rendered
    assert 'Причины по участникам — выше.' in rendered
    assert rendered.index('МАГ04805БЭ') < rendered.index('Свод не построен')


@pytest.mark.asyncio
async def test_a_member_is_named_by_its_licence_and_not_by_its_dossier_id():
    """A licence candidate's member is named by its licence number."""
    rows = [{
        'project_id': 'p1', 'licence_id': 'МАГ04805БЭ',
        'licence_layer_id': 'L1', 'centroid_lon': 150.8, 'centroid_lat': 61.6,
    }]

    async def search(payload):
        return {'workflow_status': 'ok',
                'scope_resolution': {'candidates': rows, 'searched_projects': 1}}

    resolved = await resolve_area_members(gis_call=search, licence_ids=['МАГ04805БЭ'])
    member = resolved['members'][0]

    assert member['object_name'] == 'МАГ04805БЭ'
    assert member['licence_id'] == 'МАГ04805БЭ'


def test_the_adapter_forwards_the_policy_the_caller_named():
    """`fill_geoteaser_area` forwards `policy_version`, `licence_ids` and
    `calculation_crs` to `fill_area`."""
    keywords = _call_keywords('fill_geoteaser_area', 'fill_area')

    assert keywords.get('policy_version') == 'policy_version.strip()'
    assert keywords.get('licence_ids') == 'licence_ids or ()'
    assert keywords.get('calculation_crs') == 'calculation_crs.strip()'
