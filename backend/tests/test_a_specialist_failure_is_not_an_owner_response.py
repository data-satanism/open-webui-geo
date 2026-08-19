"""A batch that died in the specialist did not fail the owner contract.

`KB-GRR-FACTORS` on run `6976094d`, chunk 2/3. All three attempts returned

    {"status": "specialist_failed", "agent": "kb", "code": "completion_failed",
     "retryable": true, "instruction": "One retry is acceptable; do not loop."}

The run validated that as an owner envelope. It found no `batch_id`,
`producer`, `policy_version` or `template_version` in it and said so -- six
violations an attempt, eighteen across the batch, every one telling the model
to fix a field in a message the model never wrote. Then it sent the same
prompt again, twice, against an envelope that had already asked it not to.

18 of the 42 GRR cells ended `requires_expert_review` this way, and the card
told a geologist that the deterministic field contract had rejected them.
"""

from __future__ import annotations

import asyncio
import json

from open_webui.services.artifacts.geotizer.owner_envelope import (
    MAX_CONSECUTIVE_SPECIALIST_FAILURES,
    build_batch_tasks,
    owner_failure_envelope,
    specialist_failure_signal,
)
from open_webui.services.artifacts.geotizer.workflow import (
    MAX_OWNER_ATTEMPTS,
    _produce_valid_owner_envelope,
)

from test_geotizer_orchestration import batch, envelope

#: The response verbatim, as `KB-GRR-FACTORS` chunk 2/3 returned it three
#: times. Kept whole rather than reduced to its `status` key, because what has
#: to be recognised is the message the specialist actually sends.
SPECIALIST_FAILED = json.dumps(
    {
        'status': 'specialist_failed',
        'agent': 'kb',
        'code': 'completion_failed',
        'retryable': True,
        'instruction': 'One retry is acceptable; do not loop.',
        'detail': 'TimeoutError: ',
    },
    ensure_ascii=False,
)


# -- recognising it ---------------------------------------------------------


def test_the_specialist_failure_envelope_is_recognised():
    signal = specialist_failure_signal(SPECIALIST_FAILED)

    assert signal is not None
    assert signal['agent'] == 'kb'
    assert signal['code'] == 'completion_failed'


def test_a_fenced_specialist_failure_is_recognised():
    signal = specialist_failure_signal(f'```json\n{SPECIALIST_FAILED}\n```')

    assert signal is not None


def test_an_owner_envelope_is_not_a_specialist_failure():
    assert specialist_failure_signal(json.dumps(envelope(), ensure_ascii=False)) is None


def test_the_words_alone_are_not_the_signal():
    """The marker has to be the payload's own `status`. An owner reporting a
    contributor's failure inside its patches is an owner response."""
    value = envelope()
    value['patches'][0]['retrieval_note'] = 'kb returned specialist_failed for this row'

    assert specialist_failure_signal(json.dumps(value, ensure_ascii=False)) is None


def test_empty_and_prose_are_not_the_signal():
    assert specialist_failure_signal('') is None
    assert specialist_failure_signal('Не удалось найти данные.') is None


# -- and acting on it -------------------------------------------------------


def _run_returning(*responses):
    value = batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    calls = []

    async def agent_call(*args, **kwargs):
        calls.append(1)
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-specialist-failure',
            agent_call=agent_call,
            datacube=None,
        )
    )
    return result, len(calls)


def test_a_run_of_specialist_failures_stops_instead_of_spending_a_third_call():
    """The envelope says «One retry is acceptable; do not loop» and the run
    looped. Two attempts, not three -- the same rule an empty response
    follows."""
    _, calls = _run_returning(SPECIALIST_FAILED)

    assert calls == MAX_CONSECUTIVE_SPECIALIST_FAILURES
    assert calls < MAX_OWNER_ATTEMPTS


def test_a_specialist_failure_between_two_real_attempts_does_not_stop_the_run():
    """Chunk 1/3 went parsed, specialist_failed, parsed. Only a *run* of
    failures ends the batch; a single one in the middle is a blip."""
    _, calls = _run_returning('not an envelope', SPECIALIST_FAILED, 'still not an envelope')

    assert calls == MAX_OWNER_ATTEMPTS


def test_the_card_names_the_specialist_and_not_the_field_contract():
    """`batch_id: expected 'KB-GRR-FACTORS', got None` sends a reader to the
    owner prompt. The specialist's timeout is where the cells were lost."""
    result, _ = _run_returning(SPECIALIST_FAILED)

    note = result['patches'][0]['retrieval_note']
    assert 'kb specialist reported completion_failed' in note
    assert 'deterministic field contract' not in note


def test_the_signal_reaches_the_state_beside_the_attempt_feedback():
    """Named separately, because a batch that died in the specialist and a
    batch the owner contract refused send a reader to different code."""
    result, _ = _run_returning(SPECIALIST_FAILED)

    locator = result['patches'][0]['source_locator']
    assert [item['code'] for item in locator['specialist_failures']] == [
        'completion_failed'
    ] * MAX_CONSECUTIVE_SPECIALIST_FAILURES


def test_a_batch_the_owner_really_did_fail_still_says_so():
    """The new sentence must not swallow the old one. An owner that wrote
    prose three times is still an owner failure."""
    fallback = owner_failure_envelope(
        batch(),
        run_id='run-owner-failure',
        attempts=3,
        feedback=['patches[0] missing source_refs'],
        attempt_diagnostics=[
            {'attempt': n, 'response_mode': 'unparseable'} for n in (1, 2, 3)
        ],
    )

    assert 'usable envelope' in fallback['patches'][0]['retrieval_note']


def test_a_lone_specialist_failure_is_still_recorded_against_the_batch():
    """Chunk 1/3 lost its middle attempt in the specialist and the run reported
    a contract violation for the batch. Both are true and both are kept: the
    sentence follows how the batch ended, the record keeps everything it saw."""
    result, calls = _run_returning(
        'not an envelope', SPECIALIST_FAILED, 'still not an envelope'
    )

    assert calls == MAX_OWNER_ATTEMPTS
    patch = result['patches'][0]
    assert 'usable envelope' in patch['retrieval_note']
    assert [item['code'] for item in patch['source_locator']['specialist_failures']] == [
        'completion_failed'
    ]
