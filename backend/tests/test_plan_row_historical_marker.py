"""Tests which retrieval notes `_note_dates_itself_before_the_plan` treats as describing work done before the ГРР plan
on rows 68-76.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.validation import (
    _note_dates_itself_before_the_plan,
)

REFUSED = [
    'работы выполнены в 1978 г.',
    'historical project parameters from 2011 announcement',
    'исторические данные о конкурсе 2006-2007 гг.',
    'по результатам ГРР 1981 года',
]

ACCEPTED = [
    'срок выполнения работ — 2 года с даты регистрации лицензии',
    'сроки указаны в календарном плане проекта ГРР на стр. 200',
    'стоимость работ 201 млн руб.',
    'восстановлено из ранее завершённого прогона 8b3cd8a2-aefa-45f4-8148-25d5a1970293',
    'профиль длиной 1 200 м',
    'план работ на 2025-2027 гг.',
    'работы будут проведены в 2026 г.',
]


@pytest.mark.parametrize('note', REFUSED)
def test_a_note_that_dates_itself_before_the_plan_is_refused(note):
    assert _note_dates_itself_before_the_plan(note.casefold())


@pytest.mark.parametrize('note', ACCEPTED)
def test_a_note_about_planned_work_is_not(note):
    assert not _note_dates_itself_before_the_plan(note.casefold())


def test_the_rule_still_only_looks_at_direct_patches():
    """`_plan_patch_violations` applies the note rule only to `direct` patches."""
    import inspect

    from open_webui.services.artifacts.geotizer import validation

    source = inspect.getsource(validation._plan_patch_violations)

    assert "origin == 'direct' and _note_dates_itself_before_the_plan(note)" in source
