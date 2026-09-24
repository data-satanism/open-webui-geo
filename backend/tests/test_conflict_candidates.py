"""Tests that a conflicted cell records each competing value with its unit, origin, source and locator, while the cell
itself carries no value.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.project_evidence.proposals import (
    apply_structured_external_field_proposals,
    apply_structured_gis_field_proposals,
)

from test_geotizer_orchestration import batch, envelope


def _gis_conflict():
    raw = envelope()
    raw['patches'][0] = {
        'field_key': 'f1',
        'value': None,
        'status': 'not_found',
        'source_refs': ['s1'],
        'source_locator': {'query': 'negative owner result'},
    }
    proposals = [
        {
            'field_key': 'f1',
            'value': value,
            'unit': 'м',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': f'gis-{value}',
            'source_title': 'GIS direct',
            'source_locator': {'layer_id': f'layer-{value}'},
            'retrieval_note': 'Direct fact.',
        }
        for value in ('left', 'right')
    ]
    return apply_structured_gis_field_proposals(
        batch(),
        raw,
        [{'source_domain': 'gis', 'field_proposals': proposals}],
    )


def _owner_versus_contributor_conflict():
    """An owner patch filled directly and a structured contributor proposal that disagrees with it."""
    plan_batch = {
        **batch(),
        'batch_id': 'KB-GRR-FACTORS',
        'fields': [{'field_key': 'geotizer_object.v1.r073.a01', 'row_id': 73, 'attribute_name': 'стоимость'}],
    }
    raw = envelope()
    raw['batch_id'] = 'KB-GRR-FACTORS'
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'geotizer_object.v1.r073.a01',
            'value': 98_000_000,
            'unit': 'руб.',
            'status': 'filled',
            'value_origin': 'direct',
            'source_locator': {'page': 95},
        }
    )
    proposals = [
        {
            'field_key': 'geotizer_object.v1.r073.a01',
            'value': 1_827_450_000,
            'unit': 'руб.',
            'value_origin': 'direct',
            'value_kind': 'planned_cost',
            'temporal_role': 'approved_plan',
            'work_stage': 'prospecting',
            'source_class': 'presentation',
            'source_document_id': 'presentation-v1',
            'entity_role': 'target_object',
            'relation_to_object': 'direct',
            'source_id': 'presentation-v1',
            'source_title': 'presentation-v1',
            'source_url': '/api/v1/files/presentation-v1',
            'source_locator': {'page': 12},
            'retrieval_note': 'Direct plan cost.',
        }
    ]
    return plan_batch, apply_structured_external_field_proposals(
        plan_batch,
        raw,
        [{'source_domain': 'kb', 'field_proposals': proposals}],
    )


def test_equal_priority_claims_record_both_values():
    patch = _gis_conflict()['patches'][0]

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None
    candidates = patch['source_locator']['candidates']
    assert [item['value'] for item in candidates] == ['left', 'right']


def test_an_owner_value_that_loses_to_a_conflict_is_not_lost_with_it():
    """The owner's value is kept among the conflict candidates."""
    _, result = _owner_versus_contributor_conflict()
    patch = result['patches'][0]

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None
    values = [item['value'] for item in patch['source_locator']['candidates']]
    assert values == [98_000_000, 1_827_450_000]


def test_each_recorded_value_carries_the_source_that_said_it():
    """Each candidate carries the source ref of the source that stated it."""
    patch = _gis_conflict()['patches'][0]
    candidates = patch['source_locator']['candidates']

    assert {item['source_ref'] for item in candidates} == set(patch['source_refs'])
    assert all(item['source_ref'] for item in candidates)
    assert [item['locator'] for item in candidates] == [
        {'layer_id': 'layer-left'},
        {'layer_id': 'layer-right'},
    ]


def test_the_unit_and_origin_travel_with_the_value():
    """Each candidate carries its unit and value origin."""
    _, result = _owner_versus_contributor_conflict()
    candidates = result['patches'][0]['source_locator']['candidates']

    assert all(item['unit'] == 'руб.' for item in candidates)
    assert all(item['value_origin'] == 'direct' for item in candidates)


def test_the_cell_itself_still_carries_no_value():
    """A conflicted cell keeps `value` null after the candidates are recorded."""
    for value in (_gis_conflict(), _owner_versus_contributor_conflict()[1]):
        patch = value['patches'][0]
        assert patch['value'] is None
        assert patch['unit'] is None
        assert patch['value_origin'] is None


def test_recording_the_candidates_does_not_break_the_contract():
    """An envelope with recorded candidates passes `validate_owner_envelope`."""
    plan_batch, result = _owner_versus_contributor_conflict()

    assert validate_owner_envelope(plan_batch, result) == ()


def test_the_existing_locator_keys_are_kept():
    """Recording candidates keeps `candidate_locators`, `owner_locator` and `proposal_locator`."""
    assert 'candidate_locators' in _gis_conflict()['patches'][0]['source_locator']
    owner_side = _owner_versus_contributor_conflict()[1]['patches'][0]['source_locator']
    assert 'owner_locator' in owner_side
    assert 'proposal_locator' in owner_side
