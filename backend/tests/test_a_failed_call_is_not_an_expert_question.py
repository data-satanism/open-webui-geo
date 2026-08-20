"""A cell the run never got an answer for is not a question for a geologist.

`requires_expert_review` was carrying both meanings. Run `6976094d` finished
with 35 review cells: 18 where no owner response in three attempts contained a
usable envelope, 17 rejected by the deterministic field contract, and zero
geological. The card told a geologist to inspect all 35.

The GIS service now has `agent_contract_failed` as a status of its own. This
side has to emit it -- and has to keep working against a deployment that has
never heard of it, because the service ships from git and the Workspace tools
are pasted by hand. A status the deployed service rejects does not degrade to a
worse label, it loses the whole envelope.
"""

from __future__ import annotations

import asyncio

from open_webui.services.artifacts.geotizer.owner_envelope import (
    AGENT_FAILURE_STATUS,
    EXPERT_REVIEW_STATUS,
    build_batch_tasks,
    failure_status_for,
    owner_failure_envelope,
)
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.artifacts.geotizer.workflow import _produce_valid_owner_envelope

from test_geotizer_orchestration import batch


def _batch(*, advertises: bool, batch_id: str = 'KB-GRR-FACTORS'):
    value = batch()
    value['batch_id'] = batch_id
    if advertises:
        value['accepted_field_statuses'] = [
            'agent_contract_failed',
            'conflicted',
            'filled',
            'not_applicable',
            'not_found',
            'requires_expert_review',
        ]
    return value


# -- what the run is allowed to say ----------------------------------------


def test_a_service_that_accepts_the_status_gets_it():
    assert failure_status_for(_batch(advertises=True)) == AGENT_FAILURE_STATUS


def test_a_service_that_has_not_heard_of_it_gets_the_old_status():
    """Not a downgrade for its own sake. An unknown status is rejected as
    `invalid_field_status` and takes every patch in the envelope with it."""
    assert failure_status_for(_batch(advertises=False)) == EXPERT_REVIEW_STATUS


def test_assemble_keeps_the_expert_status_even_where_the_new_one_is_offered():
    """`ASSEMBLE`'s fallback puts a review hypothesis in the cell. Accepting or
    rejecting that hypothesis is a geological judgement, whatever produced it.
    Every other batch's fallback leaves nothing to judge."""
    assert (
        failure_status_for(_batch(advertises=True, batch_id='ASSEMBLE'))
        == EXPERT_REVIEW_STATUS
    )


# -- and what it actually writes -------------------------------------------


def _fallback(*, advertises: bool):
    return owner_failure_envelope(
        _batch(advertises=advertises),
        run_id='run-contract-failure',
        attempts=3,
        feedback=['patches[0].status is unsupported'],
        attempt_diagnostics=[
            {'attempt': n, 'response_mode': 'unparseable', 'text_prefix': 'TimeoutError'}
            for n in (1, 2, 3)
        ],
    )


def test_the_fallback_envelope_carries_the_new_status():
    statuses = {patch['status'] for patch in _fallback(advertises=True)['patches']}

    assert statuses == {AGENT_FAILURE_STATUS}


def test_the_fallback_envelope_falls_back_with_the_service():
    statuses = {patch['status'] for patch in _fallback(advertises=False)['patches']}

    assert statuses == {EXPERT_REVIEW_STATUS}


def test_the_fallback_still_says_why():
    """The split must not cost the reason. Both halves of the card need it:
    the marker says who should look, the note says what happened."""
    note = _fallback(advertises=True)['patches'][0]['retrieval_note']

    assert 'usable envelope' in note


def test_this_repository_accepts_the_envelope_it_writes():
    """The wiring, not the helper. `_produce_valid_owner_envelope` runs its own
    fallback back through `validate_owner_envelope` -- a status the local
    vocabulary rejected would fail the run here, before the service ever saw
    it, and every test above would still have passed."""
    value = _batch(advertises=True)

    assert list(validate_owner_envelope(value, _fallback(advertises=True))) == []


def test_a_run_whose_owner_never_answers_ends_in_the_new_status():
    """Driven through the real loop rather than the fallback builder, because
    six wiring mutations have survived a tested helper nothing called."""
    value = _batch(advertises=True, batch_id='GIS-DC')
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')

    async def never_answers(*args, **kwargs):
        return ''

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-contract-failure',
            agent_call=never_answers,
            datacube=None,
        )
    )

    assert {patch['status'] for patch in result['patches']} == {AGENT_FAILURE_STATUS}


def test_the_same_run_against_an_older_service_ends_in_the_old_status():
    value = _batch(advertises=False, batch_id='GIS-DC')
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')

    async def never_answers(*args, **kwargs):
        return ''

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-contract-failure',
            agent_call=never_answers,
            datacube=None,
        )
    )

    assert {patch['status'] for patch in result['patches']} == {EXPERT_REVIEW_STATUS}


def test_a_contract_failure_may_not_carry_a_value():
    """The status means no answer arrived. A value under it is a value from
    nowhere, and the deterministic check says so rather than letting it
    through to a cell that reads as both failed and filled."""
    value = _batch(advertises=True)
    envelope = _fallback(advertises=True)
    envelope['patches'][0]['value'] = 'смuggled in'

    violations = validate_owner_envelope(value, envelope)

    assert any('must use value=null' in item for item in violations)
