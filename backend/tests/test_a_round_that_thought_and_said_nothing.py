"""Tests that a failed specialist round's usage block is recorded, that a reasoning-only round is distinguishable from
an empty one, and that orchestrator round usage reaches the run log.
"""

from __future__ import annotations

import asyncio
import contextvars
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


def test_the_usage_block_survives_the_boundary():
    """`specialist_failure_signal` keeps the envelope's usage block."""
    signal = specialist_failure_signal(REASONING_ONLY)

    assert signal['usage'] == {
        'finish_reason': 'stop', 'completion_tokens': 0, 'reasoning_tokens': 1841,
    }


def test_a_reasoning_only_round_is_distinguishable_from_an_empty_one():
    """`reasoning_only` is true for a round with reasoning tokens and false for a plain empty round."""
    assert specialist_failure_signal(REASONING_ONLY)['reasoning_only'] is True
    assert specialist_failure_signal(JUST_EMPTY)['reasoning_only'] is False


def test_a_provider_that_sends_no_usage_is_absent_not_zero():
    """An envelope with no usage block yields neither `usage` nor `reasoning_only`."""
    signal = specialist_failure_signal(NO_USAGE)

    assert 'usage' not in signal
    assert 'reasoning_only' not in signal


def test_only_the_named_usage_keys_are_republished():
    """Only the named usage keys are copied from the envelope."""
    signal = specialist_failure_signal(
        failed(reasoning_tokens=5, api_key='must-not-appear', internal_trace='x')
    )

    assert set(signal['usage']) == {'reasoning_tokens'}


def test_zero_reasoning_tokens_is_not_reasoning_only():
    assert specialist_failure_signal(failed(reasoning_tokens=0))['reasoning_only'] is False


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
    """A contributor round record carries no `attempt`."""
    record = specialist_round_record(
        specialist_failure_signal(JUST_EMPTY), role='contributor', batch_id='GIS-DC',
    )

    assert 'attempt' not in record
    assert record['role'] == 'contributor'


def log_of(*failures, cap=MAX_RECORDED_SPECIALIST_ROUNDS) -> SpecialistRoundLog:
    """A `SpecialistRoundLog` holding one contributor record per failure envelope."""
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
    """An empty log's stats are `{}`."""
    assert SpecialistRoundLog().stats() == {}


def test_a_complete_list_still_says_it_is_complete():
    """An uncapped log's stats state `dropped: 0`, `truncated: False` and the cap."""
    stats = log_of(JUST_EMPTY).stats()

    assert stats['dropped'] == 0
    assert stats['truncated'] is False
    assert stats['cap'] == MAX_RECORDED_SPECIALIST_ROUNDS


def test_the_count_is_not_capped_when_the_list_is():
    """Past the cap, `issued` counts every round while `recorded` stops at the cap."""
    log = log_of(*([JUST_EMPTY] * 12), cap=5)
    stats = log.stats()

    assert stats['issued'] == 12
    assert stats['recorded'] == 5
    assert stats['dropped'] == 7
    assert stats['truncated'] is True
    assert len(log.records) == 5


def test_every_sub_count_survives_the_cap_too():
    """Past the cap, every sub-count covers all issued rounds."""
    log = log_of(*([REASONING_ONLY] * 9), *([NO_USAGE] * 3), cap=4)
    stats = log.stats()

    assert stats['recorded'] == 4
    assert stats['reasoning_only'] == 9
    assert stats['unattributed'] == 3
    assert stats['by_code'] == {'completion_failed': 3, 'empty_completion': 9}
    assert sum(stats['by_agent'].values()) == stats['issued'] == 12


def test_the_counter_sits_before_the_bound_not_after_it():
    """`issued` and `dropped` count rounds the cap did not record."""
    log = log_of(*([JUST_EMPTY] * 100), cap=1)

    assert log.issued == 100
    assert log.dropped == 99
    assert log.issued != len(log.records)


def test_the_real_cap_is_the_one_the_workflow_uses():
    """The default cap is `MAX_RECORDED_SPECIALIST_ROUNDS`, 500."""
    log = SpecialistRoundLog()

    assert log.cap == MAX_RECORDED_SPECIALIST_ROUNDS == 500


