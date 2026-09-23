"""A refusal no value can satisfy names the status that closes the row, and a repair
loop that changes nothing stops as unactionable feedback."""

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


def test_the_06fec58d_violation_now_names_the_status_that_closes_it():
    """A subarea row naming the object itself is refused with the `status:
    not_applicable` exit."""
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
    """A subarea row naming the object itself is still refused."""
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
    """A real subarea name is accepted."""
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
    """`NO_VALUE_SATISFIES_EXIT_RU` names the exit status and the condition for each of
    the four conditions."""
    sentence = NO_VALUE_SATISFIES_EXIT_RU.format(condition=condition)

    assert EXIT_MARKER in sentence
    assert condition in sentence


def test_a_repeated_violation_set_is_not_a_contract_failure():
    sentence = _owner_failure_sentence(
        2, [{'response_mode': 'envelope'}], (), False, unactionable_feedback=True
    )

    assert 'unactionable feedback' in sentence
    assert 'rather than a contract failure' in sentence
    assert 're-running the object repeats it' in sentence


def test_a_contract_failure_still_reads_as_one():
    """A contract failure without unactionable feedback is not described as
    unactionable."""
    sentence = _owner_failure_sentence(
        3, [{'response_mode': 'envelope'}], (), False
    )

    assert 'unactionable feedback' not in sentence


def test_a_specialist_failure_still_wins_over_the_new_sentence():
    """A specialist failure takes precedence over the unactionable-feedback sentence."""
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


def test_the_feedback_surface_is_the_validator_and_only_the_validator():
    """Repair feedback comes only from `validate_owner_envelope`, which has 34 refusal
    messages of which 11 name an exit."""
    import ast
    from pathlib import Path

    from open_webui.services.artifacts.geotizer import validation, workflow

    source = Path(workflow.__file__).read_text(encoding='utf-8')
    assert 'violations = validate_owner_envelope(' in source
    assert 'feedback = list(violations)' in source

    tree = ast.parse(Path(validation.__file__).read_text(encoding='utf-8'))
    lines = Path(validation.__file__).read_text(encoding='utf-8').split('\n')
    messages = exits = 0
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        body = '\n'.join(lines[node.lineno - 1:getattr(node, 'end_lineno', node.lineno)])
        messages += body.count('patches[{index}]')
        exits += body.count('_with_exit(')

    assert messages == 34
    assert exits == 11


def test_a_resource_row_with_no_entity_at_its_scope_names_the_exit():
    """A filled resource row without entity identity gets four violations, each naming
    the exit."""
    from open_webui.services.artifacts.geotizer.validation import (
        _resource_patch_violations,
    )

    violations = _resource_patch_violations(
        0,
        row_id=44,
        status='filled',
        attribute_name='значение',
        unit='т',
        value_kind='',
        origin='direct',
        entity_id='',
        entity_scope='',
        estimate_state='',
        resource_estimate_id='',
        site_name='',
        analogue_relation='',
        note='',
    )

    assert len(violations) == 4
    assert all(EXIT_MARKER in violation for violation in violations)
