"""What a resource-row rejection has to tell the owner to be actionable.

Run `6056e157`: chunk 4/6 of `KB-RESOURCE-TECH` returned 48 violations on
attempt 2, all four resource rules across twelve patches, and repaired none of
them -- attempt 3 returned zero characters. The twelve cells were lost.

The brief that prompted this asked to quote the row contract into repair
feedback. Measured against the prompt, the contract was never missing:
`semantic_hint` already puts `required_entity_scope`,
`allowed_estimate_states`, `required_qualifiers` and
`required_analogue_relation` under `field_semantics` from attempt 1. What was
missing is the connection. `field_semantics` is keyed by `field_key`; the
violation said `patches[6]`. Acting on it meant mapping a position back to a
key and then looking that key up in a second structure.

So these tests pin two things: the violation names the field, and it carries
the value that would satisfy it rather than only the rule that refused it.
"""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.geotizer.semantics import (
    ANALOGUE_RELATION_BY_ROW,
    RESOURCE_ENTITY_SCOPE_BY_ROW,
    RESOURCE_ESTIMATE_STATES_BY_ROW,
    semantic_hint,
)

FIELD_KEY = 'geotizer_object.v1.r054.a01'


def _batch(row_id):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': FIELD_KEY, 'row_id': row_id}],
    }


def _envelope(locator, *, value_origin='analogue'):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {
                'source_id': 's1',
                'source_type': 'knowledge_base',
                'title': 't',
                'locator': 'p1',
                'url': None,
            }
        ],
        'patches': [
            {
                'field_key': FIELD_KEY,
                'status': 'filled',
                'value': '12',
                'unit': 'т',
                'value_origin': value_origin,
                'source_refs': ['s1'],
                'source_locator': locator,
                'retrieval_note': 'n',
            }
        ],
    }


def _violations(row_id, locator, **kwargs):
    return validate_owner_envelope(_batch(row_id), _envelope(locator, **kwargs))


def test_every_resource_violation_names_the_field_not_only_the_position():
    """`patches[6]` alone cannot be looked up in `field_semantics`."""
    violations = _violations(54, {'page': 1})

    assert violations
    assert all(FIELD_KEY in violation for violation in violations)
    # The position stays: it is what identifies the patch inside the array the
    # owner is about to rewrite.
    assert all('patches[0]' in violation for violation in violations)


def test_the_estimate_state_rejection_says_which_states_are_allowed():
    """This one fired 12 times on chunk 4/6 saying only "incompatible with row
    54". Row 54 accepts exactly one state, and it was not named."""
    violations = _violations(
        54,
        {
            'entity_id': 'e1',
            'entity_scope': 'analogue_deposit',
            'estimate_state': 'author_estimate',
            'analogue_relation': ANALOGUE_RELATION_BY_ROW[54],
        },
    )

    state = next(v for v in violations if 'estimate_state' in v)
    assert str(sorted(RESOURCE_ESTIMATE_STATES_BY_ROW[54])) in state
    assert "'author_estimate'" in state


def test_the_analogue_relation_rejection_says_which_relation_is_required():
    """Rows 54, 55 and 56 each require a different one, so "incompatible with
    row 55" is not something an owner can act on without the table."""
    violations = _violations(
        55,
        {
            'entity_id': 'e1',
            'entity_scope': 'analogue_deposit',
            'estimate_state': 'analogue',
            'analogue_relation': 'same_structure',
        },
    )

    relation = next(v for v in violations if 'analogue relation' in v)
    assert repr(ANALOGUE_RELATION_BY_ROW[55]) in relation
    assert "'same_structure'" in relation
    # The row's own relation, not row 54's, which is what was actually sent.
    assert ANALOGUE_RELATION_BY_ROW[55] != ANALOGUE_RELATION_BY_ROW[54]


