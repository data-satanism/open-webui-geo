"""The two contradictions the pipeline should repair rather than reject.

Run `6056e157` lost 35 cells to the owner contract. Exactly one of them was a
schema contradiction -- `patches[17] negative marker cannot use status=filled`
took a whole chunk with it -- and the brief that prompted this work estimated
the coercion at "roughly 15 cells". Measured against the state, it is one.

That does not make it wrong; it makes it cheap and correct rather than a
recovery. The tests below pin the three things the measurement changed about
how it has to be written.
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
    """An envelope the real validator accepts, so a test that asserts no
    violations is asserting about the coercion and not about the fixture.

    `BATCH` declares two fields because `_partition_violations` refuses a
    patch count that does not match; the second patch is an inert `not_found`
    unless a test overrides it.
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
    """`filled` is the default a model reaches for; a marker is a positive
    statement about absence. The marker wins."""
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': 'filled', 'value': 'нет данных', 'unit': 'м', 'value_origin': 'direct'})
    )
    patch = envelope['patches'][0]

    assert patch['status'] == 'not_found'
    assert patch['value'] is None
    assert patch['value_origin'] is None
    assert 'not_found' in render_run_notes(notes)[0]


def test_the_coercion_also_nulls_value_origin_or_it_repairs_nothing():
    """The correction that makes this a repair rather than a swap.

    `_value_origin_violations` refuses any non-`filled` status carrying a
    `value_origin` at all. Coercing the status and the value while leaving
    `value_origin='direct'` trades `negative marker cannot use status=filled`
    for `not_found must use value_origin=null`, and the cell is lost just the
    same. This asserts against the real validator, not against the shape.
    """
    envelope, _ = coerce_contradictory_patch_fields(
        _envelope({'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'})
    )

    assert validate_owner_envelope(BATCH, envelope) == ()


@pytest.mark.parametrize('status', ['not_found', 'not_applicable', 'conflicted'])
def test_all_three_valueless_statuses_are_covered(status):
    """The brief named two. The validator's rule covers three, and `conflicted`
    is 25 cells on the run that prompted this."""
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': status, 'value': 'x', 'value_origin': 'direct'})
    )

    assert envelope['patches'][0]['value'] is None
    assert validate_owner_envelope(BATCH, envelope) == ()
    assert notes


def test_a_valueless_status_carrying_only_a_value_origin_is_repaired():
    """The branch mutation testing found untested.

    `value=null` with `value_origin='direct'` violates nothing the other tests
    exercise -- there is no value to strip -- but `_value_origin_violations`
    still refuses it, so the cell is lost for a field the owner left blank
    anyway. Deleting the `elif` leaves every other test in this file green.
    """
    envelope, notes = coerce_contradictory_patch_fields(
        _envelope({'status': 'not_found', 'value': None, 'value_origin': 'direct'})
    )

    assert envelope['patches'][0]['value_origin'] is None
    assert validate_owner_envelope(BATCH, envelope) == ()
    assert 'value_origin' in render_run_notes(notes)[0]


def test_a_legitimate_filled_patch_is_untouched():
    """The coercion must not be reachable by a value that is simply a value."""
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
    """A silent repair is how a card comes to rest on a value nobody chose.
    One note per coerced patch, naming the field."""
    envelope = _envelope(
        {'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'},
        {'field_key': 'f2', 'status': 'not_found', 'value': 'y', 'value_origin': 'direct'},
    )

    _, notes = coerce_contradictory_patch_fields(envelope)

    assert len(notes) == 2
    assert any('f1' in note for note in render_run_notes(notes))
    assert any('f2' in note for note in render_run_notes(notes))


def test_the_input_envelope_is_not_mutated():
    """The loop appends the pre-enrichment envelope to `candidate_envelopes`
    before this runs, and salvage walks both. A coercion that mutated in place
    would rewrite the copy salvage is meant to fall back to."""
    original = _envelope({'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'})

    coerce_contradictory_patch_fields(original)

    assert original['patches'][0]['status'] == 'filled'
    assert original['patches'][0]['value'] == 'нет данных'
