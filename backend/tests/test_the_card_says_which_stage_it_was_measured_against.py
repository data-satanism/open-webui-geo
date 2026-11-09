"""Tests that `completeness_lines` prints the stage-scope fraction and the out-of-stage count the service sent, and
prints neither when it sent none.
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
    """The out-of-stage count and its sections are printed beside the stage fraction."""
    text = completeness_lines(RUN_93BC59A9)

    assert '- Вне стадии: 79 ячеек' in text
    assert '1.1, 1.5, 3.7, 5.3' in text
    assert 'не требуются для отчёта о поисках' in text


def test_the_whole_card_figure_still_leads():
    """The whole-card `Заполнено` line comes first."""
    text = completeness_lines(RUN_93BC59A9)

    assert text.startswith('- Заполнено: 141')


def test_a_service_that_sends_no_profile_prints_no_fraction():
    """Without `stage_scope`, no stage fraction or out-of-stage line is printed."""
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
    """`stage_scope` is also read from `audit.completeness`."""
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
