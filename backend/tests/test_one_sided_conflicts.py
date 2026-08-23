"""A candidate that states no value is not a side of a disagreement.

§4.1's rule, in the shape the marker check cannot see. That one refuses a
negative *marker* — «неизвестно», «не указано» — used as a value; this is the
case where the candidate's `value` is `null` outright, so there is no text to
match and nothing to compare.

Run `f480a072` is the first occurrence, three cells of one row: r045.a01, a02
and a03 each hold `{value: 2332, unit: "тыс. т Cu"}` against `{value: null,
unit: null, value_origin: null}`. Three of 193 conflicts across the whole
corpus, all in that run — and it matters out of proportion to the count,
because a conflict blocks publication and these three held the gate shut over a
disagreement that does not exist.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    record_unrecorded_conflicts,
    refuse_one_sided_conflicts,
)


def conflicted(candidates, **overrides):
    return {
        'field_key': 'geotizer_object.v1.r045.a01',
        'value': None,
        'status': 'conflicted',
        'source_refs': ['doc', 'gis'],
        'source_locator': {'candidates': candidates, 'entity_scope': 'ore_field'},
        'retrieval_note': 'Конфликт: в проекте ГРР 2025 указано P1+P2, строка требует P3+P2+P1.',
        **overrides,
    }


DOCUMENT = {'value': 2332, 'unit': 'тыс. т Cu', 'value_origin': 'calculated', 'source_ref': 'doc'}
SILENT = {'value': None, 'unit': None, 'value_origin': None, 'source_ref': 'gis'}
OTHER = {'value': 605.0, 'unit': 'тыс. т', 'value_origin': 'direct', 'source_ref': 'web'}


def test_a_conflict_with_one_stated_side_goes_to_a_person():
    repaired, notes = refuse_one_sided_conflicts({'patches': [conflicted([DOCUMENT, SILENT])]})
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['source_locator']['policy'] == 'conflict_without_two_stated_values'
    assert '«2332»' in patch['source_locator']['selection_trace']
    assert notes and 'одна сторона' in notes[0]


def test_every_candidate_is_kept():
    """Marked, not decided — and the silent side is evidence too: it says which
    source was consulted and came back with nothing."""
    repaired, _ = refuse_one_sided_conflicts({'patches': [conflicted([DOCUMENT, SILENT])]})

    assert repaired['patches'][0]['source_locator']['candidates'] == [DOCUMENT, SILENT]


def test_the_owner_s_own_reason_survives():
    """r045's note explains that the document gives P1+P2 while the row asks
    P3+P2+P1 — a real reason to withhold, carried on the wrong vehicle. The
    reason is the useful half and it is not overwritten."""
    repaired, _ = refuse_one_sided_conflicts({'patches': [conflicted([DOCUMENT, SILENT])]})

    assert 'P3+P2+P1' in repaired['patches'][0]['retrieval_note']


def test_a_real_disagreement_is_left_alone():
    repaired, notes = refuse_one_sided_conflicts({'patches': [conflicted([DOCUMENT, OTHER])]})

    assert repaired['patches'][0]['status'] == 'conflicted'
    assert notes == []


def test_a_conflict_with_no_candidates_belongs_to_the_other_rule():
    """The pair covers the two ways a declared conflict can have nothing to
    resolve, and neither rule should reach into the other's case."""
    sideless = conflicted([], source_locator={'entity_scope': 'ore_field'})

    untouched, notes = refuse_one_sided_conflicts({'patches': [sideless]})
    assert untouched['patches'][0]['status'] == 'conflicted'
    assert notes == []

    marked, other_notes = record_unrecorded_conflicts({'patches': [sideless]})
    assert marked['patches'][0]['source_locator']['policy'] == (
        'owner_declared_conflict_without_candidates'
    )
    assert other_notes
