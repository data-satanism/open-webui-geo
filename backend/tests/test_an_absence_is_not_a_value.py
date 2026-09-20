"""«Не извлечено» is a status, and row 14 is not the licence record.

Run `area_6c2d1043…` folded seven members over Тенгкели-Березовская площадь
and reported `строго 691 из 2457`. Two of the things it counted were not
answers.

Twenty-nine of the 226 member cells the area state exposes held a phrase
saying nothing was found — eighteen «Не извлечено», six «недоступно», five
«не указано» — as the cell's VALUE, with `status: filled`. So the fold
counted them as contributions: `Лист масштаба 1 : 1 000 000` read «3 из 7»
with the value «Не извлечено — 2 об.; недоступно», where three members
answered and none of them did.

And row 14, which asks what stage the WORK is at, was answered five times
out of seven from the licence registry: «Действует» (the licence's own
state), «Добыча» and the licence's stated purpose (which are row 11), and
the licence's own start and end dates (which are rows 9 and 10).

Both are member-level defects that the fold then showed faithfully. They are
fixed where the cell is filled.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_webui.services.artifacts.geotizer.owner_envelope import (  # noqa: E402
    ABSENCE_WRITTEN_AS_A_VALUE,
    EXPERT_REVIEW_STATUS,
    LICENCE_RECORD_IN_WORK_STAGE_RULE,
    WORK_STAGE_FIELD_KEYS,
    reads_as_an_absence,
    refuse_a_licence_record_in_the_work_stage_row,
    refuse_absence_written_as_a_value,
)

STAGE = WORK_STAGE_FIELD_KEYS['stage']
START = WORK_STAGE_FIELD_KEYS['start']
END = WORK_STAGE_FIELD_KEYS['end']
LICENCE_START = 'geotizer_object.v1.r009.a01'
LICENCE_END = 'geotizer_object.v1.r010.a01'


def patch(field_key, value, **extra):
    return {
        'field_key': field_key,
        'status': 'filled',
        'value': value,
        'unit': None,
        'value_origin': 'direct',
        'source_refs': ['s1'],
        **extra,
    }


def only(envelope):
    return envelope['patches'][0]


# -- §2 an absence reported as a value ---------------------------------------


def test_the_three_phrases_the_run_actually_carried():
    """Eighteen, six and five cells of `area_6c2d1043…`."""
    for value in ('Не извлечено', 'недоступно', 'не указано'):
        assert reads_as_an_absence(value), value


def test_the_phrases_the_task_named_are_covered_too():
    for value in ('Не предоставлено', 'not verified'):
        assert reads_as_an_absence(value), value


def test_a_caveat_that_contains_the_phrase_is_still_a_value():
    """Matched as the WHOLE value, never as a substring. «Возраст не указан
    в источнике, принят по аналогии» is a real value whose qualification
    happens to contain one of the phrases, and a substring rule would turn a
    stated caveat into a gap — the same defect pointed the other way."""
    assert not reads_as_an_absence(
        'Возраст не указан в источнике, принят по аналогии с соседним участком'
    )
    assert not reads_as_an_absence('нет данных о финансировании за 2019 год')


def test_punctuation_around_the_phrase_does_not_hide_it():
    assert reads_as_an_absence('  «Не извлечено».  ')


def test_a_structured_value_is_never_an_absence():
    """A table or a list is a value whatever it contains, and `str()` of one
    is not a phrase a specialist wrote."""
    assert not reads_as_an_absence({'value': 'не указано'})
    assert not reads_as_an_absence(['не указано'])


def test_the_cell_is_closed_not_found_and_the_value_dropped():
    repaired, notes = refuse_absence_written_as_a_value(
        {'patches': [patch('geotizer_object.v1.r005.a01', 'Не извлечено')]}
    )

    cell = only(repaired)
    assert cell['status'] == 'not_found'
    assert cell['value'] is None
    assert cell['unit'] is None
    assert cell['value_origin'] is None
    assert notes


def test_what_the_specialist_reported_survives_as_the_reason():
    """`not_found` and not `requires_expert_review`: there is nothing for an
    expert to route. But «not found HOW» is a real question, and the phrase
    is the only answer to it."""
    repaired, _ = refuse_absence_written_as_a_value(
        {'patches': [patch('geotizer_object.v1.r005.a01', 'недоступно')]}
    )

    why = only(repaired)['source_locator']['if_not_why_not']
    assert why['reason_kind'] == 'absence_reported_as_a_value'
    assert why['refused_text'] == 'недоступно'
    assert why['decided_by'] == 'policy'


def test_a_real_value_in_the_same_envelope_is_untouched():
    repaired, _ = refuse_absence_written_as_a_value(
        {
            'patches': [
                patch('geotizer_object.v1.r004.a01', 'золото, серебро'),
                patch('geotizer_object.v1.r005.a01', 'Не извлечено'),
            ]
        }
    )

    assert repaired['patches'][0]['status'] == 'filled'
    assert repaired['patches'][0]['value'] == 'золото, серебро'
    assert repaired['patches'][1]['status'] == 'not_found'


def test_a_cell_that_is_not_filled_is_left_alone():
    """A `conflicted` cell whose candidates happen to read like an absence is
    the conflict machinery's, not this rule's."""
    repaired, notes = refuse_absence_written_as_a_value(
        {
            'patches': [
                patch('geotizer_object.v1.r005.a01', 'Не извлечено',
                      status='conflicted')
            ]
        }
    )

    assert only(repaired)['status'] == 'conflicted'
    assert notes == []


def test_the_phrase_list_is_lower_case_so_the_match_can_be():
    """`reads_as_an_absence` casefolds the value and compares against these
    directly. An entry carrying a capital would never match anything."""
    for phrase in ABSENCE_WRITTEN_AS_A_VALUE:
        assert phrase == phrase.casefold(), phrase


# -- §3 the licence record in the work-stage row -----------------------------


def test_the_licence_state_is_not_a_work_stage():
    """«Действует» is `LTimeSt` from the licence registry."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, 'Действует')]}
    )

    cell = only(repaired)
    assert cell['status'] == EXPERT_REVIEW_STATUS
    assert cell['value'] is None
    assert (
        cell['source_locator']['if_not_why_not']['rule']
        == LICENCE_RECORD_IN_WORK_STAGE_RULE
    )
    assert notes


