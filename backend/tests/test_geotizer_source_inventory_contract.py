"""The source_inventory contract, written against the current implementation.

This is the "test before moving" step for CORE-BOUNDARY-01. That task deletes
eleven local mirrors of the GIS submission schema and routes the check to
`gis_service`'s dry-run instead, and it carries an explicit regression
requirement:

    source_inventory entries missing source_type/title must be rejected by the
    dry-run before submission.

Today they are not. `_source_inventory` harvests ids and returns an
unconditionally empty violation list, so a malformed entry passes every local
check and is rejected by GIS with HTTP 422 only after the whole batch has been
built. That is trap 3, and it is the concrete justification for deleting the
mirrors.

Note the direction, because it is easy to get backwards: the **repository**
copy is the broken one. The production Tool's `_source_inventory` validates
against REQUIRED_SOURCE_FIELDS and its docstring describes this bug in the past
tense. Production is ahead of Git here, so the regression test belongs against
the repository copy -- this file.

The two `xfail(strict=True)` cases below state the requirement rather than the
defect. When the dry-run lands they start passing, strict mode turns them red,
and whoever fixed it must delete the marker. That is the intended signal.
"""

from __future__ import annotations

import pytest

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


def test_source_inventory_returns_no_violations_for_a_malformed_entry():
    """Pins the defect so the fix is visible as a diff, not a surprise."""
    _, violations = _source_inventory([MALFORMED_SOURCE])

    assert violations == []


def test_source_inventory_rejects_a_non_list():
    """The one shape it does reject."""
    _, violations = _source_inventory({'source_id': 'kb-001'})

    assert violations == ['source_inventory must be an array']


def test_a_well_formed_envelope_passes_preflight():
    """Baseline: the fixture is otherwise valid, so a later failure is about
    source_inventory and not about the rest of the envelope."""
    assert validate_owner_envelope(batch(), envelope(WELL_FORMED_SOURCE)) == ()


# ------------------------------------------------------------- the requirement


@pytest.mark.xfail(
    strict=True,
    reason='CORE-BOUNDARY-01: source_type/title must be rejected before submission. '
    'Remove this marker when the gis_service dry-run replaces the local mirror.',
)
def test_missing_source_type_and_title_is_rejected():
    violations = validate_owner_envelope(batch(), envelope(MALFORMED_SOURCE))

    assert violations != ()


@pytest.mark.xfail(
    strict=True,
    reason='CORE-BOUNDARY-01: the violation must name the offending entry. '
    'Remove this marker when the gis_service dry-run replaces the local mirror.',
)
def test_the_violation_names_the_offending_source():
    _, violations = _source_inventory([MALFORMED_SOURCE])

    assert any('kb-001' in violation for violation in violations)
