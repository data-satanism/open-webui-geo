"""`SpecialistRoundLog.observe_round` counts every specialist round, measured or not,
beside the failure record."""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import SpecialistRoundLog


def burn(prompt_tokens=50_000, agent='kb', batch='KB-STUDY'):
    return {
        'agent': agent, 'code': 'empty_completion', 'retryable': True,
        'finish_reason': 'length', 'completion_tokens': 16_384,
        'prompt_tokens': prompt_tokens, 'total_tokens': prompt_tokens + 16_384,
    }


def log_with(rounds):
    log = SpecialistRoundLog()
    for entry in rounds:
        log.observe_round(**entry)
    return log


class TestTheDenominatorExists:
    def test_a_successful_round_is_counted(self):
        """A successful round is counted in `usage_stats`."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'KB-STUDY', 'outcome': 'succeeded'},
            {'agent': 'kb', 'batch_id': 'KB-STUDY', 'outcome': 'burnt', 'usage': burn()},
        ])

        stats = log.usage_stats()
        assert stats['rounds'] == 2
        assert stats['by_outcome']['succeeded']['rounds'] == 1
        assert stats['by_outcome']['burnt']['rounds'] == 1

    def test_a_successful_round_leaves_no_failure_record(self):
        """A successful round leaves `records` and `stats` empty and is still counted."""
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])

        assert log.records == []
        assert log.stats() == {}
        assert log.usage_stats()['rounds'] == 1

    def test_the_failure_record_is_made_by_the_same_call(self):
        """One `observe_round` call both records the failure and counts the round."""
        log = SpecialistRoundLog()
        log.observe_round(
            agent='kb', batch_id='KB-STUDY', chunk={'index': 2, 'total': 5},
            outcome='burnt', usage=burn(),
            failure={'agent': 'kb', 'code': 'empty_completion', 'batch_id': 'KB-STUDY'},
        )

        assert log.stats()['issued'] == 1
        assert log.usage_stats()['rounds'] == 1

    def test_no_rounds_at_all_yields_no_block(self):
        """With no rounds, `usage_stats` is an empty mapping."""
        assert SpecialistRoundLog().usage_stats() == {}


class TestMeasuredAndUnmeasuredAreNeverFolded:
    def test_a_round_with_no_usage_is_counted_and_named_unmeasured(self):
        """A round without usage is counted as unmeasured."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'},
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'},
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn()},
        ])

        block = log.usage_stats()['by_outcome']
        assert block['succeeded'] == {'rounds': 2, 'measured': 0, 'unmeasured': 2}
        assert block['burnt']['measured'] == 1
        assert block['burnt']['unmeasured'] == 0

    def test_a_percentile_is_never_published_for_a_population_with_none_measured(self):
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])

        assert 'prompt_tokens' not in log.usage_stats()['by_outcome']['succeeded']

    def test_the_totals_account_for_every_round(self):
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'},
            {'agent': 'gis', 'batch_id': 'C', 'outcome': 'burnt', 'usage': burn(agent='gis')},
            {'agent': 'web', 'batch_id': 'C', 'outcome': 'failed',
             'usage': {'finish_reason': 'stop', 'prompt_tokens': 10, 'completion_tokens': 1}},
        ])
        stats = log.usage_stats()

        assert stats['rounds'] == 3
        assert sum(b['rounds'] for b in stats['by_outcome'].values()) == 3
        assert sum(b['rounds'] for b in stats['by_agent'].values()) == 3
        assert sum(b['rounds'] for b in stats['by_batch'].values()) == 3


