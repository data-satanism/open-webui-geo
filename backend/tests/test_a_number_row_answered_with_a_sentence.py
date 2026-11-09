"""Tests for `refuse_prose_in_numeric_rows`: a sentence in a row that takes a
number moves to `requires_expert_review`, with the sentence kept for the
reviewer."""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import (
    NON_NUMERIC_IN_NUMERIC_ROW_RU,
    refuse_prose_in_numeric_rows,
)
from open_webui.services.geotizer.semantics import (
    NUMERIC_ATTRIBUTES,
    NUMERIC_FIELD_KEYS,
    expects_a_number,
    states_no_quantity,
)

ENERGY = 'geotizer_object.v1.r081.a01'


def _batch(field_key, attribute_name, row_id=81):
    return {
        'batch_id': 'GIS-DC',
        'fields': [
            {
                'field_key': field_key,
                'row_id': row_id,
                'attribute_name': attribute_name,
            }
        ],
    }


def _envelope(field_key, value, status='filled'):
    return {
        'patches': [
            {
                'field_key': field_key,
                'status': status,
                'value': value,
                'unit': None,
                'value_origin': 'direct' if status == 'filled' else None,
                'source_refs': ['s1'],
                'source_locator': {'page': 3},
            }
        ],
        'source_inventory': [{'source_id': 's1', 'source_type': 'kb', 'title': 'doc'}],
    }


def test_the_energy_node_sentence_is_refused():
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'),
        _envelope(ENERGY, 'Энергетическая база отсутствует'),
    )
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert notes


def test_the_sentence_survives_for_the_reviewer():
    """The refused sentence is kept as the value and as `refused_text`, with
    the rule's reason on the locator and in the note."""
    repaired, _ = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'),
        _envelope(ENERGY, 'Энергетическая база отсутствует'),
    )
    patch = repaired['patches'][0]

    assert patch['value'] == 'Энергетическая база отсутствует'
    why = patch['source_locator']['if_not_why_not']
    assert why['reason_kind'] == 'non_numeric_value_in_numeric_row'
    assert why['refused_text'] == 'Энергетическая база отсутствует'
    assert why['stated_reason'] == NON_NUMERIC_IN_NUMERIC_ROW_RU
    assert 'число' in why['stated_reason']
    assert why['decided_by'] == 'policy'
    assert patch['retrieval_note'] == NON_NUMERIC_IN_NUMERIC_ROW_RU
    assert patch['source_locator']['page'] == 3


def test_a_distance_is_left_alone():
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'), _envelope(ENERGY, '16.1 км')
    )

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def test_a_prose_row_named_znachenie_is_left_alone():
    """The prose row r077, whose attribute is also «значение», is left alone."""
    key = 'geotizer_object.v1.r077.a01'
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(key, 'значение', row_id=77), _envelope(key, 'Слабо освоенный район')
    )

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def test_a_cell_that_is_not_filled_is_left_alone():
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'), _envelope(ENERGY, None, status='not_found')
    )

    assert repaired['patches'][0]['status'] == 'not_found'
    assert notes == []


def test_the_rule_reaches_any_numeric_row_not_only_this_one():
    """Prose in any numeric row is refused, not only in the energy-node row."""
    key = 'geotizer_object.v1.r041.a03'
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(key, 'число профилей', row_id=41),
        _envelope(key, 'Не указано точное число профилей'),
    )

    assert repaired['patches'][0]['status'] == 'requires_expert_review'
    assert notes


@pytest.mark.parametrize(
    'value',
    [
        '16.1 км',
        '98 млн ₽',
        '1969-1970',
        '1:200 000',
        34,
        187.0,
    ],
)
def test_values_that_carry_a_quantity_are_not_prose(value):
    """Values carrying a digit are not taken for prose."""
    assert not states_no_quantity(value)


def test_the_ambiguous_attributes_are_left_out_on_purpose():
    """Attributes whose answers are numbers written as text are not in
    `NUMERIC_ATTRIBUTES`."""
    for attribute in ('средние содержания', 'масштаб', 'стоимость', 'документ', 'название'):
        assert attribute not in NUMERIC_ATTRIBUTES


def test_the_numeric_keys_are_the_znachenie_rows_that_take_numbers():
    assert 'geotizer_object.v1.r077.a01' not in NUMERIC_FIELD_KEYS
    assert ENERGY in NUMERIC_FIELD_KEYS
    assert expects_a_number({'field_key': ENERGY, 'attribute_name': 'значение'})
    assert not expects_a_number(
        {'field_key': 'geotizer_object.v1.r077.a01', 'attribute_name': 'значение'}
    )
