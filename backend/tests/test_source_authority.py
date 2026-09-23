"""Tests for the source-authority rules the conflict resolver and the owner-envelope repairs apply to cell values."""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
from open_webui.services.project_evidence.proposals import (
    PRIMARY_SOURCE_TYPES,
    WEB_SOURCE_TYPES,
    resolve_by_source_authority,
)

SOURCES = {
    'gis-1': {'source_type': 'gis'},
    'kb-1': {'source_type': 'knowledge_base'},
    'dc-1': {'source_type': 'datacube'},
    'web-1': {'source_type': 'web'},
    'web-2': {'source_type': 'web'},
    'derived-1': {'source_type': 'derived'},
    'unknown-1': {},
}


def _candidate(ref, value):
    return {'source_ref': ref, 'value': value, 'unit': 'т', 'value_origin': 'direct'}


@pytest.mark.parametrize('primary', ['gis-1', 'kb-1', 'dc-1'])
def test_a_primary_source_beats_a_web_snippet(primary):
    """A primary source wins a conflict against a web source."""
    winner, trace = resolve_by_source_authority(
        [_candidate(primary, 'primary'), _candidate('web-1', 'snippet')], SOURCES
    )

    assert winner['value'] == 'primary'
    assert 'WEB' in trace


def test_two_primaries_are_left_to_a_person():
    """Two primary sources in conflict produce no winner."""
    winner, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('kb-1', 'b')], SOURCES
    )

    assert winner is None


def test_two_web_snippets_are_left_to_a_person():
    winner, trace = resolve_by_source_authority(
        [_candidate('web-1', 'a'), _candidate('web-2', 'b')], SOURCES
    )

    assert winner is None
    assert 'WEB' in trace


@pytest.mark.parametrize('ref', ['derived-1', 'unknown-1'])
def test_a_source_of_unknown_rank_stops_the_rule(ref):
    """A `derived` or unregistered source stops the rule, with or without a web side present."""
    assert resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate(ref, 'b')], SOURCES
    )[0] is None

    assert resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate(ref, 'b'), _candidate('web-1', 'c')], SOURCES
    )[0] is None


def test_two_primaries_against_a_web_source_still_stand():
    """The web value losing does not make the two primaries agree."""
    winner, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('kb-1', 'b'), _candidate('web-1', 'c')], SOURCES
    )

    assert winner is None
    assert 'экспертом' in trace


def test_one_primary_beats_several_web_sources():
    winner, trace = resolve_by_source_authority(
        [_candidate('kb-1', 'doc'), _candidate('web-1', 'x'), _candidate('web-2', 'y')], SOURCES
    )

    assert winner['value'] == 'doc'
    assert '2 WEB' in trace


def test_a_single_candidate_is_not_a_conflict():
    assert resolve_by_source_authority([_candidate('web-1', 'a')], SOURCES) == (None, '')


def test_every_outcome_carries_a_reason_or_is_not_a_conflict():
    """Both a resolved and an unresolved conflict carry a non-empty trace."""
    resolved, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('web-1', 'b')], SOURCES
    )
    assert resolved is not None and trace

    unresolved, trace = resolve_by_source_authority(
        [_candidate('web-1', 'a'), _candidate('web-2', 'b')], SOURCES
    )
    assert unresolved is None and trace


def test_web_is_not_a_primary_source():
    """The web and primary source-type sets do not overlap."""
    assert not (WEB_SOURCE_TYPES & PRIMARY_SOURCE_TYPES)


def _resolver_fixture(owner_source_type, proposal_domain):
    """One owner patch and one contributor proposal that disagree."""
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 'owner-value',
            'unit': 'т',
            'status': 'filled',
            'value_origin': 'direct',
            'source_locator': {'page': 7},
            'source_refs': ['owner-src'],
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'owner-src',
            'source_type': owner_source_type,
            'title': 'Проект ГРР',
            'locator': 'стр. 7',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': 'contributor-value',
            'unit': 'т',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'contrib',
            'source_title': 'Пресс-релиз',
            'source_locator': {'collection_or_url': 'https://example.invalid/a'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [{'source_domain': proposal_domain, 'field_proposals': proposals}]


def _resolved_patch(owner_source_type, proposal_domain):
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _resolver_fixture(owner_source_type, proposal_domain)
    return apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]


def test_the_resolver_applies_the_hierarchy_when_a_document_meets_the_web():
    """A document owner value beats a web contributor, fills the cell, and keeps the rejected value in `candidates`."""
    patch = _resolved_patch('knowledge_base', 'web')

    assert patch['status'] == 'filled'
    assert patch['value'] == 'owner-value'
    assert patch['source_locator']['policy'] == 'resolved_by_source_authority'
    assert 'selection_trace' in patch['source_locator']
    values = [item['value'] for item in patch['source_locator']['candidates']]
    assert 'contributor-value' in values, 'the rejected value must survive the resolution'


