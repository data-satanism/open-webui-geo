"""The card reports the `conflicted` count and the disagreements behind it."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    MAX_PRINTED_CONFLICTS,
    completeness_lines,
    conflict_section,
)

RUN = {'counts': {'filled': 183, 'not_found': 108, 'requires_expert_review': 35, 'conflicted': 25}}


def _conflict(field_key, values, *, element='Магнитометрия', attribute='метод'):
    return {
        'field_key': field_key,
        'element': element,
        'attribute_name': attribute,
        'candidates': [
            {'value': value, 'unit': unit, 'value_origin': 'direct', 'source_ref': ref}
            for value, unit, ref in values
        ],
    }


def test_the_count_is_stated_even_when_the_service_sends_no_detail():
    """The conflict count and a pointer to `state.json` are printed without conflict
    detail."""
    section = conflict_section(RUN)

    assert 'Расхождения между источниками: 25' in section
    assert 'state.json' in section


def test_a_card_with_no_conflicts_says_nothing():
    """A card with no conflicts has no conflict section."""
    assert conflict_section({'counts': {'filled': 351, 'conflicted': 0}}) == ''


def test_the_count_is_read_from_the_audit_when_counts_is_absent():
    """Without `counts`, the conflict count is read from `audit.completeness`."""
    section = conflict_section({'audit': {'completeness': {'conflicted': 4}}})

    assert 'Расхождения между источниками: 4' in section


def test_each_printed_disagreement_carries_both_values_with_their_sources():
    """Each printed disagreement shows every value with its unit and source."""
    section = conflict_section(
        {
            **RUN,
            'conflicts': [_conflict('geotizer_object.v1.r040.a01', [('A', 'м', 'kb-1'), ('B', 'м', 'gis-1')])],
        }
    )

    assert '«A м» [kb-1]' in section
    assert '«B м» [gis-1]' in section
    assert '↔' in section
    assert 'Магнитометрия / метод' in section


def test_a_side_without_a_unit_does_not_grow_a_stray_space():
    section = conflict_section(
        {**RUN, 'conflicts': [_conflict('f1', [('A', None, 'kb-1'), ('B', '', 'gis-1')])]}
    )

    assert '«A» [kb-1]' in section
    assert '«B» [gis-1]' in section


def test_the_printed_list_is_capped_and_says_the_real_total():
    """The printed list is capped at `MAX_PRINTED_CONFLICTS` and states the real total."""
    conflicts = [_conflict(f'f{n}', [('A', 'м', 'kb-1'), ('B', 'м', 'gis-1')]) for n in range(25)]
    section = conflict_section({**RUN, 'conflicts': conflicts})

    assert section.count('↔') == MAX_PRINTED_CONFLICTS
    assert f'Показаны {MAX_PRINTED_CONFLICTS} из 25' in section


def test_a_conflict_the_service_sent_without_candidates_still_names_the_cell():
    """A conflict without candidates is named by its element and attribute, with no
    empty quotes."""
    section = conflict_section(
        {**RUN, 'conflicts': [{'field_key': 'f1', 'element': 'Магнитометрия', 'attribute_name': 'метод'}]}
    )

    assert 'Магнитометрия / метод' in section
    assert '«»' not in section


def test_a_conflict_with_no_label_falls_back_to_the_field_key():
    section = conflict_section(
        {**RUN, 'conflicts': [{'field_key': 'geotizer_object.v1.r040.a01', 'candidates': []}]}
    )

    assert 'geotizer_object.v1.r040.a01' in section


def test_the_result_reports_every_status_the_card_can_hold():
    """`completeness_lines` prints all five statuses with their counts."""
    rendered = completeness_lines(
        {'counts': {**RUN['counts'], 'agent_contract_failed': 27}}
    )

    for number in (183, 108, 35, 25, 27):
        assert f': {number}' in rendered, number
    assert rendered.count('\n') == 5


def test_a_status_the_service_did_not_send_is_reported_as_zero():
    """A status the service did not send is printed as 0."""
    rendered = completeness_lines(RUN)

    assert '- Сбой агента — данные не собраны: 0\n' in rendered
    assert '- Требует экспертной проверки: 35\n' in rendered


def test_filled_never_appears_alone():
    """The filled count carries its calculated and analogue shares."""
    rendered = completeness_lines(
        {
            'counts': {'filled': 197},
            'value_origins': {'direct': 161, 'calculated': 29, 'analogue': 7},
        }
    )

    assert '- Заполнено: 197 (из них расчётных: 29, по аналогу: 7)\n' in rendered


def test_an_analogue_is_not_folded_into_the_calculated_count():
    """Analogue values are counted apart from calculated ones."""
    rendered = completeness_lines(
        {'counts': {'filled': 10}, 'value_origins': {'calculated': 3, 'analogue': 4}}
    )

    assert 'расчётных: 3' in rendered
    assert 'по аналогу: 4' in rendered
    assert ': 7' not in rendered


def test_a_service_that_sends_no_origins_is_not_guessed_at():
    """Without `value_origins`, the filled line carries no shares."""
    assert completeness_lines(RUN).startswith('- Заполнено: 183\n')