def test_the_refused_value_is_kept_as_a_candidate():
    """The shape `refuse_the_wrong_kind_of_answer` uses: something was found,
    policy declined it, and an expert needs the number that was offered in
    order to route it."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, 'Прекращена')]}
    )

    candidates = only(repaired)['source_locator']['candidates']
    assert [item['value'] for item in candidates] == ['Прекращена']
    assert candidates[0]['source_ref'] == 's1'


def test_a_real_stage_passes():
    """The rule fires only when it is sure. «Поиски и оценка» is what the row
    asks for and must survive it."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, 'Поиски и оценка')]}
    )

    assert only(repaired)['status'] == 'filled'
    assert notes == []


def test_a_date_repeated_from_the_licence_term_is_refused():
    """2017-11-21 and 2034-12-31 are the licence's own start and end, already
    in rows 9 and 10, and five of seven members put them here too."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {
            'patches': [
                patch(LICENCE_START, '2017-11-21'),
                patch(LICENCE_END, '2034-12-31'),
                patch(START, '2017-11-21'),
                patch(END, '2034-12-31'),
            ]
        }
    )

    statuses = {p['field_key']: p['status'] for p in repaired['patches']}
    assert statuses[START] == EXPERT_REVIEW_STATUS
    assert statuses[END] == EXPERT_REVIEW_STATUS
    # The licence's own rows are the right place for those dates and keep
    # them.
    assert statuses[LICENCE_START] == 'filled'
    assert statuses[LICENCE_END] == 'filled'
    assert len(notes) == 2


def test_a_stage_date_of_its_own_is_kept():
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2017-11-21'), patch(START, '2021-06-01')]}
    )

    assert repaired['patches'][1]['status'] == 'filled'


def test_the_licence_term_is_found_in_what_the_run_already_accepted():
    """r009/r010 are `KB-LIC-LEGAL`'s and r014 need not share their batch, so
    the comparison reads the accepted summary as well as this envelope."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '2034-12-31')]},
        accepted_fields=[patch(LICENCE_END, '2034-12-31')],
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS


def test_the_dates_compare_through_their_separators():
    """One source writes `2034-12-31` and another `31.12.2034`; the row is
    repeating the same date either way."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '31.12.2034')]},
        accepted_fields=[patch(LICENCE_END, '2034-12-31')],
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS


def test_two_dates_with_day_and_month_transposed_are_not_one_date():
    """6 May and 5 June 2020. An earlier version reduced a date to a SORTED
    triple, so those compared equal and a genuine work-stage date whose
    numbers happened to transpose the licence's would have been refused as
    copied from it."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2020-05-06'), patch(START, '2020-06-05')]}
    )

    assert repaired['patches'][1]['status'] == 'filled'
    assert notes == []


def test_a_value_that_is_not_a_placeable_date_is_left_alone():
    """No four-digit year, or one at both ends: not a date this comparison
    can place. Guessing is how the sorted version came to equate two
    different days."""
    from open_webui.services.artifacts.geotizer.owner_envelope import _same_date

    assert not _same_date('2034', '2034')
    assert not _same_date('12/31', '12/31')
    assert _same_date('2034-12-31', '31.12.2034')


def test_the_absence_phrases_agree_in_gender():
    """«не извлечён»/«не извлечена» were there and «недоступна»/«недоступен»
    were not — a cell reading «Недоступна» beside a feminine noun escaped a
    list clearly meant to cover the agreement."""
    for value in ('Недоступна', 'недоступен', 'недоступны'):
        assert reads_as_an_absence(value), value


