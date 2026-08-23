"""Stage 6's GIS half: work planned past the licence's own end date.

The licence polygon answers none of what rows 68-76 ask -- work types,
volumes, scales, costs, deadlines, a document. The one thing it does constrain
is the outer bound. `СЛХ_025834_ТП` gives 17.07.2024 to 17.07.2031 on this
object, and work scheduled past that needs an extension, not a schedule.

It fires zero times on run `f480a072`, because every «срок» cell in the block
is empty. That is the block's real problem and this rule does not touch it.
"""

from __future__ import annotations

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
    assert '17.07.2031' in notes[0]
    locator = envelope['patches'][0]['source_locator']
    assert locator['policy'] == 'plan_deadline_beyond_licence_term'


def test_the_value_is_kept_because_this_is_a_contradiction_not_an_error():
    """Nothing here says the extraction was wrong. The plan may really run past
    the licence, which a Competent Person needs to see rather than have
    repaired away."""
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
    """Compared on the year, so 2031 against 17.07.2031 is not beyond. Going
    finer would be a false precision: a plan that says «2031» does not say
    which month."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a02', '2031')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_a_cost_beside_the_deadline_is_not_read_as_a_year():
    """«1200 тыс. руб.» is four digits and is not 1200 AD. The year pattern is
    bounded to 19xx-21xx for exactly this."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a02', '1200 тыс. руб.')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_an_empty_deadline_cell_is_not_a_contradiction():
    """The state of every «срок» cell on run `f480a072`."""
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
    """r010 is `KB-LIC-LEGAL`'s and the plan rows are `KB-GRR-FACTORS`'. A run
    that has not established the end date yet must not guess one."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r070.a05', '2035')]},
        accepted_fields=[],
    )

    assert notes == []


def test_the_licence_end_is_read_from_this_envelope_too():
    """So the rule is testable on one envelope and does not silently depend on
    batch order."""
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
    """«стоимость» sits beside «срок» on every one of these rows, and a cost
    of «2035 тыс. руб.» is not a date."""
    _, notes = flag_plan_beyond_licence_term(
        {'patches': [deadline('geotizer_object.v1.r073.a01', '2035 тыс. руб.')]},
        accepted_fields=[LICENCE_END],
    )

    assert notes == []


def test_the_nine_deadline_cells_are_the_ones_the_template_has():
    """r068-r072 carry «срок» at a05 and r073-r076 at a02, and the set is
    pinned because it was read off the template rather than derived."""
    assert len(PLAN_DEADLINE_FIELD_KEYS) == 9
    assert 'geotizer_object.v1.r068.a05' in PLAN_DEADLINE_FIELD_KEYS
    assert 'geotizer_object.v1.r076.a02' in PLAN_DEADLINE_FIELD_KEYS
