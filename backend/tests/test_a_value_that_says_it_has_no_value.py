"""A value whose own text asserts the value is unknown is not a value.

Run `af707b17` shipped eight cells stating they had no data, as data:

    F42   «Не указано точное число профилей»            filled
    G43   «Не указано конкретное название лаборатории»  filled
    x6    «неверифицировано»                            filled, alteration

The vocabulary could not express it, and not for want of entries -- «не
указано» and «не определено» have been in the narrow set since it was written.
What let these through is `_matches_marker`, which accepts a marker only when
what follows is a `NEGATIVE_VALUE_QUALIFIER` («в документе», «отдельно»).
These continue into a noun phrase instead, so they read as sentences.

The distinction the qualifier gate was reaching for is real and is kept here.
A sentence about the *source* is not a sentence about the *object*: «Не
указано число профилей» is about a document, «разведка не проводилась» is
about the deposit, and the second is an answer. `KB-STUDY` D33-I33 -- row 32,
«Разведка (+ТЭО)» -- hold «отсутствуют» under exactly that note, six real
answers a careless widening would delete. They are pinned below.
"""

from __future__ import annotations

import pytest

from open_webui.services.core.vocabulary import (
    ABSENCE_ASSERTION_PREFIXES,
    _is_empty_finding,
    _is_negative_value_marker,
)

#: Excel D33-I33. Row 32 is «Разведка (+ТЭО)»; the Excel row is one ahead.
EXPLORATION_ROW_CELLS = tuple(
    f'geotizer_object.v1.r032.a{index:02d}' for index in range(1, 7)
)

#: What those six cells hold on run `6af7479f`, with the note that makes them
#: answers rather than absences.
EXPLORATION_VALUE = 'отсутствуют'
EXPLORATION_NOTE = 'Согласованные данные GIS и KB: разведка не проводилась'


@pytest.mark.parametrize(
    'value',
    [
        'Не указано точное число профилей',
        'Не указано конкретное название лаборатории',
        'неверифицировано',
        'Не определен состав руд',
        'Не установлена глубина скважин',
        'Не указаны координаты',
    ],
)
def test_a_sentence_asserting_absence_is_an_empty_finding(value):
    assert _is_empty_finding(value)


@pytest.mark.parametrize(
    'value',
    [
        'Не указано точное число профилей',
        'Не указано конкретное название лаборатории',
        'неверифицировано',
    ],
)
def test_and_never_reaches_the_tier_that_empties_a_cell(value):
    """The whole reason this lives in `_is_empty_finding` alone.

    The narrow tier coerces `filled` to `not_found`, which claims nothing was
    ever established. These cells did establish something -- that the source
    does not say -- and the wide tier is where that belongs.
    """
    assert not _is_negative_value_marker(value)


def test_the_exploration_row_survives():
    """D33-I33: «отсутствуют» под «разведка не проводилась».

    Exploration was never carried out, two sources agreed, and that is a fact
    about the object. The pin is here so a later widening has to fail a named
    test rather than quietly take six answers.
    """
    assert len(EXPLORATION_ROW_CELLS) == 6
    assert not _is_negative_value_marker(EXPLORATION_VALUE)
    assert not _is_empty_finding(EXPLORATION_NOTE)
    assert not _is_empty_finding('разведка не проводилась')


@pytest.mark.parametrize(
    'value',
    [
        # One token, no space: the `не указан` patterns need two.
        'неопределенность оценки составляет 15%',
        # The token does not begin with «неверифицировано» -- it diverges at
        # the ending. A value carrying a caveat is still a value.
        'неверифицированные данные: 15 профилей',
        # The assertion has to open the value, not appear in it.
        'Число профилей не указано в отчёте 1971 года',
        'Медно-порфировый тип',
        'разведка не проводилась',
    ],
)
def test_what_the_rule_must_not_take(value):
    assert not _is_empty_finding(value)


def test_the_prefixes_are_matched_as_whole_tokens():
    """Not substrings. The fifth place this project would have been bitten.

    `скважин`, `изученн`, `reviewed_gap` and `197` inside a run id are the
    four before it. A substring rule here would take «неопределенность» and
    «неверифицированные», both of which are real values.
    """
    for prefix in ABSENCE_ASSERTION_PREFIXES:
        assert all(' ' not in token for token in prefix)
    joined = {' '.join(prefix) for prefix in ABSENCE_ASSERTION_PREFIXES}
    assert joined == {
        'не указан',
        'не определен',
        'не установлен',
        'неверифицировано',
    }
