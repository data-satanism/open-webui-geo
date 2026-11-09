"""Tests for `_subarea_patch_violations` on rows 50-53: a site name that names
the object itself, and a value that repeats the row's own site name."""

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
    """The object's name under a different Russian ending is caught as naming
    the object itself."""
    violations = check(50, 'Лекын-Тальбейская площадь', value='медь-молибден')

    assert len(violations) == 1
    assert 'names the object itself' in violations[0]


def test_the_exact_spelling_is_still_caught():
    """The object's exact spelling is caught."""
    assert check(50, 'Лекын_Талбейское', value='медь') != []


def test_a_numbered_subarea_sharing_the_leading_word_is_left_alone():
    """A numbered subarea sharing the object's leading word is left alone."""
    assert check(51, 'Лекын-Тальбейский участок 2', value='120 тыс. т') == []


def test_a_plainly_named_subarea_is_left_alone():
    assert check(51, 'Участок 2', value='120 тыс. т') == []


def test_an_unrelated_area_word_is_not_enough_on_its_own():
    """An area name starting with a different word is left alone."""
    assert check(51, 'Воркутинская площадь', value='90 тыс. т') == []


def test_the_row_repeating_its_own_name_as_a_value_is_refused():
    violations = check(53, 'Участок 4', value='Участок 4')

    assert len(violations) == 1
    assert 'repeats its own site name' in violations[0]


def test_the_two_mistakes_are_reported_one_at_a_time():
    """A cell making both mistakes is reported only for repeating its own site
    name."""
    violations = check(53, 'Лекын-Тальбейская площадь', value='Лекын-Тальбейская площадь')

    assert len(violations) == 1
    assert 'repeats its own site name' in violations[0]


def test_an_empty_value_is_not_a_repetition():
    """An empty value is not a repetition of the site name."""
    assert check(53, 'Участок 4', value=None) == []
    assert check(53, 'Участок 4', value='') == []


def test_rows_outside_the_subarea_block_are_untouched():
    assert check(46, 'Лекын-Тальбейская площадь', value='Лекын-Тальбейская площадь') == []


def test_nothing_fires_without_an_object_name_to_compare_against():
    """Without an object name only the self-naming check runs."""
    assert check(50, 'Лекын-Тальбейская площадь', value='медь', object_name='') == []
    assert check(50, 'Участок 1', value='Участок 1', object_name='') != []
