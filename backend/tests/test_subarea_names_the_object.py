"""Rows 50-53. Two ways a subarea row stops carrying a subarea's figure.

Both are live in run `f480a072`, and the guard that exists for the first was
watching when it happened.

  r050 «Участок 1 - ресурсы» carries `site_name = "Лекын-Тальбейская площадь"`
       — the licensed area — sourced to a 1976 area-level report. The rule
       compared against `object_name = "Лекын_Талбейское"`, and «Талбейское»
       and «Тальбейская площадь» do not normalise alike, so it passed.

  r053 «Участок 4 - ресурсы (условные P1)» carries `value = "Участок 4"` in
       its «значение» cell. The row already says which subarea it is; the cell
       is asked what was measured there.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.validation import (
    _subarea_patch_violations,
)


OBJECT = 'Лекын_Талбейское'


def check(row_id: int, site_name: str, *, value=None, object_name=OBJECT) -> list[str]:
    return _subarea_patch_violations(
        0,
        row_id=row_id,
        status='filled',
        site_name=site_name,
        object_name=object_name,
        value=value,
    )


def test_the_area_name_under_a_different_ending_is_caught():
    """The exact defect. Separator-and-case normalisation cannot equate two
    Russian endings, and the fix does not need a stemmer to see it."""
    violations = check(50, 'Лекын-Тальбейская площадь', value='медь-молибден')

    assert len(violations) == 1
    assert 'names the object itself' in violations[0]


def test_the_exact_spelling_is_still_caught():
    """The case the rule already handled, kept: a tightening that traded one
    catch for another would be a swap and not a fix."""
    assert check(50, 'Лекын_Талбейское', value='медь') != []


def test_a_numbered_subarea_sharing_the_leading_word_is_left_alone():
    """«Лекын-Тальбейский участок 2» starts the same way and is numbered,
    which makes it a part rather than the whole. Flagging it would refuse the
    correct answer on a project that really has subareas."""
    assert check(51, 'Лекын-Тальбейский участок 2', value='120 тыс. т') == []


def test_a_plainly_named_subarea_is_left_alone():
    assert check(51, 'Участок 2', value='120 тыс. т') == []


def test_an_unrelated_area_word_is_not_enough_on_its_own():
    """«площадь» in a name that starts with a different word is somebody
    else's area, not this object's, and this rule is not the one that judges
    it."""
    assert check(51, 'Воркутинская площадь', value='90 тыс. т') == []


def test_the_row_repeating_its_own_name_as_a_value_is_refused():
    violations = check(53, 'Участок 4', value='Участок 4')

    assert len(violations) == 1
    assert 'repeats its own site name' in violations[0]


def test_the_two_mistakes_are_reported_one_at_a_time():
    """A repair loop that gets two violations for one cell spends an attempt
    on each. The self-naming cell is reported alone, because its repair —
    put a figure here — is not the other one's."""
    violations = check(53, 'Лекын-Тальбейская площадь', value='Лекын-Тальбейская площадь')

    assert len(violations) == 1
    assert 'repeats its own site name' in violations[0]


def test_an_empty_value_is_not_a_repetition():
    """A `filled` cell with no value is somebody else's violation."""
    assert check(53, 'Участок 4', value=None) == []
    assert check(53, 'Участок 4', value='') == []


def test_rows_outside_the_subarea_block_are_untouched():
    assert check(46, 'Лекын-Тальбейская площадь', value='Лекын-Тальбейская площадь') == []


def test_nothing_fires_without_an_object_name_to_compare_against():
    """Skipped rather than guessed at. The self-naming check still runs: it
    needs no object name."""
    assert check(50, 'Лекын-Тальбейская площадь', value='медь', object_name='') == []
    assert check(50, 'Участок 1', value='Участок 1', object_name='') != []