def test_the_resolver_leaves_two_documents_conflicted():
    """Two documentary sources leave the cell conflicted."""
    patch = _resolved_patch('knowledge_base', 'kb')

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None
    assert patch['source_locator']['policy'] == 'direct_disagreement_is_conflicted'


def test_a_resolved_cell_keeps_both_source_refs():
    """A resolved cell keeps the source refs of both sides."""
    patch = _resolved_patch('gis', 'web')

    assert len(patch['source_refs']) == 2


def _negative_finding_fixture():
    """A GIS proposal reporting «Не выявлено» and a document proposal with a value for the same cell."""
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': None,
            'unit': None,
            'status': 'not_found',
            'value_origin': None,
            'source_locator': {'query': 'field f1'},
            'source_refs': ['s1'],
        }
    )
    gis = [
        {
            'field_key': 'f1',
            'value': 'Не выявлено',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'lekyn_layers',
            'source_title': 'layer inventory',
            'source_locator': {'layer_id': 'list_layers'},
            'retrieval_note': 'Layer inventory.',
        }
    ]
    document = [
        {
            'field_key': 'f1',
            'value': 'диориты, кварцевые диориты, плагиограниты',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'doc-115',
            'source_title': 'Отчёт',
            'source_locator': {'page': '115'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [
        {'source_domain': 'gis', 'field_proposals': gis},
        {'source_domain': 'kb', 'field_proposals': document},
    ]


def _negative_finding_patch():
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
        apply_structured_gis_field_proposals,
    )

    value, raw, evidence = _negative_finding_fixture()
    after = apply_structured_gis_field_proposals(value, raw, evidence)
    after = apply_structured_external_field_proposals(value, after, evidence)
    return after['patches'][0]


def test_a_source_that_found_nothing_does_not_disagree_with_one_that_did():
    """A negative finding does not conflict with a value, and the value fills the cell."""
    patch = _negative_finding_patch()

    assert patch['status'] == 'filled'
    assert patch['value'] == 'диориты, кварцевые диориты, плагиограниты'


def test_the_empty_search_is_still_on_the_record():
    """The negative finding is kept under `negative_findings`, not under `candidates`."""
    patch = _negative_finding_patch()
    locator = patch['source_locator']

    assert [item['value'] for item in locator['negative_findings']] == ['Не выявлено']
    assert locator['negative_findings'][0]['source_ref'] in patch['source_refs']
    assert 'candidates' not in locator


def _same_source_fixture(owner_value, owner_unit, proposal_value, proposal_unit):
    """One document read twice: the owner's patch and the same proposal."""
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': owner_value,
            'unit': owner_unit,
            'status': 'filled',
            'value_origin': 'direct',
            'source_locator': {'page': 127},
            'source_refs': ['vsluh-2007-07-03'],
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'vsluh-2007-07-03',
            'source_type': 'web',
            'title': 'vsluh.ru',
            'locator': 'стр. 127',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': proposal_value,
            'unit': proposal_unit,
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'vsluh-2007-07-03',
            'source_title': 'vsluh.ru',
            'source_locator': {'page': '127'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [{'source_domain': 'web', 'field_proposals': proposals}]


def _same_source_patch(owner_value, owner_unit, proposal_value, proposal_unit):
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _same_source_fixture(owner_value, owner_unit, proposal_value, proposal_unit)
    return apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]


@pytest.mark.parametrize(
    ('owner_value', 'owner_unit', 'proposal_value', 'proposal_unit'),
    (
        (830000, 'тонн меди', '830000', 'тонн меди'),
        ('1978', 'год', '1978', None),
        (1978, None, '1978', 'год'),
        ('медь', None, 'Медь', None),
        ('  Медно-Молибденовые  руды ', None, 'медно-молибденовые руды', None),
    ),
)
def test_one_figure_spelled_two_ways_is_not_a_disagreement(
    owner_value,
    owner_unit,
    proposal_value,
    proposal_unit,
):
    """Values differing only in JSON type, letter case, whitespace, or a unit one side omits do not conflict."""
    patch = _same_source_patch(owner_value, owner_unit, proposal_value, proposal_unit)

    assert patch['status'] == 'filled'
    assert patch['value'] == owner_value


def test_two_stated_units_still_disagree():
    """Two different stated units make a conflict."""
    patch = _same_source_patch(830000, 'тонн меди', 830000, 'тонн руды')

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None


def test_a_conflict_side_names_a_source_the_merged_state_holds():
    """After `merge_owner_envelopes`, each `candidates[].source_ref` names a source in the merged inventory."""
    from open_webui.services.artifacts.geotizer.owner_envelope import merge_owner_envelopes
    from test_geotizer_orchestration import batch

    chunk = {**batch(), 'fields': [{'field_key': 'f1', 'row_id': 1}]}
    envelope = {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 'doc-a', 'source_type': 'knowledge_base', 'title': 'A'},
            {'source_id': 'doc-b', 'source_type': 'web', 'title': 'B'},
        ],
        'patches': [
            {
                'field_key': 'f1',
                'value': None,
                'unit': None,
                'status': 'conflicted',
                'value_origin': None,
                'source_refs': ['doc-a', 'doc-b'],
                'source_locator': {
                    'policy': 'direct_disagreement_is_conflicted',
                    'candidates': [
                        {'value': 'a', 'unit': None, 'value_origin': 'direct', 'source_ref': 'doc-a', 'locator': {}},
                        {'value': 'b', 'unit': None, 'value_origin': 'direct', 'source_ref': 'doc-b', 'locator': {}},
                    ],
                },
            }
        ],
    }

    merged, _ = merge_owner_envelopes(chunk, [chunk], [envelope], run_id='r1')
    known = {source['source_id'] for source in merged['source_inventory']}
    sides = [item['source_ref'] for item in merged['patches'][0]['source_locator']['candidates']]

    assert sides == merged['patches'][0]['source_refs']
    assert set(sides) <= known


