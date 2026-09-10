"""The line judging a run against 80% counted the cells nobody disagreed about.

Two figures reach the envelope and the card prints both:

    Заполнено: 189 из 351 (строго) · 243 из 351 (с учётом расхождений)

and the next line said «Строгая полнота: 53.8%». One document, two numbers,
one word pointing at the smaller of them. A cell holding a sourced value with
a second sourced value recorded beside it is answered; that is `basic`, and on
run `06d1f455` it is 54 cells and 15.4 points more than `strict`.

The label loses «строгая» because the line no longer carries the strict figure,
and a label naming the wrong one is worse than no label at all.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    FILL_TARGET_LABEL,
    target_line,
)


def _final(**quality):
    return {'fill_quality': quality}


def test_it_prints_the_answered_figure_and_the_verdict():
    line = target_line(
        _final(
            strict_fill_percent=53.8,
            basic_fill_percent=69.2,
            target_measured_on='basic',
            target_met=False,
        )
    )

    assert line == f'- {FILL_TARGET_LABEL}: 69.2% (цель 80%: не достигнута)\n'


def test_the_label_no_longer_claims_the_strict_figure():
    """The other half of the change, and separable from it: a document that
    already prints «строго 189 · с расхождениями 243» must not then offer
    «Строгая полнота: 69.2%», which is neither."""
    line = target_line(
        _final(basic_fill_percent=69.2, target_measured_on='basic', target_met=False)
    )

    assert 'строг' not in line.lower()
    assert line.startswith('- Заполненность: ')


def test_a_met_target_says_so():
    line = target_line(
        _final(basic_fill_percent=84.1, target_measured_on='basic', target_met=True)
    )

    assert 'достигнута' in line and 'не достигнута' not in line


def test_an_older_service_does_not_get_its_verdict_restated(reason=None):
    """Skew, and the reason it is not papered over. A build that judged the
    strict figure sent a verdict about a different population; printing it
    beside the answered percentage would make one look like the measurement of
    the other. The percentage is derived from the pair on the audit -- the
    same division -- and the verdict is withheld."""
    line = target_line(
        {
            'fill_quality': {'strict_fill_percent': 53.8, 'target_met': False},
            'audit': {'completeness': {'basic': {'filled': 243, 'of': 351}}},
        }
    )

    assert '69.2%' in line
    assert 'по строгой цифре' in line
    assert 'не достигнута' not in line


def test_a_run_that_sent_neither_figure_says_so_rather_than_printing_zero():
    """`0%` is a measurement saying nothing was answered. Nothing was sent."""
    line = target_line({})

    assert 'не определена' in line
    assert '0%' not in line


def test_a_card_with_no_cells_does_not_divide_by_its_own_absence():
    line = target_line(
        {'audit': {'completeness': {'basic': {'filled': 0, 'of': 0}}}}
    )

    assert 'не определена' in line
