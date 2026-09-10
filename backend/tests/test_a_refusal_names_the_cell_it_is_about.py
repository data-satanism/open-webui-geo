"""Fifteen cells failed, and none of them was mentioned in its own reason.

Run `06d1f455` marked fifteen cells `agent_contract_failed` in
`KB-RESOURCE-TECH`. Measured across all fifteen:

    15 of 15   carried feedback that never names the cell's own field key
    52 of 56   violations named one cell, `geotizer_object.v1.r054.a01`
    that cell  finished the run `filled`, «Харбейское месторождение»

So it was one violation, not fifteen — and a reader opening `r053.a01` was
told the problem is a missing `entity_id` on a row that does not have one
missing. The chunk really was refused as a whole and the objections are why
nothing from it was accepted, so they stay on every cell of the chunk. What
they may not do is present themselves as that cell's own reason.

«A reason a cell carries must be true of that cell» is the rule that retired
the stale «Значение не найдено» sentences; this is the same rule one layer
out, on the reason a refusal writes.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    owner_failure_envelope,
)

OFFENDER = 'geotizer_object.v1.r054.a01'
BYSTANDER = 'geotizer_object.v1.r053.a01'
VIOLATIONS = [
    f'patches[6] {OFFENDER} resource field requires entity_id: set '
    'source_locator.entity_id to the identifier of the analogue_deposit',
    f'patches[6] {OFFENDER} resource entity_scope must be analogue_deposit; '
    "got '(unset)'.",
]


def _envelope(**overrides):
    batch = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'owner_chunk': {'index': 1, 'total': 3},
        'accepted_field_statuses': ['agent_contract_failed'],
        'fields': [{'field_key': OFFENDER}, {'field_key': BYSTANDER}],
    }
    batch.update(overrides)
    return owner_failure_envelope(
        batch, run_id='r', attempts=2, feedback=VIOLATIONS
    )


def _note(envelope, field_key):
    return next(
        patch['retrieval_note']
        for patch in envelope['patches']
        if patch['field_key'] == field_key
    )


def test_a_cell_no_violation_names_says_so():
    note = _note(_envelope(), BYSTANDER)

    assert 'No violation names this cell' in note


def test_the_cell_the_violations_are_about_gets_them_named():
    note = _note(_envelope(), OFFENDER)

    assert 'Violations naming this cell' in note
    assert 'No violation names this cell' not in note


def test_the_chunks_objections_stay_on_every_cell():
    """They are why nothing from the chunk was accepted, so removing them from
    the bystanders would trade a false reason for no reason at all."""
    for key in (OFFENDER, BYSTANDER):
        assert 'Validation feedback:' in _note(_envelope(), key)
        assert 'entity_id' in _note(_envelope(), key)


def test_a_deadline_stop_still_claims_nothing_about_violations():
    """Nothing was validated, so there is no objection to be about anything."""
    envelope = owner_failure_envelope(
        {
            'batch_id': 'KB-RESOURCE-TECH',
            'producer': 'kb',
            'fields': [{'field_key': BYSTANDER}],
            'accepted_field_statuses': ['agent_contract_failed'],
        },
        run_id='r',
        attempts=1,
        feedback=[],
        stopped_by_deadline=True,
    )
    note = _note(envelope, BYSTANDER)

    assert 'Validation feedback' not in note
    assert 'names this cell' not in note


def test_a_chunk_that_failed_before_validation_names_no_cells_at_all():
    """The third case, and the one the first version of this clause got wrong.

    A chunk can fail before its answer is checked cell by cell: the specialist
    reports `completion_failed`, the owner returns nothing, the envelope will
    not parse. There are then no per-cell objections about ANY cell, and
    saying «the objections below are about other cells in it» sends a reader
    hunting for objections that do not exist — the same misattribution this
    clause exists to remove, arriving through a different input.
    """
    envelope = owner_failure_envelope(
        {
            'batch_id': 'KB-RESOURCE-TECH',
            'producer': 'kb',
            'fields': [{'field_key': OFFENDER}, {'field_key': BYSTANDER}],
            'accepted_field_statuses': ['agent_contract_failed'],
        },
        run_id='r',
        attempts=2,
        feedback=['kb reported completion_failed on attempt 2; no owner envelope was produced.'],
    )

    for key in (OFFENDER, BYSTANDER):
        note = _note(envelope, key)
        assert 'No violation names any cell' in note
        assert 'about other cells' not in note


def test_a_longer_key_beginning_with_this_one_is_not_this_one():
    """`…r054.a1` and `…r054.a10` differ by a character a substring test
    cannot see. No key in today's catalogue is a prefix of another; this is
    the check that notices when one becomes so."""
    short = 'geotizer_object.v1.r054.a1'
    long = 'geotizer_object.v1.r054.a10'
    envelope = owner_failure_envelope(
        {
            'batch_id': 'KB-RESOURCE-TECH',
            'producer': 'kb',
            'fields': [{'field_key': short}, {'field_key': long}],
            'accepted_field_statuses': ['agent_contract_failed'],
        },
        run_id='r',
        attempts=2,
        feedback=[f'patches[0] {long} resource entity_scope must be analogue_deposit'],
    )

    assert 'No violation names this cell' in _note(envelope, short)
    assert 'Violations naming this cell' in _note(envelope, long)