def _resource_envelope(source_type, field_key='geotizer_object.v1.r046.a01'):
    return {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 's1', 'source_type': source_type, 'title': 'источник'},
        ],
        'patches': [
            {
                'field_key': field_key,
                'value': '830000',
                'unit': 'тонн руды',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['s1'],
                'source_locator': {'page': 3},
                'retrieval_note': 'Пресс-релиз 2007 года.',
            }
        ],
    }


@pytest.mark.parametrize('field_key', (
    'geotizer_object.v1.r044.a01',
    'geotizer_object.v1.r046.a01',
    'geotizer_object.v1.r056.a03',
))
def test_a_resource_row_is_not_filled_by_a_lone_web_source(field_key):
    """A resource-row value cited only to web is refused to `requires_expert_review` under `LONE_WEB_RESOURCE_RULE`."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        LONE_WEB_RESOURCE_RULE,
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope('web', field_key))
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == LONE_WEB_RESOURCE_RULE
    assert 'WEB' in render_run_notes(notes)[0]


def test_the_refused_figure_stays_where_a_reader_can_see_it():
    """The refused lone-web resource value is kept in `candidates` with a trace naming WEB."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(_resource_envelope('web'))
    locator = repaired['patches'][0]['source_locator']

    assert [(item['value'], item['unit']) for item in locator['candidates']] == [('830000', 'тонн руды')]
    assert locator['candidates'][0]['source_ref'] == 's1'
    assert 'WEB' in locator['selection_trace']


@pytest.mark.parametrize('source_type', ('knowledge_base', 'gis', 'datacube'))
def test_a_resource_row_is_still_filled_by_a_document_or_a_layer(source_type):
    """A resource-row value from a document, GIS or datacube source stays filled."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope(source_type))

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


@pytest.mark.parametrize('field_key', (
    'geotizer_object.v1.r043.a01',
    'geotizer_object.v1.r057.a01',
    'geotizer_object.v1.r106.a02',
))
def test_a_lone_web_source_still_fills_outside_the_resource_rows(field_key):
    """A lone web source still fills rows outside the resource rows."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope('web', field_key))

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def test_the_hierarchy_is_not_inverted_by_a_measurement():
    """A calculated candidate does not outrank a documentary one in `resolve_by_source_authority`."""
    from open_webui.services.project_evidence.proposals import resolve_by_source_authority

    winner, trace = resolve_by_source_authority([_computed_distance(), _read_distance()], SOURCES)

    assert winner is None, 'a measurement must not outrank a document by itself'
    assert trace == ''


def _computed_distance():
    return {
        'source_ref': 'gis-1',
        'value': 151.2,
        'unit': 'км',
        'value_origin': 'calculated',
        'locator': {
            'operation': 'minimum_geometry_to_geometry',
            'calculation_crs': 'EPSG:32642',
            'raw_distance_m': 151200.0,
        },
    }


def _read_distance():
    return {
        'source_ref': 'kb-1',
        'value': 130,
        'unit': 'км',
        'value_origin': 'direct',
        'locator': {'page': '4', 'document_id': 'licence-appendix'},
    }


