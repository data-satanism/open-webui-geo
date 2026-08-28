"""«Значение» and «объем руды» are the same unit and not the same number.

Every resource row asks for three quantities at once: what the deposit
contains, how much rock holds it, and the grade. The first two are both quoted
in млн т. Nothing about the number, and nothing about the unit, says which of
them a value is -- so a metal mass could stand where an ore tonnage belongs
and every check the row had would pass it. Run `973999df` is what that costs.

`value_kind` is the only thing that separates them, and these are the tests
that make it carry that weight.

The unit is the second half and it fails differently: it is refused only when
this side recognises it *and* it belongs to another dimension. A grade in
тонны is wrong whatever the value kind says; a unit nobody listed is not
evidence of anything, and refusing it would reject a correct value for being
spelled unusually.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_webui.services.artifacts.geotizer.validation import (
    _resource_unit_violations,
)
from open_webui.services.geotizer.semantics import (
    RESOURCE_UNITS_BY_FAMILY,
    RESOURCE_VALUE_KIND_BY_ATTRIBUTE,
    semantic_hint,
)


def violations(attribute, value_kind='', unit=''):
    return _resource_unit_violations(
        0, attribute_name=attribute, value_kind=value_kind, unit=unit
    )


def test_a_metal_mass_cannot_stand_in_for_an_ore_tonnage():
    """The defect this exists for, in the direction the report found it."""
    found = violations('объем руды', 'contained_metal', 'млн т')

    assert len(found) == 1
    assert "'contained_metal' does not answer 'объем руды'" in found[0]


def test_an_ore_tonnage_cannot_stand_in_for_the_resource_value():
    """And the other direction, which is the same mistake."""
    found = violations('значение', 'ore_tonnage', 'млн т')

    assert len(found) == 1
    assert "does not answer 'значение'" in found[0]


@pytest.mark.parametrize(
    'attribute,value_kind,unit',
    [
        ('объем руды', 'ore_tonnage', 'млн т'),
        ('значение', 'contained_metal', 'т'),
        ('средние содержания', 'grade', 'г/т'),
        ('глубина прогноза', 'depth', 'м'),
        ('ресурсы', 'resource_quantity', 'т'),
    ],
)
def test_a_matching_pair_is_not_refused(attribute, value_kind, unit):
    assert violations(attribute, value_kind, unit) == []


def test_a_grade_quoted_in_tonnes_is_refused():
    found = violations('средние содержания', 'grade', 'млн т')

    assert len(found) == 1
    assert 'is mass' in found[0] and 'concentration' in found[0]


def test_the_unit_is_checked_even_with_no_value_kind():
    """The value kind is absent far more often than it is wrong."""
    found = violations('объем руды', '', 'г/т')

    assert len(found) == 1
    assert 'is concentration' in found[0]


def test_an_absent_value_kind_with_a_fitting_unit_is_not_refused_yet():
    """Requiring it waits until the model is told to send it.

    `semantic_hint` emitted `allowed_value_kinds` for the GRR plan rows and
    for nothing else, so the resource rows have never asked for a value kind.
    Refusing an owner for omitting a field nobody requested is how a check
    gets switched off in its first week.
    """
    assert violations('объем руды', '', 'млн т') == []


def test_an_unrecognised_unit_is_not_evidence_of_a_mismatch():
    assert violations('объем руды', 'ore_tonnage', 'бочек') == []


def test_a_non_resource_attribute_is_left_alone():
    assert violations('описание результатов', 'anything', 'млн т') == []


def test_no_unit_belongs_to_two_dimensions():
    """The inversion the rule reads is only sound while this holds.

    `RESOURCE_UNIT_FAMILIES` maps a unit to one family. If a unit were listed
    under two, the dict would silently keep whichever came last and the check
    would be guessing rather than deciding.
    """
    seen: dict[str, str] = {}
    for family, units in RESOURCE_UNITS_BY_FAMILY.items():
        for unit in units:
            assert unit not in seen, f'{unit!r} is in {seen[unit]} and {family}'
            seen[unit] = family


def test_the_contract_is_stated_to_the_model():
    """A rule refusing a value kind the prompt never asked for is a trap."""
    hint = semantic_hint(
        {'row_id': 46, 'attribute_name': 'объем руды'}
    )

    assert hint['allowed_value_kinds'] == ['ore_tonnage', 'ore_volume']


def test_the_stated_contract_and_the_enforced_one_are_the_same_table():
    """Two copies drift; one does not."""
    for attribute, kinds in RESOURCE_VALUE_KIND_BY_ATTRIBUTE.items():
        hint = semantic_hint({'row_id': 46, 'attribute_name': attribute})
        if 'allowed_value_kinds' in hint:
            assert hint['allowed_value_kinds'] == sorted(kinds)


def test_the_rule_is_reached_from_the_patch_validator():
    """Called, not merely written.

    Every test above exercises `_resource_unit_violations` directly, and all
    of them would pass on a rule nothing invokes. This one goes in through
    `_semantic_patch_violations`, which is what an owner envelope actually
    meets.
    """
    from open_webui.services.artifacts.geotizer.validation import (
        _semantic_patch_violations,
    )

    field = {
        'field_key': 'geotizer_object.v1.r046.a02',
        'row_id': 46,
        'attribute_name': 'объем руды',
    }
    patch = {
        'field_key': field['field_key'],
        'status': 'filled',
        'value': 12.0,
        'unit': 'млн т',
        'value_origin': 'direct',
        'source_locator': {
            'value_kind': 'contained_metal',
            'entity_id': 'X',
            'entity_scope': 'licence_area',
            'estimate_state': 'author_estimate',
            'resource_estimate_id': 'E1',
        },
    }

    found = _semantic_patch_violations(
        0, field, patch, batch_id='KB-RESOURCE-TECH', object_name='Объект'
    )

    assert any("does not answer 'объем руды'" in item for item in found)


def test_the_same_patch_with_the_right_kind_is_accepted():
    """The control: nothing else about the patch is what refused it."""
    from open_webui.services.artifacts.geotizer.validation import (
        _semantic_patch_violations,
    )

    field = {
        'field_key': 'geotizer_object.v1.r046.a02',
        'row_id': 46,
        'attribute_name': 'объем руды',
    }
    patch = {
        'field_key': field['field_key'],
        'status': 'filled',
        'value': 12.0,
        'unit': 'млн т',
        'value_origin': 'direct',
        'source_locator': {
            'value_kind': 'ore_tonnage',
            'entity_id': 'X',
            'entity_scope': 'licence_area',
            'estimate_state': 'author_estimate',
            'resource_estimate_id': 'E1',
        },
    }

    assert _semantic_patch_violations(
        0, field, patch, batch_id='KB-RESOURCE-TECH', object_name='Объект'
    ) == []
