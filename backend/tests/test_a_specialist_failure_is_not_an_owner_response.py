"""A specialist failure returned in place of an owner envelope is recognised
and reported as such, not as an owner contract failure."""

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
    """A `specialist_failed` mention inside an owner envelope's patches is not a specialist failure."""
    value = envelope()
    value['patches'][0]['retrieval_note'] = 'kb returned specialist_failed for this row'

    assert specialist_failure_signal(json.dumps(value, ensure_ascii=False)) is None


def test_empty_and_prose_are_not_the_signal():
    assert specialist_failure_signal('') is None
    assert specialist_failure_signal('Не удалось найти данные.') is None


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
    """Consecutive specialist failures stop the loop after `MAX_CONSECUTIVE_SPECIALIST_FAILURES` calls."""
    _, calls = _run_returning(SPECIALIST_FAILED)

    assert calls == MAX_CONSECUTIVE_SPECIALIST_FAILURES
    assert calls < MAX_OWNER_ATTEMPTS


CONTEXT_OVERFLOW_FAILED = (
    '{"status": "specialist_failed", "agent": "gis", '
    '"code": "context_window_exceeded", "retryable": false, '
    '"detail": "prompt 117233 of 150000 tokens; narrow the tool request"}'
)


def test_a_failure_the_specialist_calls_final_is_not_retried():
    """A specialist failure with `retryable: false` stops the loop after one call."""
    _, calls = _run_returning(CONTEXT_OVERFLOW_FAILED)

    assert calls == 1
    assert calls < MAX_CONSECUTIVE_SPECIALIST_FAILURES


def test_a_retryable_failure_is_still_retried():
    """A specialist failure with `retryable: true` is retried."""
    _, calls = _run_returning(SPECIALIST_FAILED)

    assert calls == MAX_CONSECUTIVE_SPECIALIST_FAILURES


def test_an_envelope_with_no_retryable_field_is_retried():
    """A specialist failure with no `retryable` field is retried."""
    _, calls = _run_returning(
        '{"status": "specialist_failed", "agent": "kb", "code": "completion_failed"}'
    )

    assert calls == MAX_CONSECUTIVE_SPECIALIST_FAILURES


def test_a_specialist_failure_between_two_real_attempts_does_not_stop_the_run():
    """A single specialist failure between two other attempts does not stop the loop."""
    _, calls = _run_returning('not an envelope', SPECIALIST_FAILED, 'still not an envelope')

    assert calls == MAX_OWNER_ATTEMPTS


def test_the_card_names_the_specialist_and_not_the_field_contract():
    """The cell note names the specialist's failure and not the field contract."""
    result, _ = _run_returning(SPECIALIST_FAILED)

    note = result['patches'][0]['retrieval_note']
    assert 'kb specialist reported completion_failed' in note
    assert 'deterministic field contract' not in note


def test_the_signal_reaches_the_state_beside_the_attempt_feedback():
    """Each specialist failure is recorded in the patch locator's `specialist_failures`."""
    result, _ = _run_returning(SPECIALIST_FAILED)

    locator = result['patches'][0]['source_locator']
    assert [item['code'] for item in locator['specialist_failures']] == [
        'completion_failed'
    ] * MAX_CONSECUTIVE_SPECIALIST_FAILURES


def test_a_batch_the_owner_really_did_fail_still_says_so():
    """An owner that returned only unparseable output is still reported as having no usable envelope."""
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
    """A lone specialist failure is recorded in `specialist_failures` while the note follows how the batch ended."""
    result, calls = _run_returning(
        'not an envelope', SPECIALIST_FAILED, 'still not an envelope'
    )

    assert calls == MAX_OWNER_ATTEMPTS
    patch = result['patches'][0]
    assert 'usable envelope' in patch['retrieval_note']
    assert [item['code'] for item in patch['source_locator']['specialist_failures']] == [
        'completion_failed'
    ]


SETUP_TIMEOUT = json.dumps(
    {
        'status': 'specialist_failed',
        'agent': 'kb',
        'code': 'setup_timeout',
        'retryable': True,
        'instruction': 'One retry is acceptable; do not loop.',
        'seconds': 60,
        'detail': (
            'The tool surface did not build within 60s, so the specialist '
            'never ran. A tool server or MCP endpoint is unreachable or not '
            'answering; check the KB_TOOL_IDS and *_OPENAPI_BASE_URL valves '
            'and the servers they name.'
        ),
    },
    ensure_ascii=False,
)


def test_a_specialist_that_cannot_reach_its_tool_server_is_recognised():
    signal = specialist_failure_signal(SETUP_TIMEOUT)

    assert signal is not None
    assert signal['code'] == 'setup_timeout'


def test_the_cell_carries_the_code_and_the_thing_to_check():
    """The cell note carries the specialist's code and detail, not a field-contract violation."""
    result, calls = _run_returning(SETUP_TIMEOUT)

    note = result['patches'][0]['retrieval_note']
    assert 'kb specialist reported setup_timeout' in note
    assert 'KB_TOOL_IDS' in note
    assert 'batch_id' not in note


def test_the_detail_is_bounded_before_it_reaches_a_cell():
    """`specialist_failure_signal` bounds the failure detail to under 500 characters."""
    long_detail = json.dumps(
        {'status': 'specialist_failed', 'agent': 'kb', 'code': 'x', 'detail': 'и' * 5000},
        ensure_ascii=False,
    )
    signal = specialist_failure_signal(long_detail)

    assert signal is not None
    assert len(signal['detail']) < 500