def test_a_measured_and_a_read_value_are_named_as_a_divergence():
    """`spatial_divergence` records a calculated and a read candidate as `computed_against_read`."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    record = spatial_divergence([_computed_distance(), _read_distance()])

    assert record['kind'] == 'computed_against_read'
    assert record['measured'][0]['value'] == 151.2
    assert record['measured'][0]['operation'] == 'minimum_geometry_to_geometry'
    assert record['read'][0]['value'] == 130


def test_a_pair_with_no_computation_is_not_a_spatial_divergence():
    """Two read candidates produce no spatial divergence."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    assert spatial_divergence([_read_distance(), {**_read_distance(), 'source_ref': 'dc-1'}]) is None


def test_two_computations_are_not_a_divergence_of_this_kind():
    """Two calculated candidates produce no spatial divergence."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    second = {**_computed_distance(), 'source_ref': 'dc-1', 'value': 148.9}

    assert spatial_divergence([_computed_distance(), second]) is None


def test_a_row_with_no_layer_to_measure_it_is_refused_not_cited():
    """A filled row the project has no layer for is refused under `ABSENT_SPATIAL_LAYER_RULE`, keeping its value in
    `candidates`.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        ABSENT_SPATIAL_LAYER_RULE,
        refuse_unanswerable_spatial_rows,
    )

    envelope = {
        'source_inventory': [{'source_id': 'kb-1', 'source_type': 'knowledge_base', 'title': 'Приложение'}],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'value': 130,
                'unit': 'км',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['kb-1'],
                'source_locator': {'page': '4'},
                'retrieval_note': 'Из приложения к лицензии.',
            }
        ],
    }
    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r078.a01',
            'roles': ['settlement'],
            'role_labels': ['населённый пункт'],
            'code': 'layer_not_found',
        }
    ]

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == ABSENT_SPATIAL_LAYER_RULE
    assert [item['value'] for item in patch['source_locator']['candidates']] == [130]
    assert 'населённый пункт' in patch['source_locator']['selection_trace']
    assert 'r078' in render_run_notes(notes)[0]


def test_a_row_whose_layer_exists_is_left_alone():
    """The refusal is keyed on the absent layer, not on the block."""
    from open_webui.services.artifacts.geotizer.owner_envelope import refuse_unanswerable_spatial_rows

    envelope = {
        'source_inventory': [],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'value': 'автомобильная дорога: 9.47 км',
                'unit': None,
                'status': 'filled',
                'value_origin': 'calculated',
                'source_refs': ['gis-1'],
                'source_locator': {'operation': 'minimum_geometry_to_geometry'},
            }
        ],
    }

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, [{'field_key': 'geotizer_object.v1.r078.a01'}])

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def _measured_patch_fixture():
    """A GIS-calculated owner patch and a documentary proposal for the same cell."""
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 'автомобильная дорога: автомобильная дорога row:17; 0.0 км',
            'unit': None,
            'status': 'filled',
            'value_origin': 'calculated',
            'source_refs': ['gis-measured'],
            'source_locator': {
                'operation': 'minimum_geometry_to_geometry',
                'calculation_crs': 'EPSG:32642',
                'raw_distance_m': 0.0,
                'semantic_role': 'road',
                'target_feature_id': 'row:17',
            },
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'gis-measured',
            'source_type': 'gis',
            'title': 'GIS infrastructure calculation: road',
            'locator': 'road row:17',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': 'п. Полярный',
            'unit': None,
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'grr-project',
            'source_title': 'Проект ГРР',
            'source_locator': {'page': 12, 'document_id': 'grr'},
            'retrieval_note': 'Прямая выгрузка из проекта ГРР: п. Полярный (60 км).',
        }
    ]
    return value, raw, [{'source_domain': 'kb', 'field_proposals': proposals}]


def _measured_patch_result():
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _measured_patch_fixture()
    return apply_structured_external_field_proposals(value, raw, evidence)


def test_a_document_may_take_a_measured_cell_but_not_erase_the_measurement():
    """A document proposal takes a measured cell and the displaced measurement is recorded in `spatial_divergence`."""
    patch = _measured_patch_result()['patches'][0]

    assert patch['value'] == 'п. Полярный', 'the documentary hierarchy is unchanged'
    divergence = patch['source_locator'].get('spatial_divergence')
    assert divergence is not None, 'the displaced measurement left no record'
    assert divergence['kind'] == 'computed_against_read'
    assert divergence['measured'][0]['operation'] == 'minimum_geometry_to_geometry'
    assert divergence['measured'][0]['calculation_crs'] == 'EPSG:32642'
    assert divergence['read'][0]['value'] == 'п. Полярный'


