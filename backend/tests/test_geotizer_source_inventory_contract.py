"""The source_inventory contract.

Written first as a record of a defect, now a record of its fix.

CORE-BOUNDARY-01 carries an explicit regression requirement: source_inventory
entries missing source_type/title must be rejected before submission. They were
not. `_source_inventory` harvested ids and returned an unconditionally empty
violation list, so a malformed entry passed every local check -- the
per-attempt check, salvage, both merge checks and submission -- and was
rejected by GIS with HTTP 422 only after the whole batch had been built.

The direction was easy to get backwards: the **repository** copy was the broken
one. The production Tool validates against REQUIRED_SOURCE_FIELDS and its
docstring describes the bug in the past tense. Production was ahead of Git, so
the regression test belonged against the repository copy -- this file.

Action 4's parity corpus is what closed it. Four of its twenty-two envelopes
were accepted here and refused by the server, all four of them source-inventory
shapes, and the fix is the production implementation. The two cases below were
`xfail(strict=True)` while the requirement was unmet; the fix turned them red,
which is what strict mode is for, and the markers are gone.
"""

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
# Exactly the payload that produced the HTTP 422: an id and nothing else.
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


# --------------------------------------------------------------- current state


def test_source_inventory_harvests_ids():
    """The half that works: ids are collected and blanks dropped."""
    source_ids, _ = _source_inventory([WELL_FORMED_SOURCE, {'source_id': ''}])

    assert source_ids == {'kb-001'}


def test_source_inventory_reports_a_malformed_entry():
    """What the defect record used to assert was `violations == []`."""
    _, violations = _source_inventory([MALFORMED_SOURCE])

    assert violations == ['source_inventory[0] (kb-001) is missing source_type, title']


def test_source_inventory_rejects_a_non_list():
    """The one shape it does reject."""
    _, violations = _source_inventory({'source_id': 'kb-001'})

    assert violations == ['source_inventory must be an array']


def test_a_well_formed_envelope_passes_preflight():
    """Baseline: the fixture is otherwise valid, so a later failure is about
    source_inventory and not about the rest of the envelope."""
    assert validate_owner_envelope(batch(), envelope(WELL_FORMED_SOURCE)) == ()


# ------------------------------------------------------- the requirement, met


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
    """A patch citing '' must not be able to pass by matching a blank entry."""
    source_ids, violations = _source_inventory([{'source_id': '   '}])

    assert source_ids == set()
    assert violations == ['source_inventory[0].source_id is required']
