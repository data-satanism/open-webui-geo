"""Tests that `coerce_contradictory_patch_fields` repairs a patch whose status contradicts its value, rather than
letting the validator reject it.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import (
    coerce_contradictory_patch_fields,
)
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope

BATCH = {
    'batch_id': 'KB-LIC-LEGAL',
    'producer': 'kb',
    'policy_version': 'geotizer_assignments.v1',
    'template_version': 'geotizer_object.v1',
    'fields': [
        {'field_key': 'f1', 'row_id': 1},
        {'field_key': 'f2', 'row_id': 1},
    ],
}


def _envelope(*patches):
    """An envelope `validate_owner_envelope` accepts.

    Holds the given patches (field `f1` unless a patch names another) and an
    inert `not_found` patch for each field of `BATCH` they do not cover.
    """
    supplied = [
        {'field_key': 'f1', 'source_refs': ['s1'], **dict(patch)} for patch in patches
    ]
    keys = {str(patch.get('field_key') or '') for patch in supplied}
    rest = [
        {'field_key': key, 'source_refs': ['s1'], 'status': 'not_found', 'value': None}
        for key in ('f1', 'f2')
        if key not in keys
    ]
    return {
        'batch_id': 'KB-LIC-LEGAL',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {
                'source_id': 's1',
                'source_type': 'knowledge_base',
                'title': 't',
                'locator': 'p1',
                'url': None,
            }
        ],
        'patches': [*supplied, *rest],
    }


def test_a_negative_marker_beats_the_status_it_contradicts():
    """A `filled` patch whose value is a negative marker becomes `not_found`."""
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': 'filled', 'value': 'нет данных', 'unit': 'м', 'value_origin': 'direct'})
    )
    patch = envelope['patches'][0]

    assert patch['status'] == 'not_found'
    assert patch['value'] is None
    assert patch['value_origin'] is None
    assert 'not_found' in render_run_notes(notes)[0]


def test_the_coercion_also_nulls_value_origin_or_it_repairs_nothing():
    """The coercion also sets `value_origin` to null, so the envelope passes the validator."""
    envelope, _ = coerce_contradictory_patch_fields(
        _envelope({'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'})
    )

    assert validate_owner_envelope(BATCH, envelope) == ()


@pytest.mark.parametrize('status', ['not_found', 'not_applicable', 'conflicted'])
def test_all_three_valueless_statuses_are_covered(status):
    """A value on a `not_found`, `not_applicable` or `conflicted` patch is removed."""
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': status, 'value': 'x', 'value_origin': 'direct'})
    )

    assert envelope['patches'][0]['value'] is None
    assert validate_owner_envelope(BATCH, envelope) == ()
    assert notes


def test_a_valueless_status_carrying_only_a_value_origin_is_repaired():
    """A valueless status carrying only a `value_origin` has it removed."""
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': 'not_found', 'value': None, 'value_origin': 'direct'})
    )

    assert envelope['patches'][0]['value_origin'] is None
    assert validate_owner_envelope(BATCH, envelope) == ()
    assert 'value_origin' in render_run_notes(notes)[0]


def test_a_legitimate_filled_patch_is_untouched():
    """A `filled` patch with an ordinary value is left unchanged."""
    original = {
        'status': 'filled',
        'value': '12',
        'unit': 'м',
        'value_origin': 'direct',
        'source_locator': {'page': 1},
    }
    envelope, notes = coerce_contradictory_patch_fields(_envelope(original))

    assert envelope['patches'][0]['value'] == '12'
    assert envelope['patches'][0]['unit'] == 'м'
    assert envelope['patches'][0]['value_origin'] == 'direct'
    assert notes == []


def test_every_coercion_is_recorded():
    """Each coerced patch gets one note naming its field."""
    envelope = _envelope(
        {'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'},
        {'field_key': 'f2', 'status': 'not_found', 'value': 'y', 'value_origin': 'direct'},
    )

    _, notes = coerce_contradictory_patch_fields(envelope)

    assert len(notes) == 2
    assert any('f1' in note for note in render_run_notes(notes))
    assert any('f2' in note for note in render_run_notes(notes))


def test_the_input_envelope_is_not_mutated():
    """`coerce_contradictory_patch_fields` leaves its input envelope unchanged."""
    original = _envelope({'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'})

    coerce_contradictory_patch_fields(original)

    assert original['patches'][0]['status'] == 'filled'
    assert original['patches'][0]['value'] == 'нет данных'