def test_without_a_licence_term_the_dates_are_not_guessed_at():
    """A rule that fired on any date in the row would refuse a real stage
    date whenever the licence rows had not been filled yet."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '2034-12-31')]}
    )

    assert only(repaired)['status'] == 'filled'
    assert notes == []


# -- the two patterns the docstring named and the first version missed ------


def test_the_licence_category_is_not_a_work_stage():
    """«Добыча» is what the licence is FOR — row 11 — and one member put it
    in row 14. The first version of this rule named the defect in its
    docstring and checked only the licence STATE words, so «Добыча» passed
    unrefused while the comment claimed otherwise."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {
            'patches': [
                patch('geotizer_object.v1.r011.a01', 'Добыча'),
                patch(STAGE, 'Добыча'),
            ]
        }
    )

    statuses = {p['field_key']: p['status'] for p in repaired['patches']}
    assert statuses[STAGE] == EXPERT_REVIEW_STATUS
    # Row 11 is where that answer belongs and keeps it.
    assert statuses['geotizer_object.v1.r011.a01'] == 'filled'
    assert notes


def test_a_licence_purpose_clause_is_not_a_work_stage():
    """«для геологического изучения недр, включающего поиски и оценку…» is
    the licence's stated purpose. A work stage is a noun phrase — «поиски и
    оценка», «разведка» — and never a purpose clause, so the preposition is
    the marker, and it does not need the licence's own text to compare
    against."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {
            'patches': [
                patch(
                    STAGE,
                    'для геологического изучения недр, включающего поиски и '
                    'оценку месторождений полезных ископаемых',
                )
            ]
        }
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS
    assert notes


def test_a_stage_that_merely_resembles_the_category_is_kept():
    """The rule fires on EQUALITY with row 11, not on the vocabularies
    overlapping. «Поиски и оценка» is a real stage and is also the sort of
    phrase a licence category uses."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {
            'patches': [
                patch('geotizer_object.v1.r011.a01', 'Добыча'),
                patch(STAGE, 'Поиски и оценка'),
            ]
        }
    )

    assert repaired['patches'][1]['status'] == 'filled'
    assert notes == []


def test_the_category_comparison_sees_through_punctuation():
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, ' Добыча. ')]},
        accepted_fields=[patch('geotizer_object.v1.r011.a01', 'Добыча')],
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS


def test_work_that_really_began_on_the_licence_date_goes_to_a_reviewer():
    """A recorded decision, not an oversight. Work CAN genuinely begin the
    day a licence takes effect, and then the licence's start date is the
    honest answer to row 14 — but it is indistinguishable from the date
    being copied out of row 9, which five of seven members did. So the cell
    is not deleted: it becomes `requires_expert_review` with the date kept
    as a candidate, and a reviewer who knows the work began that day
    restores it."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2017-11-21'), patch(START, '2017-11-21')]}
    )

    cell = repaired['patches'][1]
    assert cell['status'] == EXPERT_REVIEW_STATUS
    # Kept, and reachable.
    assert [c['value'] for c in cell['source_locator']['candidates']] == [
        '2017-11-21'
    ]


# -- the pipeline actually calls them ----------------------------------------


def test_the_pipeline_wires_both_rules_on_both_paths():
    """Testing the rules as pure functions says nothing about whether
    anything calls them. Both call sites could be deleted with every other
    test in this file green — the same shape as «the member link was only
    ever matched as a string».

    Read with `ast` rather than by driving `_produce_valid_owner_envelope`,
    which needs an owner model, a batch contract and a validator round: this
    check is about the wiring existing on both paths, and it fails the
    moment either call is removed.
    """
    import ast

    source = Path(
        'backend/open_webui/services/artifacts/geotizer/workflow.py'
    ).read_text(encoding='utf-8')
    called = [
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    for name in (
        'refuse_absence_written_as_a_value',
        'refuse_a_licence_record_in_the_work_stage_row',
    ):
        # Twice: the attempt loop and the salvage path. A salvaged envelope
        # is the one an area member is most likely to end on.
        assert called.count(name) == 2, (name, called.count(name))


def test_the_salvage_path_is_given_the_same_licence_term_as_the_loop():
    """`accepted_fields` is how the rule sees a licence term accepted in an
    earlier batch. The salvage path was calling without it, so a work-stage
    date repeating that term went unrefused there — silently weaker than
    the main loop for the defect the rule exists for."""
    import ast

    source = Path(
        'backend/open_webui/services/artifacts/geotizer/workflow.py'
    ).read_text(encoding='utf-8')
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'refuse_a_licence_record_in_the_work_stage_row'
    ]

    assert len(calls) == 2
    for call in calls:
        assert [kw.arg for kw in call.keywords] == ['accepted_fields'], ast.dump(call)