def test_the_displaced_measurement_keeps_a_source_ref_that_resolves():
    """The displaced measurement's `source_ref` is in the source inventory and in the cell's `source_refs`."""
    result = _measured_patch_result()
    patch = result['patches'][0]
    known = {str(source.get('source_id') or '') for source in result['source_inventory']}

    ref = patch['source_locator']['spatial_divergence']['measured'][0]['source_ref']
    assert ref in known
    assert ref in patch['source_refs']


def test_the_note_says_a_measurement_was_displaced():
    """The retrieval note keeps the winning value's note and mentions the displaced GIS measurement."""
    patch = _measured_patch_result()['patches'][0]

    assert 'GIS' in patch['retrieval_note']
    assert 'п. Полярный' in patch['retrieval_note'], 'the winning value keeps its own note'


def test_a_displaced_documentary_value_is_not_dressed_as_a_divergence():
    """A document displacing a direct value records no spatial divergence."""
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _measured_patch_fixture()
    raw['patches'][0].update({'value_origin': 'direct', 'source_locator': {'page': 3}})

    patch = apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]

    assert 'spatial_divergence' not in patch['source_locator']


def test_a_measurement_that_cannot_take_the_cell_is_still_recorded():
    """A calculated proposal that cannot replace a documentary value is still recorded in `spatial_divergence`."""
    from open_webui.services.project_evidence.proposals import (
        apply_structured_gis_field_proposals,
    )
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 130,
            'unit': 'км',
            'status': 'filled',
            'value_origin': 'direct',
            'source_refs': ['owner-src'],
            'source_locator': {'page': 188, 'document_id': 'licence-appendix'},
        }
    )
    raw['source_inventory'] = [
        {'source_id': 'owner-src', 'source_type': 'knowledge_base', 'title': 'Лицензия'}
    ]
    evidence = [
        {
            'source_domain': 'gis',
            'field_proposals': [
                {
                    'field_key': 'f1',
                    'value': 151.2,
                    'unit': 'км',
                    'value_origin': 'calculated',
                    'relation_to_object': 'direct',
                    'source_id': 'gis-infrastructure-abc',
                    'source_title': 'GIS infrastructure calculation: settlement',
                    'source_locator': {
                        'operation': 'minimum_geometry_to_geometry',
                        'calculation_crs': 'EPSG:32642',
                        'raw_distance_m': 151200.0,
                    },
                    'retrieval_note': 'Calculated minimum distance.',
                }
            ],
        }
    ]

    result = apply_structured_gis_field_proposals(value, raw, evidence)
    patch = result['patches'][0]
    known = {str(source.get('source_id') or '') for source in result['source_inventory']}

    assert patch['value'] == 130, 'the document keeps the cell'
    divergence = patch['source_locator']['spatial_divergence']
    assert divergence['measured'][0]['value'] == 151.2
    assert divergence['read'][0]['value'] == 130
    assert divergence['measured'][0]['source_ref'] in known
    assert divergence['measured'][0]['source_ref'] in patch['source_refs']


def test_the_run_says_how_many_cells_hold_a_measurement_they_did_not_use():
    """`spatial_divergence_notes` counts and names the cells carrying a spatial divergence."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        spatial_divergence_notes,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'source_locator': {'spatial_divergence': {'kind': 'computed_against_read'}},
            },
            {'field_key': 'geotizer_object.v1.r084.a02', 'source_locator': {'page': 3}},
        ]
    }

    notes = spatial_divergence_notes(envelope)

    assert len(notes) == 1
    assert '1 ячеек' in render_run_notes(notes)[0]
    assert 'geotizer_object.v1.r084.a01' in render_run_notes(notes)[0]
    assert spatial_divergence_notes({'patches': []}) == []


def test_a_conflict_the_owner_declared_without_sides_says_so():
    """`record_unrecorded_conflicts` stamps an owner-declared conflict that has no candidates, and leaves a recorded one
    alone.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        record_unrecorded_conflicts,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r045.a01',
                'status': 'conflicted',
                'value': None,
                'source_refs': ['kb-a', 'kb-b'],
                'source_locator': {'entity_scope': 'ore_field'},
            },
            {
                'field_key': 'geotizer_object.v1.r005.a01',
                'status': 'conflicted',
                'value': None,
                'source_refs': ['kb-a', 'kb-b'],
                'source_locator': {'candidates': [{'value': 'R-42'}, {'value': 'Q-42'}]},
            },
        ]
    }

    repaired, notes = record_unrecorded_conflicts(envelope)
    first, second = repaired['patches']

    assert first['status'] == 'conflicted', 'the status is the owner’s and is not repaired'
    assert first['source_locator']['policy'] == 'owner_declared_conflict_without_candidates'
    assert 'kb-a, kb-b' in first['source_locator']['selection_trace']
    assert 'selection_trace' not in second['source_locator'], 'a recorded conflict is left alone'
    assert len(notes) == 1
    assert '1 конфликтных ячеек' in render_run_notes(notes)[0]


