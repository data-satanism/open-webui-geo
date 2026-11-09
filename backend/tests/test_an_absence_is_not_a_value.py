"""An absence written as a value is closed as `not_found`, and a licence record in the
work-stage row goes to expert review."""

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


def test_the_three_phrases_the_run_actually_carried():
    """«Не извлечено», «недоступно» and «не указано» read as absences."""
    for value in ('Не извлечено', 'недоступно', 'не указано'):
        assert reads_as_an_absence(value), value


def test_the_phrases_the_task_named_are_covered_too():
    for value in ('Не предоставлено', 'not verified'):
        assert reads_as_an_absence(value), value


def test_a_caveat_that_contains_the_phrase_is_still_a_value():
    """A phrase is matched against the whole value, never as a substring."""
    assert not reads_as_an_absence(
        'Возраст не указан в источнике, принят по аналогии с соседним участком'
    )
    assert not reads_as_an_absence('нет данных о финансировании за 2019 год')


def test_punctuation_around_the_phrase_does_not_hide_it():
    assert reads_as_an_absence('  «Не извлечено».  ')


def test_a_structured_value_is_never_an_absence():
    """A mapping or a list is never an absence."""
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
    """The refused phrase is kept in `if_not_why_not` with the reason kind and
    `decided_by: policy`."""
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
    """A cell that is not `filled` is left unchanged."""
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
    """Every entry of `ABSENCE_WRITTEN_AS_A_VALUE` is already casefolded."""
    for phrase in ABSENCE_WRITTEN_AS_A_VALUE:
        assert phrase == phrase.casefold(), phrase


def test_the_licence_state_is_not_a_work_stage():
    """A licence state word in the work-stage row is sent to expert review under
    `LICENCE_RECORD_IN_WORK_STAGE_RULE`."""
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
    """The refused work-stage value is kept as a candidate with its source ref."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, 'Прекращена')]}
    )

    candidates = only(repaired)['source_locator']['candidates']
    assert [item['value'] for item in candidates] == ['Прекращена']
    assert candidates[0]['source_ref'] == 's1'


def test_a_real_stage_passes():
    """A real work stage passes unchanged."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(STAGE, 'Поиски и оценка')]}
    )

    assert only(repaired)['status'] == 'filled'
    assert notes == []


def test_a_date_repeated_from_the_licence_term_is_refused():
    """Work-stage dates equal to the licence start and end are sent to expert review,
    and the licence rows keep them."""
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
    assert statuses[LICENCE_START] == 'filled'
    assert statuses[LICENCE_END] == 'filled'
    assert len(notes) == 2


def test_a_stage_date_of_its_own_is_kept():
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2017-11-21'), patch(START, '2021-06-01')]}
    )

    assert repaired['patches'][1]['status'] == 'filled'


def test_the_licence_term_is_found_in_what_the_run_already_accepted():
    """The licence term is also read from `accepted_fields`."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '2034-12-31')]},
        accepted_fields=[patch(LICENCE_END, '2034-12-31')],
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS


def test_the_dates_compare_through_their_separators():
    """Dates compare equal across `-` and `.` separators and day-month-year order."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '31.12.2034')]},
        accepted_fields=[patch(LICENCE_END, '2034-12-31')],
    )

    assert only(repaired)['status'] == EXPERT_REVIEW_STATUS


def test_two_dates_with_day_and_month_transposed_are_not_one_date():
    """Dates with day and month transposed are different dates."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2020-05-06'), patch(START, '2020-06-05')]}
    )

    assert repaired['patches'][1]['status'] == 'filled'
    assert notes == []


def test_a_value_that_is_not_a_placeable_date_is_left_alone():
    """`_same_date` is false for values without a placeable four-digit year."""
    from open_webui.services.artifacts.geotizer.owner_envelope import _same_date

    assert not _same_date('2034', '2034')
    assert not _same_date('12/31', '12/31')
    assert _same_date('2034-12-31', '31.12.2034')


def test_the_absence_phrases_agree_in_gender():
    """The masculine, feminine and plural forms of «недоступно» read as absences."""
    for value in ('Недоступна', 'недоступен', 'недоступны'):
        assert reads_as_an_absence(value), value


def test_without_a_licence_term_the_dates_are_not_guessed_at():
    """Without a licence term, work-stage dates are left unchanged."""
    repaired, notes = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(END, '2034-12-31')]}
    )

    assert only(repaired)['status'] == 'filled'
    assert notes == []


def test_the_licence_category_is_not_a_work_stage():
    """A work stage equal to the row 11 licence category is sent to expert review, and
    row 11 keeps it."""
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
    assert statuses['geotizer_object.v1.r011.a01'] == 'filled'
    assert notes


def test_a_licence_purpose_clause_is_not_a_work_stage():
    """A licence purpose clause in the work-stage row is sent to expert review."""
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
    """A work stage that differs from the row 11 category is kept."""
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
    """A work start date equal to the licence start goes to expert review with the date
    kept as a candidate."""
    repaired, _ = refuse_a_licence_record_in_the_work_stage_row(
        {'patches': [patch(LICENCE_START, '2017-11-21'), patch(START, '2017-11-21')]}
    )

    cell = repaired['patches'][1]
    assert cell['status'] == EXPERT_REVIEW_STATUS
    assert [c['value'] for c in cell['source_locator']['candidates']] == [
        '2017-11-21'
    ]


def test_the_pipeline_wires_both_rules_on_both_paths():
    """`workflow.py` calls each rule twice, on the attempt loop and on the salvage path."""
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
        assert called.count(name) == 2, (name, called.count(name))


def test_the_salvage_path_is_given_the_same_licence_term_as_the_loop():
    """Both calls of the work-stage rule in `workflow.py` pass `accepted_fields`."""
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