class TestThePercentiles:
    def test_they_are_nearest_rank_and_not_interpolated(self):
        """Percentiles are nearest-rank, not interpolated."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt',
             'usage': burn(prompt_tokens=value)}
            for value in (10, 20, 30, 40, 50)
        ])

        block = log.usage_stats()['by_outcome']['burnt']['prompt_tokens']
        assert block == {'n': 5, 'min': 10, 'p50': 30, 'p90': 50, 'p99': 50, 'max': 50}

    def test_a_single_round_reports_itself_at_every_percentile(self):
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn(prompt_tokens=7)}
        ])

        block = log.usage_stats()['by_outcome']['burnt']['prompt_tokens']
        assert block['p50'] == block['p99'] == block['max'] == 7

    def test_completion_tokens_are_summarised_beside_prompt_tokens(self):
        """Completion tokens are summarised beside prompt tokens."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn()}
        ])

        block = log.usage_stats()['by_outcome']['burnt']
        assert block['completion_tokens']['max'] == 16_384
        assert block['prompt_tokens']['max'] == 50_000

    def test_the_finish_reasons_of_a_population_are_listed(self):
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn()},
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'failed',
             'usage': {'finish_reason': 'stop'}},
        ])

        assert log.usage_stats()['by_outcome']['burnt']['finish_reasons'] == ['length']

    def test_a_boolean_is_not_a_token_count(self):
        """A boolean token count is ignored."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt',
             'usage': {'prompt_tokens': True, 'completion_tokens': 5}},
        ])

        block = log.usage_stats()['by_outcome']['burnt']
        assert 'prompt_tokens' not in block
        assert block['completion_tokens']['max'] == 5


class TestNothingIsSampled:
    def test_every_round_reaches_the_per_round_list(self):
        """Every round reaches `rounds()` and the percentile population."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn(prompt_tokens=n)}
            for n in range(1, 301)
        ])

        assert len(log.rounds()) == 300
        assert log.usage_stats()['by_outcome']['burnt']['prompt_tokens']['n'] == 300

    def test_the_round_list_is_uncapped_where_the_failure_list_is_not(self):
        """`cap` bounds the failure records and not the round list."""
        log = SpecialistRoundLog(cap=2)
        for _index in range(50):
            log.observe_round(
                agent='kb', batch_id='B', outcome='burnt', usage=burn(),
                failure={'agent': 'kb', 'code': 'empty_completion', 'batch_id': 'B'},
            )

        assert len(log.records) == 2
        assert log.stats()['dropped'] == 48
        assert len(log.rounds()) == 50
        assert log.usage_stats()['rounds'] == 50

    def test_the_per_round_list_is_a_copy(self):
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])
        log.rounds()[0]['agent'] = 'tampered'

        assert log.rounds()[0]['agent'] == 'kb'