def test_an_envelope_with_no_conflicts_gets_no_note():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        record_unrecorded_conflicts,
    )

    repaired, notes = record_unrecorded_conflicts(
        {'patches': [{'field_key': 'f1', 'status': 'filled', 'value': 'x'}]}
    )

    assert notes == []
    assert repaired['patches'][0]['status'] == 'filled'


def _radius_patch(field_key, value, divergence=None):
    locator = {'page': 12}
    if divergence is not None:
        locator['spatial_divergence'] = divergence
    return {
        'field_key': field_key,
        'value': value,
        'unit': None,
        'status': 'filled',
        'value_origin': 'direct',
        'source_refs': ['doc-1'],
        'source_locator': locator,
    }


def _road_divergence(value):
    return {
        'kind': 'computed_against_read',
        'measured': [{'value': value, 'unit': None, 'source_ref': 'gis-1'}],
        'read': [{'value': 'документ', 'source_ref': 'doc-1'}],
    }


def test_a_value_that_says_it_is_130_km_away_cannot_fill_the_50_km_row():
    """An out-of-radius value is replaced by a recorded measurement within the radius and kept in `candidates`."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r084.a01',
                'г. Лабытнанги (130 км)',
                _road_divergence('автомобильная дорога row:17; 0.0 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]

    assert patch['status'] == 'filled'
    assert patch['value'] == 'автомобильная дорога row:17; 0.0 км'
    assert patch['value_origin'] == 'calculated'
    assert patch['source_refs'][0] == 'gis-1'
    assert patch['source_locator']['policy'] == 'out_of_radius_value_replaced_by_measurement'
    refused = patch['source_locator']['candidates'][-1]
    assert refused['value'] == 'г. Лабытнанги (130 км)'
    assert refused['locator']['stated_distance_km'] == 130.0
    assert refused['locator']['row_radius_km'] == 50.0
    assert '1 ячеек' in render_run_notes(notes)[0]


def test_an_out_of_radius_value_with_no_measurement_goes_to_a_person():
    """An out-of-radius value with no measurement to replace it goes to `requires_expert_review`."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        OUT_OF_RADIUS_RULE,
        refuse_out_of_radius_infrastructure,
    )

    envelope = {'patches': [_radius_patch('geotizer_object.v1.r084.a01', 'г. Воркута (130 км)')]}

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['value_origin'] is None
    assert OUT_OF_RADIUS_RULE in patch['source_locator']['selection_trace']
    assert patch['source_locator']['candidates'][-1]['value'] == 'г. Воркута (130 км)'
    assert 'передано эксперту' in render_run_notes(notes)[0]


def test_a_value_inside_the_radius_keeps_its_cell_against_a_measurement():
    """A value stating a distance inside the radius keeps its cell."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r084.a01',
                'п. Полярный (30 км)',
                _road_divergence('автомобильная дорога row:17; 0.0 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['value'] == 'п. Полярный (30 км)'
    assert notes == []


def test_a_value_stating_no_distance_is_left_alone():
    """A value stating no distance is left unchanged."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r085.a01',
                'п. Полярный',
                _road_divergence('автомобильная дорога row:11; 51.293 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['value'] == 'п. Полярный'
    assert notes == []


def test_a_range_is_read_at_its_nearest_end():
    """`stated_distance_km` reads a range at its nearest end and returns None for a value with no distance."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        stated_distance_km,
    )

    assert stated_distance_km('ж/д ветка (70–130 км)') == 70.0
    assert stated_distance_km('в 60 км к северу') == 60.0
    assert stated_distance_km('расстояние 60-300 км') == 60.0
    assert stated_distance_km('автомобильная дорога row:13; 40.813 км') == 40.813
    assert stated_distance_km('п. Полярный') is None
    assert stated_distance_km(130) is None


def test_an_empty_cell_on_an_unanswerable_row_is_told_why():
    """A `not_found` cell on an unanswerable row keeps its status and gets the absence code and its meaning."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r082.a01',
            'roles': ['port'],
            'role_labels': ['порт'],
            'code': 'layer_not_found',
            'code_meaning_ru': 'В проекте нет слоя для этой роли.',
        }
    ]
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r082.a01',
                'value': None,
                'status': 'not_found',
                'source_refs': ['web'],
                'retrieval_note': 'Значение не найдено. Где искали: Web search: no data.',
                'source_locator': {'relation_to_object': 'direct'},
            }
        ]
    }
    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'not_found'
    assert patch['value'] is None
    assert patch['source_locator']['absence_code'] == 'layer_not_found'
    assert patch['retrieval_note'].endswith('В проекте нет слоя для этой роли.')
    assert 'Web search: no data' in patch['retrieval_note']
    assert 'Роли: порт' in patch['retrieval_note']
    assert 'layer_not_found' in render_run_notes(notes)[0]


