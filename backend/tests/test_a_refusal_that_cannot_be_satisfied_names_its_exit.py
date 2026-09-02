"""Two clean runs on one build, and 25 cells is the difference between them.

`06fec58d` and `94124958` were run on the same commit with nothing changed
between. Rows 50-53 came back:

    06fec58d   agent_contract_failed 20 · requires_expert_review 4
    94124958   not_applicable 12 · requires_expert_review 11 · not_found 1

`94124958`'s owner answered `not_applicable`, which is right — the object has
no участок 2 and no участок 3. `06fec58d`'s owner wrote the object's own name
into the subarea rows, was refused three times, and lost the whole chunk.

The refusal was correct both times. What differed is that one owner worked out
the exit and one did not, because the message says what is wrong and never
what is right:

    subarea row 50 names the object itself ('Лекын-Тальбейская площадь');
    rows 50-53 are named subareas of it, so an area-level figure belongs on
    the area row and not here

Accurate, and unactionable. On an object with no named subareas there is no
value that satisfies the row; the only answer that closes it is a status, and
the message did not name it. This is the `work_stage` shape for the third
time — the model told which qualifier and not where to put it, then which
value is wrong and not which status is right.

Two changes, and neither weakens a refusal. The message names the exit, and
the loop stops when an attempt changes nothing rather than spending a third on
feedback that cannot lead anywhere.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import (
    _owner_failure_sentence,
)
from open_webui.services.artifacts.geotizer.validation import (
    NO_ANALOGUE_RU,
    NO_ESTIMATE_IN_STATE_RU,
    NO_NAMED_SUBAREAS_RU,
    NO_VALUE_SATISFIES_EXIT_RU,
    NO_WORK_AT_STAGE_RU,
    _subarea_patch_violations,
)

OBJECT = ['Лекын_Талбейское', 'Лекын-Тальбейская площадь']
EXIT_MARKER = 'status: not_applicable'


# ------------------------------------------------------- the message's exit


def test_the_06fec58d_violation_now_names_the_status_that_closes_it():
    """The exact patch that cost 25 cells."""
    violations = _subarea_patch_violations(
        4,
        row_id=50,
        status='filled',
        value='2.5',
        site_name='Лекын-Тальбейская площадь',
        object_name=OBJECT,
    )

    assert len(violations) == 1
    assert 'names the object itself' in violations[0]
    assert EXIT_MARKER in violations[0]
    assert NO_NAMED_SUBAREAS_RU in violations[0]


def test_the_row_naming_itself_names_the_same_exit():
    violations = _subarea_patch_violations(
        4,
        row_id=53,
        status='filled',
        value='Участок 4',
        site_name='Участок 4',
        object_name=OBJECT,
    )

    assert 'repeats its own site name' in violations[0]
    assert EXIT_MARKER in violations[0]


def test_the_refusal_itself_is_unchanged():
    """`06fec58d`'s owner was wrong and the rule caught it. It still does."""
    violations = _subarea_patch_violations(
        4,
        row_id=50,
        status='filled',
        value='2.5',
        site_name='Лекын-Тальбейская площадь',
        object_name=OBJECT,
    )

    assert violations


def test_a_real_subarea_is_still_accepted():
    """The exit is a sentence on a refusal, not a new way to refuse."""
    violations = _subarea_patch_violations(
        4,
        row_id=50,
        status='filled',
        value='2.5',
        site_name='Участок 1',
        object_name=OBJECT,
    )

    assert violations == []


@pytest.mark.parametrize(
    'condition',
    [NO_NAMED_SUBAREAS_RU, NO_ESTIMATE_IN_STATE_RU, NO_ANALOGUE_RU, NO_WORK_AT_STAGE_RU],
)
def test_every_unsatisfiable_condition_produces_the_same_exit(condition):
    """One sentence, four conditions. A rule that invents its own wording is
    a rule the next reader has to learn separately."""
    sentence = NO_VALUE_SATISFIES_EXIT_RU.format(condition=condition)

    assert EXIT_MARKER in sentence
    assert condition in sentence


# --------------------------------------------------- the unactionable stop


def test_a_repeated_violation_set_is_not_a_contract_failure():
    sentence = _owner_failure_sentence(
        2, [{'response_mode': 'envelope'}], (), False, unactionable_feedback=True
    )

    assert 'unactionable feedback' in sentence
    assert 'rather than a contract failure' in sentence
    assert 're-running the object repeats it' in sentence


def test_a_contract_failure_still_reads_as_one():
    """The distinction only helps if the other side keeps its own sentence."""
    sentence = _owner_failure_sentence(
        3, [{'response_mode': 'envelope'}], (), False
    )

    assert 'unactionable feedback' not in sentence


def test_a_specialist_failure_still_wins_over_the_new_sentence():
    """`KB-GRR-FACTORS` chunk 2/3 was reported as a contract failure on all 18
    of its cells once already; the ordering that fixed it is preserved."""
    sentence = _owner_failure_sentence(
        3,
        [{'response_mode': 'envelope'}],
        [{'agent': 'kb', 'error': 'timeout'}],
        False,
        unactionable_feedback=True,
    )

    assert 'unactionable feedback' not in sentence


def test_a_deadline_stop_still_wins_over_everything():
    sentence = _owner_failure_sentence(
        0, [], (), True, unactionable_feedback=True
    )

    assert 'fill deadline' in sentence
