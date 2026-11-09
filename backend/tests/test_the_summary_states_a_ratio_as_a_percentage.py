"""The counts line states both completeness ratios as percentages, rounded identically to the target line."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    completeness_lines,
    fill_percent,
    target_line,
)


STRICT, BASIC, TOTAL = 159, 203, 351


def _final(*, quality=None, strict=STRICT, basic=BASIC, total=TOTAL):
    final = {
        'counts': {'filled': strict},
        'audit': {
            'completeness': {
                'strict': {'filled': strict, 'of': total},
                'basic': {'filled': basic, 'of': total},
            }
        },
    }
    if quality is not None:
        final['fill_quality'] = quality
    return final


def _filled(final):
    return next(
        line for line in completeness_lines(final).splitlines()
        if line.startswith('- Заполнено')
    )


def test_both_ratios_are_stated_as_percentages():
    line = _filled(
        _final(quality={'strict_fill_percent': 45.3, 'basic_fill_percent': 57.8})
    )

    assert line == (
        f'- Заполнено: {STRICT} из {TOTAL} (45.3%, строго) · '
        f'{BASIC} из {TOTAL} (57.8%, с учётом расхождений)'
    )


def test_a_service_that_sends_no_percentages_gets_the_same_rounding():
    """Without service percentages the counts line derives both rates with the same one-place rounding."""
    line = _filled(_final())

    assert '(45.3%, строго)' in line
    assert '(57.8%, с учётом расхождений)' in line


def test_the_two_lines_round_identically():
    """The `basic` rate in the counts line equals the rate in the target line."""
    final = _final()
    counts = _filled(final)
    target = target_line({**final, 'fill_quality': {
        'basic_fill_percent': fill_percent(
            final, 'basic_fill_percent', BASIC, TOTAL,
        ),
        'target_fill_rate': 0.8,
        'target_measured_on': 'basic',
        'target_met': False,
    }})
    rate = target.split(': ', 1)[1].split('%', 1)[0]

    assert f'({rate}%, с учётом расхождений)' in counts


def test_neither_percentage_is_invented_when_neither_figure_exists():
    """A card with no completeness pair prints the single filled count and no percentage."""
    line = _filled({'counts': {'filled': 159}, 'audit': {'completeness': {}}})

    assert line == '- Заполнено: 159'


def test_one_percentage_without_the_other_prints_neither():
    """A card with only the strict percentage and no basic pair prints no percentage."""
    line = _filled(
        _final(strict=STRICT, basic=None, quality={'strict_fill_percent': 45.3})
    )

    assert '%' not in line


def test_the_recorded_rate_wins_over_the_division():
    """`fill_percent` returns the service's recorded rate when one is present instead of dividing."""
    final = {'fill_quality': {'basic_fill_percent': 57.9}}

    assert fill_percent(final, 'basic_fill_percent', 203, 351) == 57.9


def test_the_division_is_rounded_to_one_place():
    assert fill_percent({}, 'basic_fill_percent', 203, 351) == 57.8
    assert fill_percent({}, 'strict_fill_percent', 159, 351) == 45.3


def test_a_missing_figure_is_none_rather_than_zero():
    """`fill_percent` returns None for a missing numerator or a zero or missing
    denominator, and 0.0 for a zero numerator."""
    assert fill_percent({}, 'basic_fill_percent', None, 351) is None
    assert fill_percent({}, 'basic_fill_percent', 203, 0) is None
    assert fill_percent({}, 'basic_fill_percent', 203, None) is None
    assert fill_percent({}, 'basic_fill_percent', 0, 351) == 0.0