class TestTheSplitsAReaderWillActOn:
    def test_by_agent_and_by_batch_are_both_published(self):
        log = log_with([
            {'agent': 'kb', 'batch_id': 'KB-STUDY', 'outcome': 'burnt', 'usage': burn()},
            {'agent': 'gis', 'batch_id': 'GIS-DC', 'outcome': 'succeeded'},
        ])
        stats = log.usage_stats()

        assert set(stats['by_agent']) == {'kb', 'gis'}
        assert set(stats['by_batch']) == {'KB-STUDY', 'GIS-DC'}

    def test_the_chunk_is_kept_on_the_round(self):
        """A round keeps its chunk, parsed into index, total and batch id."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='KB-GEO', chunk='3/4', outcome='burnt',
                          usage=burn())

        assert log.rounds()[0]['chunk'] == {'index': 3, 'total': 4, 'batch_id': 'KB-GEO'}

    def test_a_round_naming_no_chunk_carries_none_rather_than_chunk_zero(self):
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])

        assert 'chunk' not in log.rounds()[0]


class TestTheShapeADeliveredRunCarries:
    """A failure signal in the shape a delivered run carries is measured as a burnt
    round."""

    DELIVERED = {
        'agent': 'kb', 'code': 'empty_completion', 'retryable': True,
        'finish_reason': 'length', 'completion_tokens': 16384,
        'prompt_tokens': 17862, 'total_tokens': 34246,
    }

    def test_a_delivered_failure_signal_measures(self):
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='GIS-DC', chunk={'index': 2, 'total': 2},
                          outcome='burnt', usage=self.DELIVERED)

        block = log.usage_stats()['by_outcome']['burnt']
        assert block['measured'] == 1
        assert block['prompt_tokens']['max'] == 17862
        assert block['completion_tokens']['max'] == 16384
        assert block['finish_reasons'] == ['length']

    @pytest.mark.parametrize('count,expected_p50,expected_p90', [
        (21, 50381, 87030),
    ])
    def test_the_delivered_distribution_reproduces_its_published_percentiles(
        self, count, expected_p50, expected_p90
    ):
        observed = [9063, 10120, 10188, 11561, 17862, 21993, 25489, 26228, 28760,
                    44052, 50381, 51180, 53938, 60164, 64948, 66176, 67983,
                    72878, 87030, 89659, 99537]
        assert len(observed) == count
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt',
             'usage': burn(prompt_tokens=value)}
            for value in observed
        ])

        block = log.usage_stats()['by_outcome']['burnt']['prompt_tokens']
        assert block['p50'] == expected_p50
        assert block['p90'] == expected_p90
        assert block['max'] == 99537


class TestTheOrchestratorRoundsAreAbsorbed:
    """`absorb_orchestrator_rounds` takes the orchestrator's per-round usage records
    into the log."""

    ROUNDS = [
        {'agent': 'kb', 'outcome': 'answered', 'measured': True,
         'prompt_tokens': 4000, 'completion_tokens': 900, 'finish_reason': 'stop'},
        {'agent': 'kb', 'outcome': 'tool_calls', 'measured': True,
         'prompt_tokens': 2000, 'completion_tokens': 120, 'finish_reason': 'tool_calls'},
        {'agent': 'gis', 'outcome': 'empty_completion', 'measured': True,
         'prompt_tokens': 50381, 'completion_tokens': 16384, 'finish_reason': 'length'},
    ]

    def test_the_measured_half_stops_being_zero(self):
        """Absorbed orchestrator rounds are measured."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='KB-STUDY', outcome='succeeded')
        assert log.usage_stats()['by_outcome']['succeeded']['measured'] == 0

        log.absorb_orchestrator_rounds(self.ROUNDS)

        stats = log.usage_stats()
        assert stats['by_outcome']['answered']['measured'] == 1
        assert stats['by_outcome']['answered']['completion_tokens']['max'] == 900

    def test_the_two_populations_are_never_added_together(self):
        """Absorbed orchestrator rounds replace the counted specialist calls rather than
        adding to them."""
        log = SpecialistRoundLog()
        for _ in range(5):
            log.observe_round(agent='kb', batch_id='KB-STUDY', outcome='succeeded')
        assert log.usage_stats()['rounds'] == 5

        log.absorb_orchestrator_rounds(self.ROUNDS)

        assert log.usage_stats()['rounds'] == 3

    def test_the_block_says_which_population_it_is_reporting(self):
        """`source` is `specialist_calls` before absorbing and `orchestrator_rounds`
        after."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='B', outcome='succeeded')
        assert log.usage_stats()['source'] == 'specialist_calls'

        log.absorb_orchestrator_rounds(self.ROUNDS)

        assert log.usage_stats()['source'] == 'orchestrator_rounds'

    def test_an_empty_drain_leaves_the_counted_population_alone(self):
        """Absorbing an empty list leaves the counted specialist calls in place."""
        log = SpecialistRoundLog()
        for _ in range(5):
            log.observe_round(agent='kb', batch_id='B', outcome='succeeded')

        assert log.absorb_orchestrator_rounds([]) == 0
        stats = log.usage_stats()
        assert stats['rounds'] == 5
        assert stats['source'] == 'specialist_calls'
        assert stats['by_outcome']['succeeded']['unmeasured'] == 5

    def test_unmeasured_survives_a_round_the_tool_could_not_measure(self):
        """An absorbed round marked unmeasured is counted as unmeasured."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            {'agent': 'kb', 'outcome': 'answered', 'measured': False},
            {'agent': 'kb', 'outcome': 'answered', 'measured': True,
             'prompt_tokens': 10, 'completion_tokens': 20},
        ])

        block = log.usage_stats()['by_outcome']['answered']
        assert block == {
            'rounds': 2, 'measured': 1, 'unmeasured': 1,
            'prompt_tokens': {'n': 1, 'min': 10, 'p50': 10, 'p90': 10, 'p99': 10, 'max': 10},
            'completion_tokens': {'n': 1, 'min': 20, 'p50': 20, 'p90': 20, 'p99': 20, 'max': 20},
        }

    def test_a_boolean_token_count_is_still_refused_on_this_path(self):
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            {'agent': 'kb', 'outcome': 'answered', 'prompt_tokens': True},
        ])

        assert 'prompt_tokens' not in log.usage_stats()['by_outcome']['answered']

    def test_a_non_mapping_entry_is_dropped_rather_than_crashed_on(self):
        log = SpecialistRoundLog()

        assert log.absorb_orchestrator_rounds(['text', None, 3]) == 0


