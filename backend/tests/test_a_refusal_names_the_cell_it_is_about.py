"""A refusal's note separates the violations naming its own cell from those naming other cells of the chunk."""

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
    """The chunk's validation feedback stays on every cell of the refused chunk."""
    for key in (OFFENDER, BYSTANDER):
        assert 'Validation feedback:' in _note(_envelope(), key)
        assert 'entity_id' in _note(_envelope(), key)


def test_a_deadline_stop_still_claims_nothing_about_violations():
    """A deadline stop carries no validation feedback and no claim about which cell a violation names."""
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
    """A chunk that failed before per-cell validation says no violation names any cell."""
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
    """A violation naming a key is not attributed to a shorter key that is its prefix."""
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
