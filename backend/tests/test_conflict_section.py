"""The card has to report the status it was hiding.

The result markdown printed Заполнено, Строгая полнота, Не найдено, Требует
экспертной проверки, audit counts and the links. `conflicted` was not among
them. On run `6056e157` that is 326 of 351 cells reported and 25 absent from
the only artefact the user reads.

Three documents assume otherwise:

  - `GT-3a` — report `filled`, `conflicted`, `requires_expert_review` and
    `not_found` separately
  - `GT-4` — point the reader at «Расхождения между источниками» *before* the
    completeness figure
  - `geoteaser-fill` — "A card with 183 filled, 25 conflicted and 35 under
    review has evidence for 243 cells", and the printed list is capped with
    the real total above it

An orchestrator cannot obey any of them from a card that never carries the
number.
"""

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
    """The 25 cells this run never mentioned. A service older than the detail
    still has the count, and the count is the part `GT-3a` needs."""
    section = conflict_section(RUN)

    assert 'Расхождения между источниками: 25' in section
    assert 'state.json' in section


def test_a_card_with_no_conflicts_says_nothing():
    """An empty section on every clean card would train the reader to skip the
    heading on the cards that have one."""
    assert conflict_section({'counts': {'filled': 351, 'conflicted': 0}}) == ''


def test_the_count_is_read_from_the_audit_when_counts_is_absent():
    """`counts` is the summary's; `audit.completeness` is the state's. The
    result already falls back between them for every other number."""
    section = conflict_section({'audit': {'completeness': {'conflicted': 4}}})

    assert 'Расхождения между источниками: 4' in section


def test_each_printed_disagreement_carries_both_values_with_their_sources():
    """`INV-6`: report both values with both sources and never pick one.
    `OUT-3`: value A with source, value B with source. A list of field names
    satisfies neither."""
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
    """`geoteaser-fill` already documents this shape: the list is capped and
    the count above it is the total. A cap that did not say so would read as
    the whole set."""
    conflicts = [_conflict(f'f{n}', [('A', 'м', 'kb-1'), ('B', 'м', 'gis-1')]) for n in range(25)]
    section = conflict_section({**RUN, 'conflicts': conflicts})

    assert section.count('↔') == MAX_PRINTED_CONFLICTS
    assert f'Показаны {MAX_PRINTED_CONFLICTS} из 25' in section


def test_a_conflict_the_service_sent_without_candidates_still_names_the_cell():
    """The 25 cells on this run have no candidates recorded, because they were
    produced before the values were kept. The section must degrade to naming
    them rather than printing an empty pair of quotes."""
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
    """The defect itself, guarded where it happened.

    `conflicted` was not dropped from the renderer -- it was never added, and
    nothing noticed for as long as the card has existed, because every test
    checked the numbers that were printed rather than the ones that were not.

    This used to assert against the adapter's source text, with a docstring
    saying it should move with the rendering rather than be deleted if the
    rendering ever left the adapter. It has: the lines are built by
    `completeness_lines`, so the weaker source-text check is replaced by the
    output itself. There are five statuses now rather than four --
    `agent_contract_failed` was split out of `requires_expert_review` -- and
    every one of them has to appear with its number.
    """
    rendered = completeness_lines(
        {'counts': {**RUN['counts'], 'agent_contract_failed': 27}}
    )

    for number in (183, 108, 35, 25, 27):
        assert f': {number}' in rendered, number
    assert rendered.count('\n') == 5


def test_a_status_the_service_did_not_send_is_reported_as_zero():
    """A deployment older than the split sends no `agent_contract_failed`. The
    line still prints, at 0, with the old total under expert review -- the skew
    degrades to the previous card rather than to a card missing a status."""
    rendered = completeness_lines(RUN)

    assert '- Сбой агента — данные не собраны: 0\n' in rendered
    assert '- Требует экспертной проверки: 35\n' in rendered


def test_filled_never_appears_alone():
    """197 filled is not 197 observations. The workbook says so in every
    derived cell and the card said nothing."""
    rendered = completeness_lines(
        {
            'counts': {'filled': 197},
            'value_origins': {'direct': 161, 'calculated': 29, 'analogue': 7},
        }
    )

    assert '- Заполнено: 197 (из них расчётных: 29, по аналогу: 7)\n' in rendered


def test_an_analogue_is_not_folded_into_the_calculated_count():
    """The renderer gives them different prefixes. Adding 7 analogues to 29
    formulas would make the card disagree with the workbook it links to."""
    rendered = completeness_lines(
        {'counts': {'filled': 10}, 'value_origins': {'calculated': 3, 'analogue': 4}}
    )

    assert 'расчётных: 3' in rendered
    assert 'по аналогу: 4' in rendered
    assert ': 7' not in rendered


def test_a_service_that_sends_no_origins_is_not_guessed_at():
    """Omitted, not invented. Same version-skew rule `card_docx_link` follows."""
    assert completeness_lines(RUN).startswith('- Заполнено: 183\n')
