"""Nothing reads `reasoning_content`, and an empty round hides inside that.

Two identical requests to `kb-agent` returned the same tokens in different
channels — once as the answer, once inside a reasoning block. Open WebUI is
configured with `Теги рассуждения: Включено` and `Вызов функции: Нативный`, so
`<think>` is parsed out of the content before the loop sees it.

A round whose work lands in that channel yields no `tool_calls` and no content.
The loop reads only those two, so the round produced nothing — and from there
two runs of one build are on different paths for the rest of the batch. That is
the shape of the divergence the audit found at layer 6: different tool and
different query on the first call of the first chunk, in every batch, with no
prior-round content to have accumulated from.

The Workspace tool already captures the cause: `empty_completion` carries
`finish_reason`, `completion_tokens` and `reasoning_tokens`. This repository
was throwing that block away at the boundary and recording contributor rounds
nowhere at all.

**Measurement only.** Nothing here branches on `reasoning_only`. Whether to
read the reasoning channel, or to treat a reasoning-only response as a failed
round, is a decision that needs the number first; what is not acceptable is
that a reasoning-only round and an empty one are currently the same event.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from open_webui.services.artifacts.geotizer.owner_envelope import (
    MAX_RECORDED_SPECIALIST_ROUNDS,
    SpecialistRoundLog,
    specialist_failure_signal,
    specialist_round_record,
)
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

from tests.test_run_notes import batch, envelope


def failed(agent='kb', code='empty_completion', **usage) -> str:
    """The envelope the Workspace tool returns, verbatim in shape."""
    payload: dict[str, Any] = {
        'status': 'specialist_failed',
        'agent': agent,
        'code': code,
        'retryable': True,
        'instruction': 'One retry is acceptable; do not loop.',
        'detail': 'The model returned no content.',
    }
    if usage:
        payload['usage'] = usage
    return json.dumps(payload, ensure_ascii=False)


REASONING_ONLY = failed(finish_reason='stop', completion_tokens=0, reasoning_tokens=1841)
JUST_EMPTY = failed(finish_reason='stop', completion_tokens=0)
NO_USAGE = failed(code='completion_failed')


# ------------------------------------------------------- the boundary read


def test_the_usage_block_survives_the_boundary():
    """It was already being sent and already being dropped."""
    signal = specialist_failure_signal(REASONING_ONLY)

    assert signal['usage'] == {
        'finish_reason': 'stop', 'completion_tokens': 0, 'reasoning_tokens': 1841,
    }


def test_a_reasoning_only_round_is_distinguishable_from_an_empty_one():
    """The whole point. Today they are the same event."""
    assert specialist_failure_signal(REASONING_ONLY)['reasoning_only'] is True
    assert specialist_failure_signal(JUST_EMPTY)['reasoning_only'] is False


def test_a_provider_that_sends_no_usage_is_absent_not_zero():
    """A zero would read as «the model wrote nothing» when the truth is «the
    provider did not say»."""
    signal = specialist_failure_signal(NO_USAGE)

    assert 'usage' not in signal
    assert 'reasoning_only' not in signal


def test_only_the_named_usage_keys_are_republished():
    """This lands in a run artefact, so a provider sending something larger
    must not silently widen what the record carries."""
    signal = specialist_failure_signal(
        failed(reasoning_tokens=5, api_key='must-not-appear', internal_trace='x')
    )

    assert set(signal['usage']) == {'reasoning_tokens'}


def test_zero_reasoning_tokens_is_not_reasoning_only():
    assert specialist_failure_signal(failed(reasoning_tokens=0))['reasoning_only'] is False


# --------------------------------------------------------- the placement


def test_the_record_says_which_round_not_just_that_one_failed():
    record = specialist_round_record(
        specialist_failure_signal(REASONING_ONLY),
        role='owner', batch_id='KB-GRR-FACTORS', chunk='2/3', attempt=1,
    )

    assert record['role'] == 'owner'
    assert record['batch_id'] == 'KB-GRR-FACTORS'
    assert record['chunk'] == '2/3'
    assert record['attempt'] == 1
    assert record['reasoning_only'] is True


def test_a_contributor_record_carries_no_attempt():
    """Nothing retries a contributor, so an attempt number would be invented."""
    record = specialist_round_record(
        specialist_failure_signal(JUST_EMPTY), role='contributor', batch_id='GIS-DC',
    )

    assert 'attempt' not in record
    assert record['role'] == 'contributor'


# ------------------------------------------------------------ the counts


def log_of(*failures, cap=MAX_RECORDED_SPECIALIST_ROUNDS) -> SpecialistRoundLog:
    """`failures`, not `envelopes`: `envelope` is the owner-envelope fixture
    imported above, and shadowing it here would leave two different meanings
    for one name in one file."""
    log = SpecialistRoundLog(cap=cap)
    for failure in failures:
        log.add(
            specialist_round_record(
                specialist_failure_signal(failure), role='contributor', batch_id='b',
            )
        )
    return log


def test_the_stats_answer_the_question_as_a_number():
    stats = log_of(REASONING_ONLY, REASONING_ONLY, JUST_EMPTY, NO_USAGE).stats()

    assert stats['issued'] == 4
    assert stats['recorded'] == 4
    assert stats['reasoning_only'] == 2
    assert stats['unattributed'] == 1
    assert stats['by_code'] == {'completion_failed': 1, 'empty_completion': 3}


def test_no_failed_round_produces_no_stats_block():
    """A key that is always present is a key a reader has to interpret."""
    assert SpecialistRoundLog().stats() == {}


def test_a_complete_list_still_says_it_is_complete():
    """`dropped: 0` printed rather than implied. A reader who has to notice an
    absence to learn the list is whole is doing the cap's bookkeeping."""
    stats = log_of(JUST_EMPTY).stats()

    assert stats['dropped'] == 0
    assert stats['truncated'] is False
    assert stats['cap'] == MAX_RECORDED_SPECIALIST_ROUNDS