class TestTwoFillsInOneProcess:
    """Two fills in one process each report only the rounds drained for them."""

    def drain_from(self, buffer):
        """A stand-in for the orchestrator's own take-and-clear."""
        def drain():
            taken = list(buffer)
            buffer.clear()
            return taken
        return drain

    def test_the_second_fill_reports_only_its_own_rounds(self):
        buffer = [{'agent': 'kb', 'outcome': 'answered', 'prompt_tokens': 100}]
        drain = self.drain_from(buffer)

        first = SpecialistRoundLog()
        first.absorb_orchestrator_rounds(drain())

        buffer.extend([
            {'agent': 'gis', 'outcome': 'answered', 'prompt_tokens': 700},
            {'agent': 'gis', 'outcome': 'answered', 'prompt_tokens': 900},
        ])
        second = SpecialistRoundLog()
        second.absorb_orchestrator_rounds(drain())

        assert first.usage_stats()['rounds'] == 1
        assert second.usage_stats()['rounds'] == 2
        assert second.usage_stats()['by_agent'].keys() == {'gis'}
        assert first.usage_stats()['by_outcome']['answered']['prompt_tokens']['max'] == 100

    def test_a_second_fill_with_nothing_recorded_keeps_its_own_denominator(self):
        buffer = [{'agent': 'kb', 'outcome': 'answered', 'prompt_tokens': 100}]
        drain = self.drain_from(buffer)
        SpecialistRoundLog().absorb_orchestrator_rounds(drain())

        second = SpecialistRoundLog()
        second.observe_round(agent='kb', batch_id='B', outcome='succeeded')
        second.absorb_orchestrator_rounds(drain())

        stats = second.usage_stats()
        assert stats['rounds'] == 1
        assert stats['source'] == 'specialist_calls'
        assert stats['by_outcome']['succeeded']['unmeasured'] == 1


class TestTheOrchestratorsOwnMeasurements:
    ROUND = {
        'agent': 'kb', 'outcome': 'answered', 'measured': True,
        'finish_reason': 'stop', 'prompt_tokens': 6214,
        'completion_tokens': 56, 'total_tokens': 6270,
        'content_chars': 41, 'reasoning_chars': 0, 'tool_call_count': 0,
    }

    def test_content_chars_and_reasoning_chars_survive_the_absorb(self):
        """`content_chars`, `reasoning_chars` and `tool_call_count` survive the absorb."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([self.ROUND])

        kept = log.rounds()[0]
        assert kept['content_chars'] == 41
        assert kept['reasoning_chars'] == 0
        assert kept['tool_call_count'] == 0

    def test_a_zero_is_kept_because_zero_is_the_measurement(self):
        """Zero character counts are kept."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            dict(self.ROUND, content_chars=0, reasoning_chars=0,
                 completion_tokens=16384, finish_reason='length'),
        ])

        kept = log.rounds()[0]
        assert kept['content_chars'] == 0
        assert kept['reasoning_chars'] == 0
        assert kept['completion_tokens'] == 16384

    def test_what_compaction_removed_survives_the_absorb(self):
        """`compacted_chars` survives the absorb."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([dict(self.ROUND, compacted_chars=48213)])

        assert log.rounds()[0]['compacted_chars'] == 48213

    def test_nothing_compacted_is_a_zero_and_not_an_absence(self):
        """A `compacted_chars` of zero is kept."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([dict(self.ROUND, compacted_chars=0)])

        assert log.rounds()[0]['compacted_chars'] == 0

    def test_a_round_that_never_reported_it_carries_no_zero(self):
        """A round without `compacted_chars` gains no such key."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([self.ROUND])

        assert 'compacted_chars' not in log.rounds()[0]

    def test_the_recorders_measured_flag_is_carried_not_recomputed(self):
        """The orchestrator's `measured` flag is carried rather than recomputed."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            {'agent': 'kb', 'outcome': 'answered', 'measured': False,
             'prompt_tokens': 10},
        ])

        block = log.usage_stats()['by_outcome']['answered']
        assert block['measured'] == 0
        assert block['unmeasured'] == 1

    def test_a_round_with_no_flag_falls_back_to_the_numbers(self):
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            {'agent': 'kb', 'outcome': 'answered', 'prompt_tokens': 10},
            {'agent': 'kb', 'outcome': 'answered'},
        ])

        block = log.usage_stats()['by_outcome']['answered']
        assert (block['measured'], block['unmeasured']) == (1, 1)

    def test_a_boolean_is_still_not_a_character_count(self):
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            dict(self.ROUND, content_chars=True),
        ])

        assert 'content_chars' not in log.rounds()[0]


