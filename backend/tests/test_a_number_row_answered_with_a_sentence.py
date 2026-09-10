"""«Энергетическая база отсутствует» is not a distance.

Run `af707b17` put that sentence in the distance-to-energy-node cell and every
check passed it, because nothing could object: the template declares no types.
A field entry carries `attribute_name`, `element`, `group`, `row_id` and
`excel_cell`, and says nothing about the shape an answer takes -- so a string
in a cell that takes strings is all a validator could see.

`requires_expert_review`, not `not_found`. Something *was* found and policy
declined it, and the sentence is what a reviewer needs to tell «this row
cannot be answered for this object» from «the specialist answered a different
question». The negative-marker repair would have coerced the cell to
`not_found` and dropped the text with it.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import (
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
    """Not `not_found`: the run holds an answer and policy declined it."""
    repaired, _ = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'),
        _envelope(ENERGY, 'Энергетическая база отсутствует'),
    )
    patch = repaired['patches'][0]

    assert patch['value'] == 'Энергетическая база отсутствует'
    why = patch['source_locator']['if_not_why_not']
    assert why['reason_kind'] == 'non_numeric_value_in_numeric_row'
    assert why['stated_reason'] == 'Энергетическая база отсутствует'
    assert why['decided_by'] == 'policy'
    # The locator it already had is not discarded to make room.
    assert patch['source_locator']['page'] == 3


def test_a_distance_is_left_alone():
    repaired, notes = refuse_prose_in_numeric_rows(
        _batch(ENERGY, 'значение'), _envelope(ENERGY, '16.1 км')
    )

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def test_a_prose_row_named_znachenie_is_left_alone():
    """r077 «Степень экономической освоенности района» is prose and its
    attribute is «значение», the same word as six distance rows carry."""
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
    """Run-wide by construction: a property of the row, not a list of cells."""
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
    """A digit test and not a parser. None of these is a bare float and every
    one of them is a legitimate answer in its row."""
    assert not states_no_quantity(value)


def test_the_ambiguous_attributes_are_left_out_on_purpose():
    """«Средние содержания» is «Au 1.2 г/т», «масштаб» is «1:200 000» and
    «стоимость» is «98 млн ₽» -- numbers wearing text. They carry digits, so
    the rule would pass them anyway; they are out of the table because a
    looser one buys nothing and risks false refusals."""
    for attribute in ('средние содержания', 'масштаб', 'стоимость', 'документ', 'название'):
        assert attribute not in NUMERIC_ATTRIBUTES


def test_the_numeric_keys_are_the_znachenie_rows_that_take_numbers():
    assert 'geotizer_object.v1.r077.a01' not in NUMERIC_FIELD_KEYS
    assert ENERGY in NUMERIC_FIELD_KEYS
    assert expects_a_number({'field_key': ENERGY, 'attribute_name': 'значение'})
    assert not expects_a_number(
        {'field_key': 'geotizer_object.v1.r077.a01', 'attribute_name': 'значение'}
    )
