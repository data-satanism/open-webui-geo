"""«Заполнено: 141» is a number without a question.

The customer's template highlights the subsections that belong to a later
stage than this report, and four of them carry whole GeoTeaser blocks -- 1.1
Климат, 1.5 Лицензия and Юр.Лицо, 3.7 Технология, 5.3 Инфраструктура. On run
`93bc59a9` that is 79 of 351 cells, 59 of them filled.

Applying the profile takes the figure down rather than up: 141/351 = 40.2%
becomes 82/272 = 30.1%, because the sections this report does not ask for are
the ones that fill and the geology and изученность rows are the ones that do
not. So the excluded count is printed beside the fraction and never folded
into it -- the narrower denominator alone would read as progress.

The service measures it. This module prints what it was sent, and prints
nothing when it was sent nothing.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import completeness_lines

RUN_93BC59A9 = {
    'counts': {
        'required': 351,
        'filled': 141,
        'not_found': 92,
        'conflicted': 11,
        'requires_expert_review': 107,
        'agent_contract_failed': 0,
    },
    'stage_scope': {
        'report_profile': 'exploration_results',
        'in_stage': {'required': 272, 'filled': 82},
        'out_of_stage': {'required': 79, 'filled': 59, 'out_of_stage_scope': 10},
        'out_of_stage_sections': {
            '1.1': {'required': 2, 'filled': 2},
            '1.5': {'required': 28, 'filled': 24},
            '3.7': {'required': 27, 'filled': 20},
            '5.3': {'required': 22, 'filled': 13},
        },
        'contested_sections': ['5.3'],
    },
}


def test_the_stage_fraction_is_printed_with_its_denominator():
    text = completeness_lines(RUN_93BC59A9)

    assert '- Заполнено на этой стадии: 82 из 272 применимых' in text


def test_the_excluded_count_is_never_dropped():
    """82/272 on its own is a smaller number that reads as a better one."""
    text = completeness_lines(RUN_93BC59A9)

    assert '- Вне стадии: 79 ячеек' in text
    assert '1.1, 1.5, 3.7, 5.3' in text
    assert 'не требуются для отчёта о поисках' in text


def test_the_whole_card_figure_still_leads():
    """`Заполнено` stays the figure two runs are compared on."""
    text = completeness_lines(RUN_93BC59A9)

    assert text.startswith('- Заполнено: 141')


def test_a_service_that_sends_no_profile_prints_no_fraction():
    """Version skew degrades to the previous card, not to an invented number.

    This module holds no profile. A stage fraction computed here would look
    exactly like one the service measured, and would be wrong the first time
    the highlighting changed.
    """
    text = completeness_lines({'counts': RUN_93BC59A9['counts']})

    assert 'на этой стадии' not in text
    assert 'Вне стадии' not in text
    assert text.startswith('- Заполнено: 141')


def test_a_half_sent_projection_prints_nothing_rather_than_half_a_pair():
    text = completeness_lines(
        {'counts': RUN_93BC59A9['counts'], 'stage_scope': {'in_stage': {'filled': 82}}}
    )

    assert 'на этой стадии' not in text


def test_the_projection_is_also_read_off_the_audit():
    """The service carries it on the manifest and inside `completeness`."""
    text = completeness_lines(
        {
            'audit': {
                'completeness': {
                    **RUN_93BC59A9['counts'],
                    'stage_scope': RUN_93BC59A9['stage_scope'],
                }
            }
        }
    )

    assert '82 из 272 применимых' in text
    assert '- Вне стадии: 79 ячеек' in text