def test_the_entity_scope_rejection_reports_what_was_sent():
    """It already named the expected scope. It did not say what it got, so an
    owner that believed it had sent the right one had nothing to compare."""
    violations = _violations(
        54,
        {
            'entity_id': 'e1',
            'entity_scope': 'licence_area',
            'estimate_state': 'analogue',
            'analogue_relation': ANALOGUE_RELATION_BY_ROW[54],
        },
    )

    scope = next(v for v in violations if 'entity_scope' in v)
    assert RESOURCE_ENTITY_SCOPE_BY_ROW[54] in scope
    assert "'licence_area'" in scope


@pytest.mark.parametrize(
    ('locator_key', 'fragment'),
    [
        ('entity_id', 'source_locator.entity_id'),
        ('resource_estimate_id', 'source_locator.resource_estimate_id'),
        ('site_name', 'source_locator.site_name'),
    ],
)
def test_a_missing_qualifier_names_the_key_to_set(locator_key, fragment):
    """"requires entity_id" does not say where to put it. Row 50 needs all
    three of these, and each lives under `source_locator`."""
    locator = {
        'entity_id': 'e1',
        'entity_scope': RESOURCE_ENTITY_SCOPE_BY_ROW[50],
        'estimate_state': 'author_estimate',
        'resource_estimate_id': 'r1',
        'site_name': 'Участок 1',
    }
    del locator[locator_key]

    violations = _violations(50, locator, value_origin='direct')

    assert any(fragment in violation for violation in violations)


def test_an_unset_qualifier_is_reported_as_unset_not_as_empty():
    """`got ''` reads as "you sent an empty string"; the owner sent no key at
    all, and those are different mistakes."""
    violations = _violations(
        54,
        {'entity_id': 'e1', 'entity_scope': 'analogue_deposit', 'estimate_state': 'analogue'},
    )

    relation = next(v for v in violations if 'analogue relation' in v)
    assert '(unset)' in relation


def test_the_contract_the_violation_quotes_is_the_one_the_prompt_carries():
    """Two statements of the same rule, and they must not drift.

    `semantic_hint` writes the contract into the owner's prompt; these
    violations quote it back on rejection. If they were derived from different
    tables, an owner following the prompt exactly could be rejected by a rule
    that says something else -- which is unfixable from inside the loop.
    """
    hint = semantic_hint({'field_key': FIELD_KEY, 'row_id': 54})
    violations = _violations(54, {'page': 1})
    text = ' '.join(violations)

    assert str(hint['allowed_estimate_states']) in text
    assert hint['required_entity_scope'] in text
    assert repr(hint['required_analogue_relation']) in text


def test_a_conforming_resource_patch_still_passes():
    """The rules were not loosened; only what they say when they refuse."""
    assert (
        _violations(
            54,
            {
                'entity_id': 'e1',
                'entity_scope': RESOURCE_ENTITY_SCOPE_BY_ROW[54],
                'estimate_state': 'analogue',
                'analogue_relation': ANALOGUE_RELATION_BY_ROW[54],
            },
        )
        == ()
    )


def test_the_grr_work_stage_rejection_says_which_stage_the_row_wants():
    """`KB-GRR-FACTORS 1/3` spent two attempts on this one rule -- 18
    violations then 12, all of it this line -- and the line never said which
    stage the row wants. The owner was asked to guess a value the row
    declares, which is the same gap the resource rules had."""
    from open_webui.services.geotizer.semantics import GRR_WORK_STAGE_BY_ROW

    batch = {
        'batch_id': 'KB-GRR-FACTORS',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': 'k1', 'row_id': 68, 'attribute_name': 'стоимость'}],
    }
    envelope = {
        'batch_id': 'KB-GRR-FACTORS',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 's1', 'source_type': 'knowledge_base', 'title': 't', 'locator': 'p', 'url': None}
        ],
        'patches': [
            {
                'field_key': 'k1',
                'status': 'filled',
                'value': '1',
                'unit': 'руб.',
                'value_origin': 'direct',
                'source_refs': ['s1'],
                'retrieval_note': 'n',
                'source_locator': {'work_stage': 'drilling'},
            }
        ],
    }

    stage = next(
        v for v in validate_owner_envelope(batch, envelope) if 'work_stage is incompatible' in v
    )

    assert repr(GRR_WORK_STAGE_BY_ROW[68]) in stage
    assert "'drilling'" in stage
