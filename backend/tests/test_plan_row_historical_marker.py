"""What a note about a *planned* work stage is allowed to contain.

Rows 68-76 are the ГРР plan. A patch on one of them must not be a record of
work already done, and the check for that read the note -- prose the model
writes to say where it looked -- for nine substrings: `historical`,
`историческ`, `выполнен`, `проведен`, `197`, `198`, `199`, `200`, `201`.

Five of the nine are bare digit runs, and a bare digit run is not a year. In
the exported corpus they matched a **run id**: fourteen accepted cells of run
`e4368779` carry «Восстановлено из ранее завершённого прогона
8b3cd8a2-aefa-45f4-8148-25d5a1970293», and `197` is inside that uuid. They also
match «стр. 200», «201 млн» and «1 200 м».

Two of the nine are tense-neutral stems. «Срок выполнения работ» is the
standard name for a planned period; «работы будут проведены» is future. The
fifth attribute of every plan row is «срок», which is where a duration and a
page number are most likely to appear -- and r068.a05, r069.a05 and r070.a05 of
run `d0a464be` were refused three times each with this violation and repaired
none of them. Three identical attempts, three identical violations, three cells
lost to `agent_contract_failed`.

What the rule still catches is what it was for: a note that says «historical»
or dates itself to a year before the plan.
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
    # The three that cost run `d0a464be` its «срок» cells.
    'срок выполнения работ — 2 года с даты регистрации лицензии',
    'сроки указаны в календарном плане проекта ГРР на стр. 200',
    'стоимость работ 201 млн руб.',
    # A run id, which is what `197` actually matched.
    'восстановлено из ранее завершённого прогона 8b3cd8a2-aefa-45f4-8148-25d5a1970293',
    # A distance, and the plan's own dates.
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
    """Pinned as a defect, not as a design.

    Of the 70 plan-row cells in the exported corpus whose note carries one of
    these markers, 54 are `calculated`, 2 are `analogue` and 14 are `direct`.
    The rule inspects the 14. Nineteen of the other 56 state in their own prose
    that no current plan was found and the value was constructed from
    historical data or from standard practice -- «No current planned
    geochemistry found; this is a proposed plan based on historical
    c[haracter]» on r071.a01 of run `5880a164` -- and all nineteen shipped as
    filled cells of a plan row.

    Widening the rule to every origin would turn those nineteen into
    `agent_contract_failed`, which is a worse cell than a marked one, so the
    fix is not a wider refusal. GMM attention register A-87.
    """
    import inspect

    from open_webui.services.artifacts.geotizer import validation

    source = inspect.getsource(validation._plan_patch_violations)

    assert "origin == 'direct' and _note_dates_itself_before_the_plan(note)" in source
