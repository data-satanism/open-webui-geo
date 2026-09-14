"""One document stated the same ratio two ways and only one of them was a rate.

Run `c0455027`'s envelope carried:

    - **Заполнено:** 159 из 351 (строго) · 203 из 351 (с учётом расхождений)
    - Заполненность: 45.3% (цель 80%: …)

Two counts and a percentage, in the same markdown, and a reader comparing this
run to the last one has to divide. The counts line now states both ratios as
percentages as well, so nothing has to be computed off the page:

    - **Заполнено:** 159 из 351 (45.3%, строго) · 203 из 351 (57.8%, с учётом
      расхождений)

The rounding matters more than the figures. «45.3%» here and «45.32%» three
lines down is the shape that produced the last round's five-site sweep, so
both lines are printed from `fill_percent` -- one expression, one rounding,
two callers. Two implementations of the same division drift, and the drift is
invisible because both look finished.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    completeness_lines,
    fill_percent,
    target_line,
)


#: Run `c0455027`'s own figures.
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
    """An older service sends the pair and not the rates. Dividing here is the
    same division; rounding it differently from the target line is the defect,
    so the fallback repeats that expression rather than formatting afresh."""
    line = _filled(_final())

    assert '(45.3%, строго)' in line
    assert '(57.8%, с учётом расхождений)' in line


def test_the_two_lines_round_identically():
    """The property, stated over the figures rather than over one example.
    `Заполненность` is the `basic` rate and so is the second half of
    `Заполнено`; a reader meeting both must meet one number."""
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
    """A card with no pair falls back to the single count, exactly as before.
    A percentage derived from a figure the result does not carry is the thing
    INV-4 forbids, and it would be indistinguishable from a measured one."""
    line = _filled({'counts': {'filled': 159}, 'audit': {'completeness': {}}})

    assert line == '- Заполнено: 159'


def test_one_percentage_without_the_other_prints_neither():
    """The reader would take the one shown as the figure. A run whose service
    sends `strict_fill_percent` and no basic pair cannot be half-rendered."""
    line = _filled(
        _final(strict=STRICT, basic=None, quality={'strict_fill_percent': 45.3})
    )

    assert '%' not in line


# --- `fill_percent` itself --------------------------------------------------

def test_the_recorded_rate_wins_over_the_division():
    """The service's own figure, when it sent one: it is the number the
    verdict was computed against, and recomputing it here would be a second
    opinion presented as the first."""
    final = {'fill_quality': {'basic_fill_percent': 57.9}}

    assert fill_percent(final, 'basic_fill_percent', 203, 351) == 57.9


def test_the_division_is_rounded_to_one_place():
    assert fill_percent({}, 'basic_fill_percent', 203, 351) == 57.8
    assert fill_percent({}, 'strict_fill_percent', 159, 351) == 45.3


def test_a_missing_figure_is_none_rather_than_zero():
    """A gap and a guard must not look alike: 0.0% is a real answer for a run
    that filled nothing, and it is not what «the run did not say» means."""
    assert fill_percent({}, 'basic_fill_percent', None, 351) is None
    assert fill_percent({}, 'basic_fill_percent', 203, 0) is None
    assert fill_percent({}, 'basic_fill_percent', 203, None) is None
    assert fill_percent({}, 'basic_fill_percent', 0, 351) == 0.0