def test_an_unanswerable_row_the_run_never_reached_is_left_alone():
    """A status that is neither filled nor not_found is somebody else's."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r082.a01',
            'role_labels': ['порт'],
            'code': 'layer_not_found',
            'code_meaning_ru': 'В проекте нет слоя для этой роли.',
        }
    ]
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r082.a01',
                'value': None,
                'status': 'agent_contract_failed',
                'source_refs': ['web'],
                'source_locator': {},
            }
        ]
    }
    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert repaired['patches'][0]['status'] == 'agent_contract_failed'
    assert notes == []


def test_every_absence_code_the_catalogue_names_has_a_sentence():
    """`ABSENCE_TRACE_RU` and `ABSENCE_NOTE_RU` hold a distinct sentence for exactly `layer_not_found`,
    `layer_lacks_required_attribute` and `only_the_source_feature_in_layer`.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        ABSENCE_NOTE_RU,
        ABSENCE_TRACE_RU,
    )

    codes = {
        'layer_not_found',
        'layer_lacks_required_attribute',
        'only_the_source_feature_in_layer',
    }

    assert set(ABSENCE_TRACE_RU) == codes
    assert set(ABSENCE_NOTE_RU) == codes
    assert len({*ABSENCE_TRACE_RU.values()}) == len(codes)
    assert len({*ABSENCE_NOTE_RU.values()}) == len(codes)
    assert 'нет слоя' not in ABSENCE_TRACE_RU['only_the_source_feature_in_layer']
    assert 'истинное отсутствие' in ABSENCE_TRACE_RU['only_the_source_feature_in_layer']
    assert 'нет слоя' not in ABSENCE_TRACE_RU['layer_lacks_required_attribute']
    assert 'нет колонок' in ABSENCE_TRACE_RU['layer_lacks_required_attribute']
    assert 'no_labelled_feature_in_layer' not in ABSENCE_TRACE_RU
    assert 'no_labelled_feature_in_layer' not in ABSENCE_NOTE_RU


def test_a_displaced_measurement_keeps_its_unit_in_the_note():
    """The displaced-measurement note carries the measurement's unit exactly once."""
    from open_webui.services.project_evidence.proposals import (
        _note_with_displaced_measurement,
    )

    written = {'spatial_divergence': {'measured': [{'value': 95.366, 'unit': 'км'}]}}
    scalar = {'value': 95.366, 'unit': 'км'}
    assert _note_with_displaced_measurement('Прямая оценка.', written, scalar).endswith(
        'не выбран: 95.366 км. Он сохранён в source_locator.spatial_divergence.'
    )

    labelled = {'value': 'автомобильная дорога row:17; 0.0 км', 'unit': 'км'}
    assert '0.0 км.' in _note_with_displaced_measurement('', written, labelled)
    assert 'км км' not in _note_with_displaced_measurement('', written, labelled)


def test_the_note_is_read_when_the_value_names_no_distance():
    """`note_distance_km` reads the nearest distance stated in a note."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        note_distance_km,
    )

    assert note_distance_km('Прямая оценка из лицензии: … в 70 км.', limit_km=50.0) == 70.0
    assert note_distance_km('п. Полярный (в диапазоне 60-300 км)', limit_km=50.0) == 60.0
    assert note_distance_km('точка доступа, расстояния нет', limit_km=50.0) is None

    assert note_distance_km('Населенный пункт в радиусе 100 км', limit_km=100.0) is None
    assert (
        note_distance_km('в радиусе 50 км (фактически 70 км)', limit_km=50.0) == 70.0
    )
    assert note_distance_km('Населённый пункт в радиусе 130 км', limit_km=50.0) == 130.0


def test_the_measurement_this_run_wrote_into_the_note_is_not_the_object_s_distance():
    """`note_distance_km` ignores distances equal to the cell's own recorded measurements."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        _measured_distances_km,
        note_distance_km,
    )

    locator = {
        'spatial_divergence': {
            'kind': 'computed_against_read',
            'measured': [{'value': 'автомобильная дорога row:17; 0.0 км'}],
        }
    }
    note = (
        'Прямая оценка из лицензии: ж/д ветка Обская – Бованенково в 70 км. '
        'Расчёт GIS для этой ячейки не выбран: автомобильная дорога row:17; 0.0 км.'
    )

    assert _measured_distances_km(locator) == {0.0}
    assert note_distance_km(note, limit_km=50.0) == 0.0
    assert (
        note_distance_km(note, limit_km=50.0, measured_km=_measured_distances_km(locator))
        == 70.0
    )


