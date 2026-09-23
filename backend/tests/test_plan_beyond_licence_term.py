"""A planned-work deadline past the licence end date is flagged."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
from open_webui.services.artifacts.geotizer.owner_envelope import (
    LICENCE_END_FIELD_KEY,
    PLAN_DEADLINE_FIELD_KEYS,
    flag_plan_beyond_licence_term,
)

LICENCE_END = {
    'field_key': LICENCE_END_FIELD_KEY,
    'status': 'filled',
    'value': '17.07.2031',
}


def deadline(field_key: str, value, status: str = 'filled') -> dict:
    return {'field_key': field_key, 'status': status, 'value': value}


def test_a_deadline_past_the_licence_end_is_flagged():
    envelope, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r070.a05', '2032-2034')]},
        accepted_fields=[LICENCE_END],
    )

    assert len(notes) == 1
    assert '17.07.2031' in render_run_notes(notes)[0]
    locator = envelope['patches'][0]['source_locator']
    assert locator['policy'] == 'plan_deadline_beyond_licence_term'


def test_the_value_is_kept_because_this_is_a_contradiction_not_an_error():
    """A flagged deadline keeps its value and its `filled` status."""
    envelope, _ = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r076.a02', 'IV квартал 2033')]},
        accepted_fields=[LICENCE_END],
    )

    assert envelope['patches'][0]['value'] == 'IV квартал 2033'
    assert envelope['patches'][0]['status'] == 'filled'


def test_a_deadline_inside_the_term_passes():
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r070.a05', '2026-2028')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_the_last_year_of_the_licence_is_still_inside_it():
    """Deadlines are compared by year, so the licence's last year is inside the term."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a02', '2031')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_a_cost_beside_the_deadline_is_not_read_as_a_year():
    """A four-digit number outside 1900-2199 is not read as a year."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a02', '1200 тыс. руб.')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_an_empty_deadline_cell_is_not_a_contradiction():
    """Empty deadline cells are not flagged."""
    _, notes = flag_plan_beyond_licence_term(
        {
            'patches': [
                deadline(key, None, status='not_found')
                for key in PLAN_DEADLINE_FIELD_KEYS
            ]
        },
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_without_a_licence_end_nothing_is_judged():
    """Without a licence end date nothing is flagged."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r070.a05', '2035')]},
        accepted_fields=[],
    )

    assert notes == []


def test_the_licence_end_is_read_from_this_envelope_too():
    """The licence end date is also read from the same envelope."""
    _, notes = flag_plan_beyond_licence_term(
        {
            'patches': [
                LICENCE_END,
                deadline('geotizer_object.v1.r070.a05', '2035'),
            ]
        },
    )

    assert len(notes) == 1


def test_only_the_deadline_cells_are_examined():
    """Only the deadline cells are examined."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a01', '2035 тыс. руб.')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_the_nine_deadline_cells_are_the_ones_the_template_has():
    """`PLAN_DEADLINE_FIELD_KEYS` holds the nine deadline cells: a05 of r068-r072 and
    a02 of r073-r076."""
    assert len(PLAN_DEADLINE_FIELD_KEYS) == 9
    assert 'geotizer_object.v1.r068.a05' in PLAN_DEADLINE_FIELD_KEYS
    assert 'geotizer_object.v1.r076.a02' in PLAN_DEADLINE_FIELD_KEYS
