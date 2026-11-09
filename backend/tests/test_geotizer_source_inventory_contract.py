"""A `source_inventory` entry missing `source_type` or `title` is rejected before
submission."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.validation import (
    _source_inventory,
    validate_owner_envelope,
)

FIELD_KEY = 'geotizer_object.v1.r001.a01'

WELL_FORMED_SOURCE = {
    'source_id': 'kb-001',
    'source_type': 'knowledge_base',
    'title': 'Отчёт о результатах ГРР, Лекын-Тальбейская площадь',
}
MALFORMED_SOURCE = {'source_id': 'kb-001'}


def batch():
    return {
        'batch_id': 'KB-GEO',
        'producer': 'KB Agent',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': FIELD_KEY}],
    }


def envelope(source):
    return {
        'batch_id': 'KB-GEO',
        'producer': 'KB Agent',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [source],
        'patches': [
            {
                'field_key': FIELD_KEY,
                'value': '120 км',
                'unit': 'км',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['kb-001'],
                'source_locator': {'document_id': 'doc-1', 'page': 4},
            }
        ],
    }


def test_source_inventory_harvests_ids():
    """`_source_inventory` collects the source ids and drops blank ones."""
    source_ids, _ = _source_inventory([WELL_FORMED_SOURCE, {'source_id': ''}])

    assert source_ids == {'kb-001'}


def test_source_inventory_reports_a_malformed_entry():
    """An entry missing `source_type` and `title` is reported with its id."""
    _, violations = _source_inventory([MALFORMED_SOURCE])

    assert violations == ['source_inventory[0] (kb-001) is missing source_type, title']


def test_source_inventory_rejects_a_non_list():
    """An inventory that is not a list is rejected."""
    _, violations = _source_inventory({'source_id': 'kb-001'})

    assert violations == ['source_inventory must be an array']


def test_a_well_formed_envelope_passes_preflight():
    """The well-formed fixture envelope has no violations."""
    assert validate_owner_envelope(batch(), envelope(WELL_FORMED_SOURCE)) == ()


def test_missing_source_type_and_title_is_rejected():
    violations = validate_owner_envelope(batch(), envelope(MALFORMED_SOURCE))

    assert violations != ()


def test_the_violation_names_the_offending_source():
    _, violations = _source_inventory([MALFORMED_SOURCE])

    assert any('kb-001' in violation for violation in violations)


def test_an_entry_that_is_not_an_object_is_reported_rather_than_crashing():
    _, violations = _source_inventory(['kb-001'])

    assert violations == ['source_inventory[0] must be an object']


def test_an_entry_without_an_id_is_reported():
    _, violations = _source_inventory([{'source_type': 'kb', 'title': 'no id'}])

    assert violations == ['source_inventory[0].source_id is required']


def test_a_blank_id_is_not_harvested_as_a_registered_source():
    """A blank `source_id` is reported and not registered."""
    source_ids, violations = _source_inventory([{'source_id': '   '}])

    assert source_ids == set()
    assert violations == ['source_inventory[0].source_id is required']