def test_a_note_distance_refusal_says_which_field_stated_it():
    """A refusal based on a note distance records `retrieval_note` as where the distance was read from."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'value': 'ж/д ветка Обская – Бованенково',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['doc'],
                'retrieval_note': 'Прямая оценка из лицензии: ж/д ветка в 70 км.',
                'source_locator': {'relation_to_object': 'direct'},
            }
        ]
    }
    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]
    refused = patch['source_locator']['candidates'][0]

    assert patch['status'] == 'requires_expert_review'
    assert refused['locator']['stated_distance_km'] == 70.0
    assert refused['locator']['stated_distance_read_from'] == 'retrieval_note'
    assert 'расстояния не называет' in patch['source_locator']['selection_trace']
    assert notes


def test_only_the_two_radius_rows_are_governed():
    """Rows other than the two radius rows are not refused for distance."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {'patches': [_radius_patch('geotizer_object.v1.r078.a01', '130 км')]}

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def _unanswerable_envelope(code, labels):
    return (
        {
            'patches': [
                {
                    'field_key': 'geotizer_object.v1.r086.a01',
                    'value': 'СЛХ 025834 ТП',
                    'unit': None,
                    'status': 'filled',
                    'value_origin': 'direct',
                    'source_refs': ['doc-1'],
                    'source_locator': {'page': 4},
                }
            ]
        },
        [
            {
                'field_key': 'geotizer_object.v1.r086.a01',
                'roles': ['licence'],
                'role_labels': labels,
                'code': code,
            }
        ],
    )


def test_a_layer_missing_the_row_s_columns_is_not_reported_as_a_missing_layer():
    """`layer_lacks_required_attribute` is reported as missing columns, not as a missing layer."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
        render_run_notes,
    )

    envelope, unanswerable = _unanswerable_envelope(
        'layer_lacks_required_attribute', ['лицензия']
    )

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['source_locator']['absence_code'] == 'layer_lacks_required_attribute'
    assert 'нет слоя' not in patch['source_locator']['selection_trace']
    assert 'нет колонок' in patch['source_locator']['selection_trace']
    assert render_run_notes(notes) == [
        '1 ячеек: слой в проекте есть, объекты в нём есть, но нет колонок, из '
        'которых строится значение строки; значение отклонено правилом '
        "'spatial_question_needs_a_spatial_answer' и передано эксперту "
        '(geotizer_object.v1.r086.a01).'
    ]


def test_an_absence_this_side_has_no_wording_for_is_named_not_guessed():
    """An unknown absence code is described by its `code_meaning_ru` and named in the run note."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
        render_run_notes,
    )

    envelope, unanswerable = _unanswerable_envelope('a_code_from_a_later_catalogue', ['лицензия'])
    unanswerable[0]['code_meaning_ru'] = 'Причина, которую эта сторона ещё не знает.'

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    trace = repaired['patches'][0]['source_locator']['selection_trace']

    assert 'нет слоя' not in trace
    assert 'Причина, которую эта сторона ещё не знает.' in trace
    assert 'a_code_from_a_later_catalogue' in render_run_notes(notes)[0]


def test_a_missing_layer_still_reads_as_a_missing_layer():
    """`layer_not_found` is still reported as a missing layer."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    envelope, unanswerable = _unanswerable_envelope('layer_not_found', ['лицензия'])

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert repaired['patches'][0]['source_locator']['absence_code'] == 'layer_not_found'
    assert 'нет слоя' in repaired['patches'][0]['source_locator']['selection_trace']
    assert 'инфраструктурных ячеек' in render_run_notes(notes)[0]


def test_the_two_absences_are_counted_separately():
    """Each absence code gets its own run note."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    envelope = {
        'patches': [
            {
                'field_key': key,
                'value': 'что-то',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['doc-1'],
                'source_locator': {},
            }
            for key in ('geotizer_object.v1.r086.a01', 'geotizer_object.v1.r078.a01')
        ]
    }
    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r086.a01',
            'roles': ['licence'],
            'role_labels': ['лицензия'],
            'code': 'only_the_source_feature_in_layer',
        },
        {
            'field_key': 'geotizer_object.v1.r078.a01',
            'roles': ['settlement'],
            'role_labels': ['населённый пункт'],
            'code': 'layer_not_found',
        },
    ]

    _, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert len(notes) == 2
    rendered = render_run_notes(notes)
    assert any('инфраструктурных ячеек' in note for note in rendered)
    assert any('единственный объект в нём' in note for note in rendered)