import sys  # noqa: E402
import types  # noqa: E402
from typing import Any  # noqa: E402

from open_webui.services.artifacts.geotizer.workflow import (  # noqa: E402
    round_usage_scope,
)

COLLECTOR = '''
rounds = None

def open_round_usage():
    global rounds
    rounds = []

def record_round_usage(agent, outcome, usage):
    if rounds is None:
        return
    rounds.append({'agent': agent, 'measured': bool(usage), **(dict(usage or {}))})

def drain_round_usage():
    global rounds
    taken, rounds = rounds, None
    return list(taken or [])
'''

TOOLS_CLASS = '''
class Tools:
    async def run_agent_task(self, *a, **k):
        return ''
'''


@pytest.fixture
def loaded_tool(request):
    """Build a tool the way the loader does: exec the source into a registered module
    and return the module and a `Tools()` instance."""
    created: list[str] = []

    def build(source: str) -> tuple[Any, Any]:
        name = f'tool_geoteaser_{len(created)}_{id(request)}'
        module = types.ModuleType(name)
        sys.modules[name] = module
        created.append(name)
        exec(source, module.__dict__)
        return module, module.Tools()

    yield build
    for name in created:
        sys.modules.pop(name, None)


def test_the_pair_is_found_on_the_module_behind_a_tools_instance(loaded_tool):
    module, handle = loaded_tool(COLLECTOR + TOOLS_CLASS)

    scope = round_usage_scope(handle)

    assert scope is not None
    scope.open()
    module.record_round_usage('kb', 'answered', {'prompt_tokens': 10})
    assert scope.drain() == [
        {'agent': 'kb', 'measured': True, 'prompt_tokens': 10},
    ]


def test_a_module_carrying_only_a_drain_is_still_refused(loaded_tool):
    """A module with a drain and no opener yields no round-usage scope."""
    source = COLLECTOR.replace('def open_round_usage():', 'def _open_round_usage():')
    _, handle = loaded_tool(source + TOOLS_CLASS)

    assert round_usage_scope(handle) is None


def test_an_opener_on_the_handle_does_not_pair_with_a_drain_on_the_module(loaded_tool):
    """An opener on the handle and a drain on its module do not pair."""
    source = COLLECTOR.replace('def open_round_usage():', 'def _unused_open():') + '''
class Tools:
    def open_round_usage(self):
        pass

    async def run_agent_task(self, *a, **k):
        return ''
'''
    _, handle = loaded_tool(source)

    assert round_usage_scope(handle) is None


def test_a_handle_carrying_both_itself_is_used_without_the_module(loaded_tool):
    """A handle with both methods is used without consulting its module."""
    source = '''
def open_round_usage():
    raise AssertionError('module opener must not be reached')

def drain_round_usage():
    raise AssertionError('module drain must not be reached')

class Tools:
    def __init__(self):
        self.opened = False

    def open_round_usage(self):
        self.opened = True

    def drain_round_usage(self):
        return [{'agent': 'gis', 'measured': True}]
'''
    _, handle = loaded_tool(source)

    scope = round_usage_scope(handle)

    assert scope is not None
    scope.open()
    assert handle.opened is True
    assert scope.drain() == [{'agent': 'gis', 'measured': True}]