def _run(
    *,
    contributor: str | None = None,
    owner_answer: str | None = None,
    round_usage_drain=None,
    as_coroutine: bool = False,
) -> Any:
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

    async def _fill():
        return await run_geotizer_workflow(
            object_name='Лекын', project_id=None, model_run_id=None, run_id=None,
            allow_draft=True, gis_call=gis_call, agent_call=agent_call,
            round_usage_drain=round_usage_drain,
        )

    if as_coroutine:
        async def _both():
            await _fill()
            return sent['run_log']

        return _both()
    asyncio.run(_fill())
    return sent['run_log']


def test_a_contributor_that_thought_and_said_nothing_reaches_the_run_log():
    """A reasoning-only contributor round reaches the run log's round stats and failures."""
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
    """Reasoning-only and empty contributor rounds produce the same number of rounds and differ only in the recorded
    `reasoning_only` count.
    """
    thinking = _run(contributor=REASONING_ONLY)
    empty = _run(contributor=JUST_EMPTY)

    rounds = thinking['specialist_round_stats']['issued']

    assert rounds == empty['specialist_round_stats']['issued']
    assert thinking['specialist_round_stats']['reasoning_only'] == rounds
    assert empty['specialist_round_stats']['reasoning_only'] == 0


class _Scope:
    """A ContextVar-backed stand-in for the orchestrator's round collection.

    `open` starts a collection for the current context, `drain` takes it and
    closes it, and a round recorded outside any collection is dropped.
    """

    def __init__(self, rounds=(), *, on_drain=None):
        self._seed = list(rounds)
        self._on_drain = on_drain
        self._var = contextvars.ContextVar('scope_rounds', default=None)
        self.opened = 0

    def open(self):
        self.opened += 1
        self._var.set(list(self._seed))

    def drain(self):
        if self._on_drain is not None:
            return self._on_drain()
        taken = self._var.get()
        self._var.set(None)
        return list(taken or [])


class _PerFillScope(_Scope):
    """A `_Scope` shared by every fill and seeded per context label."""

    def __init__(self, rounds_for):
        super().__init__()
        self._rounds_for = rounds_for
        self._label = contextvars.ContextVar('scope_label', default=None)

    def open_for(self, label):
        self._label.set(label)
        self.open()

    def open(self):
        self.opened += 1
        self._var.set(list(self._rounds_for(self._label.get())))


def test_the_drained_rounds_reach_the_run_log_measured():
    """Drained orchestrator rounds reach `specialist_round_usage` as measured."""
    rounds = [
        {'agent': 'kb', 'outcome': 'answered', 'measured': True,
         'prompt_tokens': 4210, 'completion_tokens': 880, 'finish_reason': 'stop'},
        {'agent': 'kb', 'outcome': 'tool_calls', 'measured': True,
         'prompt_tokens': 1900, 'completion_tokens': 96, 'finish_reason': 'tool_calls'},
    ]
    log = _run(round_usage_drain=_Scope(rounds))

    usage = log['specialist_round_usage']
    assert usage['source'] == 'orchestrator_rounds'
    assert usage['by_outcome']['answered']['measured'] == 1
    assert usage['by_outcome']['answered']['completion_tokens']['max'] == 880
    assert log['specialist_rounds'][0]['agent'] == 'kb'


def test_a_contour_without_the_drain_still_carries_a_denominator():
    """Without a drain, every round is counted and none is measured."""
    log = _run()

    usage = log['specialist_round_usage']
    assert usage['source'] == 'specialist_calls'
    assert usage['rounds'] >= 1
    assert usage['by_outcome']['succeeded']['measured'] == 0
    assert usage['by_outcome']['succeeded']['unmeasured'] == usage['rounds']


def test_a_drain_that_raises_does_not_take_the_fill_with_it():
    """A raising drain leaves the fill complete and the usage source `specialist_calls`."""
    def exploding():
        raise RuntimeError('older tool, different signature')

    log = _run(round_usage_drain=_Scope(on_drain=exploding))

    assert log['specialist_round_usage']['source'] == 'specialist_calls'