# ------------------------------------------------------- exceeding the cap


def test_the_count_is_not_capped_when_the_list_is():
    """The defect this replaced: 600 failures reported as `rounds: 500` with
    nothing saying the other hundred existed. A cap nobody has watched behave
    is a cap nobody has watched.

    Driven past the bound rather than asserted about, because the bug was in
    the arithmetic and the arithmetic looked right."""
    log = log_of(*([JUST_EMPTY] * 12), cap=5)
    stats = log.stats()

    assert stats['issued'] == 12
    assert stats['recorded'] == 5
    assert stats['dropped'] == 7
    assert stats['truncated'] is True
    assert len(log.records) == 5


def test_every_sub_count_survives_the_cap_too():
    """A sub-count of a capped population is capped. `reasoning_only` is the
    number the whole record exists to produce, and understating it errs in the
    direction nobody checks."""
    log = log_of(*([REASONING_ONLY] * 9), *([NO_USAGE] * 3), cap=4)
    stats = log.stats()

    assert stats['recorded'] == 4
    assert stats['reasoning_only'] == 9
    assert stats['unattributed'] == 3
    assert stats['by_code'] == {'completion_failed': 3, 'empty_completion': 9}
    assert sum(stats['by_agent'].values()) == stats['issued'] == 12


def test_the_counter_sits_before_the_bound_not_after_it():
    """The trap inside the fix. An `issued` counter placed after the same
    bound that truncates the list reports zero dropped on a run that dropped a
    hundred, and `dropped = issued - len(records)` looks correct while doing
    it. Asserted on a log driven far past its cap, where the two would be
    equal if the counting happened at the wrong end."""
    log = log_of(*([JUST_EMPTY] * 100), cap=1)

    assert log.issued == 100
    assert log.dropped == 99
    assert log.issued != len(log.records)


def test_the_real_cap_is_the_one_the_workflow_uses():
    """A test that only ever exercises a cap of five has not watched the cap
    the run has."""
    log = SpecialistRoundLog()

    assert log.cap == MAX_RECORDED_SPECIALIST_ROUNDS == 500


# ------------------------------------------------- on the run's own artefact


def _run(*, contributor: str | None = None, owner_answer: str | None = None) -> dict[str, Any]:
    value = batch()
    sent: dict[str, Any] = {}
    filled = [{'field_key': 'f1', 'status': 'filled', 'source_locator': {'document_id': 'd'}}]

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting', 'run_id': 'run-think',
                'object_name': 'Лекын', 'datacube': {}, 'next_batch': value,
                'fields': filled, 'batches_total': 1,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting', 'run_id': 'run-think',
                'next_batch': None, 'fields': filled,
            }
        sent.update(payload)
        return {
            'workflow_status': 'finalized', 'run_id': 'run-think', 'fields': filled,
            'xlsx': {'download_path': '/geotizer/files/run-think/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return contributor if contributor is not None else 'bounded evidence'
        return owner_answer if owner_answer is not None else json.dumps(
            envelope(), ensure_ascii=False
        )

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын', project_id=None, model_run_id=None, run_id=None,
            allow_draft=True, gis_call=gis_call, agent_call=agent_call,
        )
    )
    return sent['run_log']


def test_a_contributor_that_thought_and_said_nothing_reaches_the_run_log():
    """The owner loop has recognised this envelope since run `6976094d`; the
    six contributors around it did not, so evidence that never arrived left no
    trace anywhere."""
    log = _run(contributor=REASONING_ONLY)

    assert log['specialist_round_stats']['reasoning_only'] >= 1
    assert all(
        entry['role'] == 'contributor' for entry in log['specialist_round_failures']
    )


def test_the_record_names_the_batch_the_round_belonged_to():
    entry = _run(contributor=REASONING_ONLY)['specialist_round_failures'][0]

    assert entry['batch_id'] == 'GIS-DC'
    assert entry['usage']['reasoning_tokens'] == 1841


def test_a_run_where_every_round_answered_carries_neither_key():
    log = _run()

    assert 'specialist_round_failures' not in log
    assert 'specialist_round_stats' not in log


def test_nothing_branches_on_reasoning_only_yet():
    """Measure, do not act. A reasoning-only contributor and a plainly empty
    one must reach the same card — the difference is recorded and nothing
    reads it."""
    thinking = _run(contributor=REASONING_ONLY)
    empty = _run(contributor=JUST_EMPTY)

    rounds = thinking['specialist_round_stats']['issued']

    assert rounds == empty['specialist_round_stats']['issued']
    assert thinking['specialist_round_stats']['reasoning_only'] == rounds
    assert empty['specialist_round_stats']['reasoning_only'] == 0