def test_two_fills_in_one_process_do_not_share_rounds():
    """Two sequential fills sharing a clearing drain each carry only their own rounds."""
    buffer = [{'agent': 'kb', 'outcome': 'answered', 'measured': True,
               'prompt_tokens': 100, 'completion_tokens': 10}]

    def drain():
        taken = list(buffer)
        buffer.clear()
        return taken

    scope = _Scope(on_drain=drain)
    first = _run(round_usage_drain=scope)
    buffer.extend([
        {'agent': 'gis', 'outcome': 'answered', 'measured': True,
         'prompt_tokens': 700, 'completion_tokens': 70},
        {'agent': 'gis', 'outcome': 'answered', 'measured': True,
         'prompt_tokens': 900, 'completion_tokens': 90},
    ])
    second = _run(round_usage_drain=scope)

    assert first['specialist_round_usage']['rounds'] == 1
    assert second['specialist_round_usage']['rounds'] == 2
    assert set(second['specialist_round_usage']['by_agent']) == {'gis'}
    assert first['specialist_round_usage']['by_outcome']['answered'][
        'completion_tokens']['max'] == 10


def test_the_collection_is_opened_at_the_start_of_the_fill():
    """The fill opens the round collection once, before any round is recorded."""
    scope = _Scope([{'agent': 'kb', 'outcome': 'answered', 'prompt_tokens': 11}])

    log = _run(round_usage_drain=scope)

    assert scope.opened == 1
    assert log['specialist_round_usage']['source'] == 'orchestrator_rounds'


def test_a_fill_whose_collection_never_opened_reports_unmeasured_not_zero():
    """A fill with no round collection reports its rounds as unmeasured."""
    log = _run()

    usage = log['specialist_round_usage']
    assert usage['source'] == 'specialist_calls'
    assert usage['by_outcome']['succeeded']['measured'] == 0
    assert usage['by_outcome']['succeeded']['unmeasured'] == usage['rounds']


def test_two_concurrent_fills_each_carry_only_their_own_rounds():
    rounds = {
        'A': [{'agent': 'A', 'outcome': 'answered', 'prompt_tokens': 100,
               'completion_tokens': 10}] * 3,
        'B': [{'agent': 'B', 'outcome': 'answered', 'prompt_tokens': 700,
               'completion_tokens': 70}] * 5,
    }
    scope = _PerFillScope(lambda label: rounds.get(label, []))

    async def fill(label):
        scope._label.set(label)
        return await _run(round_usage_drain=scope, as_coroutine=True)

    async def both():
        return await asyncio.gather(fill('A'), fill('B'))

    first, second = asyncio.run(both())

    assert first['specialist_round_usage']['rounds'] == 3
    assert second['specialist_round_usage']['rounds'] == 5
    assert set(first['specialist_round_usage']['by_agent']) == {'A'}
    assert set(second['specialist_round_usage']['by_agent']) == {'B'}
    for log in (first, second):
        assert log['specialist_round_usage']['by_outcome']['answered']['measured'] > 0


def test_a_shared_module_level_collector_would_fail_this(monkeypatch):
    """A collector backed by one shared list does not give two concurrent fills 3 and 5 rounds apiece."""

    class _SharedList(_Scope):
        def __init__(self, rounds_for):
            super().__init__()
            self._rounds_for = rounds_for
            self._label = contextvars.ContextVar('label', default=None)
            self._shared: list = []

        def open(self):
            self.opened += 1
            self._shared.extend(self._rounds_for(self._label.get()))

        def drain(self):
            taken, self._shared = list(self._shared), []
            return taken

    rounds = {
        'A': [{'agent': 'A', 'outcome': 'answered', 'prompt_tokens': 1}] * 3,
        'B': [{'agent': 'B', 'outcome': 'answered', 'prompt_tokens': 2}] * 5,
    }
    scope = _SharedList(lambda label: rounds.get(label, []))

    async def fill(label):
        scope._label.set(label)
        return await _run(round_usage_drain=scope, as_coroutine=True)

    async def both():
        return await asyncio.gather(fill('A'), fill('B'))

    first, second = asyncio.run(both())
    agents = set(first['specialist_round_usage']['by_agent']) | set(
        second['specialist_round_usage'].get('by_agent') or {}
    )

    assert agents == {'A', 'B'} or (
        first['specialist_round_usage']['rounds'],
        second['specialist_round_usage']['rounds'],
    ) != (3, 5)
