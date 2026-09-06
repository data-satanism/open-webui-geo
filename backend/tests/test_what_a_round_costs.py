"""21 burns out of how many rounds? Nothing recorded the second number.

`completion_usage()` runs on every round and surfaces only when a round fails,
so every failure count this project has published has been a numerator with no
denominator. Three questions follow from that and all three are one record
away: do burnt rounds carry larger prompts than successful ones, do they carry
longer tool histories, and what does a successful specialist round actually
cost.

`observe_round` is the single entry point — the round tally and the failure
record are made in one call, so there is no second site for them to disagree
about how many rounds there were. That is A-186 and A-187 restated: the defect
was never the bound, it was two numbers derived in two places.

One thing this cannot do yet, and says so rather than guessing: the
orchestrator is a Workspace tool whose entry point is «plain data in and text
out», so a **successful** round reaches this repository as a string with no
usage block. Those rounds are counted and reported as `unmeasured`, never
folded into a percentile that would then be a percentile over «whichever rounds
happened to be visible».
"""

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
        """The number that has never existed. Without it «21 burns» cannot be
        turned into a rate, and every comparison between runs of different
        lengths has been unanchored."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'KB-STUDY', 'outcome': 'succeeded'},
            {'agent': 'kb', 'batch_id': 'KB-STUDY', 'outcome': 'burnt', 'usage': burn()},
        ])

        stats = log.usage_stats()
        assert stats['rounds'] == 2
        assert stats['by_outcome']['succeeded']['rounds'] == 1
        assert stats['by_outcome']['burnt']['rounds'] == 1

    def test_a_successful_round_leaves_no_failure_record(self):
        """The two must not drift: counting a round is not recording a
        failure, and the old `records`/`stats` contract is unchanged."""
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])

        assert log.records == []
        assert log.stats() == {}
        assert log.usage_stats()['rounds'] == 1

    def test_the_failure_record_is_made_by_the_same_call(self):
        """One entry point, so the tally and the record cannot disagree about
        how many rounds there were — the defect A-186 and A-187 were about,
        one level along."""
        log = SpecialistRoundLog()
        log.observe_round(
            agent='kb', batch_id='KB-STUDY', chunk={'index': 2, 'total': 5},
            outcome='burnt', usage=burn(),
            failure={'agent': 'kb', 'code': 'empty_completion', 'batch_id': 'KB-STUDY'},
        )

        assert log.stats()['issued'] == 1
        assert log.usage_stats()['rounds'] == 1

    def test_no_rounds_at_all_yields_no_block(self):
        """An empty block is a key a reader has to interpret before learning
        it says nothing."""
        assert SpecialistRoundLog().usage_stats() == {}


class TestMeasuredAndUnmeasuredAreNeverFolded:
    def test_a_round_with_no_usage_is_counted_and_named_unmeasured(self):
        """The honest shape. A successful round reaches this repository as a
        string, so it can be counted and not measured — and saying which is the
        difference between a measurement and an average of what was visible."""
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
        """With 300 rounds an interpolated percentile invents a token count no
        round had, and this number is going to be argued about as if it were a
        measurement."""
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
        """The pair is the point: `max_tokens` is argued from completion, and
        whether burns carry larger prompts is argued from prompt."""
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
        """`isinstance(True, int)` is true in Python, and a percentile over
        `True` is a number with no referent."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt',
             'usage': {'prompt_tokens': True, 'completion_tokens': 5}},
        ])

        block = log.usage_stats()['by_outcome']['burnt']
        assert 'prompt_tokens' not in block
        assert block['completion_tokens']['max'] == 5


class TestNothingIsSampled:
    def test_every_round_reaches_the_per_round_list(self):
        """No sampling anywhere. A percentile over a subset answers a different
        question, and the subset would be chosen by the same code path whose
        behaviour is in question."""
        log = log_with([
            {'agent': 'kb', 'batch_id': 'B', 'outcome': 'burnt', 'usage': burn(prompt_tokens=n)}
            for n in range(1, 301)
        ])

        assert len(log.rounds()) == 300
        assert log.usage_stats()['by_outcome']['burnt']['prompt_tokens']['n'] == 300

    def test_the_round_list_is_uncapped_where_the_failure_list_is_not(self):
        """The failure list is bounded because a person reads it. The rounds
        are a measurement, and a measurement over a truncated prefix is the
        defect this project has already fixed twice."""
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
        """So a burnt round can be joined to the cells it damaged without
        mining a `source_refs` prefix."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='KB-GEO', chunk='3/4', outcome='burnt',
                          usage=burn())

        assert log.rounds()[0]['chunk'] == {'index': 3, 'total': 4, 'batch_id': 'KB-GEO'}

    def test_a_round_naming_no_chunk_carries_none_rather_than_chunk_zero(self):
        log = log_with([{'agent': 'kb', 'batch_id': 'B', 'outcome': 'succeeded'}])

        assert 'chunk' not in log.rounds()[0]


class TestTheShapeADeliveredRunCarries:
    """Transcribed from `16c65331`'s `specialist_round_failures[0]`, so the
    reader is pinned to the artefact rather than to the writer's signature."""

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
        # The 21 burns of `16c65331`, sorted. p50 is the median the task
        # quotes; p90 is nearest-rank, so ceil(0.90 * 21) = 19 and the answer
        # is the 19th smallest — 87030, not the 20th value 89659. Written out
        # because a percentile everyone reads and nobody can recompute is the
        # kind of number that drifts.
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


# --- The drain. v5.9.0 recorded every round and nothing read it: the eighth
# instance of a record written to a carrier nobody reads, introduced in the
# same round that warned about the pattern.


class TestTheOrchestratorRoundsAreAbsorbed:
    """Option B, and it is not a hack.

    The fork already reaches the loaded module by attribute name — the adapter
    does exactly this for `run_agent_task`, with an explicit «this contour is
    running a version older than the one GeoTeaser calls». And instrumentation
    in this system already travels beside the data rather than through it:
    `QueryDrain` collects retrieval the same way, for the same reason. A round's
    cost is instrumentation. Widening `run_agent_task` — «plain data in and text
    out» — would put a measurement into the contract that keeps this repository
    independent of the tool's internals, and every caller would carry it.
    """

    ROUNDS = [
        {'agent': 'kb', 'outcome': 'answered', 'measured': True,
         'prompt_tokens': 4000, 'completion_tokens': 900, 'finish_reason': 'stop'},
        {'agent': 'kb', 'outcome': 'tool_calls', 'measured': True,
         'prompt_tokens': 2000, 'completion_tokens': 120, 'finish_reason': 'tool_calls'},
        {'agent': 'gis', 'outcome': 'empty_completion', 'measured': True,
         'prompt_tokens': 50381, 'completion_tokens': 16384, 'finish_reason': 'length'},
    ]

    def test_the_measured_half_stops_being_zero(self):
        """The assertion the whole task is for. Before the drain,
        `succeeded: {measured: 0}`; after it, a number."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='KB-STUDY', outcome='succeeded')
        assert log.usage_stats()['by_outcome']['succeeded']['measured'] == 0

        log.absorb_orchestrator_rounds(self.ROUNDS)

        stats = log.usage_stats()
        assert stats['by_outcome']['answered']['measured'] == 1
        assert stats['by_outcome']['answered']['completion_tokens']['max'] == 900

    def test_the_two_populations_are_never_added_together(self):
        """One record per specialist call here, one per model round there, and
        a call that used tools is several rounds. Adding them would count the
        same work twice, so the finer measured population replaces the coarser
        counted one."""
        log = SpecialistRoundLog()
        for _ in range(5):
            log.observe_round(agent='kb', batch_id='KB-STUDY', outcome='succeeded')
        assert log.usage_stats()['rounds'] == 5

        log.absorb_orchestrator_rounds(self.ROUNDS)

        assert log.usage_stats()['rounds'] == 3

    def test_the_block_says_which_population_it_is_reporting(self):
        """A denominator that changes meaning without saying so is how two
        runs get compared on different units."""
        log = SpecialistRoundLog()
        log.observe_round(agent='kb', batch_id='B', outcome='succeeded')
        assert log.usage_stats()['source'] == 'specialist_calls'

        log.absorb_orchestrator_rounds(self.ROUNDS)

        assert log.usage_stats()['source'] == 'orchestrator_rounds'

    def test_an_empty_drain_leaves_the_counted_population_alone(self):
        """«The tool reported nothing» must not erase «there were five
        rounds». A contour running an older build measures nothing and still
        has a denominator."""
        log = SpecialistRoundLog()
        for _ in range(5):
            log.observe_round(agent='kb', batch_id='B', outcome='succeeded')

        assert log.absorb_orchestrator_rounds([]) == 0
        stats = log.usage_stats()
        assert stats['rounds'] == 5
        assert stats['source'] == 'specialist_calls'
        assert stats['by_outcome']['succeeded']['unmeasured'] == 5

    def test_unmeasured_survives_a_round_the_tool_could_not_measure(self):
        """The third application of the rule: `issued` beside `recorded`,
        `measured` beside `unmeasured`, an uncapped index behind
        `failures_for`. A provider that sends no usage block is a round that
        happened and was not measured."""
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
    """`drain_round_usage()` clears on read, so a second fill must not inherit
    the first one's rounds. The tool holds them in a module-level list where
    `QueryDrain` uses a contextvar — sequential fills are correct because of
    the clear, and concurrent fills are not. That is the tool's to close."""

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


# --- The three fields v5.8.0 added, which reached this repository and got no
# further. The orchestrator emits every key its `completion_usage` produced;
# this side copied only the provider's five and dropped the rest, so a round of
# analysis read their absence from `run_log.json` as evidence that the server
# sends no message object. The record arrived and was discarded at the door.


class TestTheOrchestratorsOwnMeasurements:
    ROUND = {
        'agent': 'kb', 'outcome': 'answered', 'measured': True,
        'finish_reason': 'stop', 'prompt_tokens': 6214,
        'completion_tokens': 56, 'total_tokens': 6270,
        'content_chars': 41, 'reasoning_chars': 0, 'tool_call_count': 0,
    }

    def test_content_chars_and_reasoning_chars_survive_the_absorb(self):
        """Their presence in the artefact is the only proof the split ever
        ran. Without it their absence reads as a finding about the server."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([self.ROUND])

        kept = log.rounds()[0]
        assert kept['content_chars'] == 41
        assert kept['reasoning_chars'] == 0
        assert kept['tool_call_count'] == 0

    def test_a_zero_is_kept_because_zero_is_the_measurement(self):
        """`reasoning_chars: 0` beside a large `completion_tokens` is the
        answer to the burn question. Dropping a falsy value would erase
        exactly the observation being sought."""
        log = SpecialistRoundLog()
        log.absorb_orchestrator_rounds([
            dict(self.ROUND, content_chars=0, reasoning_chars=0,
                 completion_tokens=16384, finish_reason='length'),
        ])

        kept = log.rounds()[0]
        assert kept['content_chars'] == 0
        assert kept['reasoning_chars'] == 0
        assert kept['completion_tokens'] == 16384

    def test_the_recorders_measured_flag_is_carried_not_recomputed(self):
        """A round the orchestrator marked unmeasured stays unmeasured, even
        if one key survived the copy. Two sides disagreeing quietly about the
        same count is what `issued` beside `recorded` exists to stop."""
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


# --- Detection ran against the wrong object, and reported the absence as the
# build's. `load_tool_module_by_id` returns `module.Tools()`, not the module:
# `run_agent_task` is a method of `Tools` and resolved, so the adapter worked
# and nothing looked wrong, while `open_round_usage` and `drain_round_usage`
# are module-level and were invisible on that instance. `round_usage_scope`
# returned None, the collection was never opened, all 61 rounds of run
# `a3d7feac` were dropped at `if rounds is None`, and the log fell back to
# `source: specialist_calls` with usage on none of them -- while the failure
# envelope, which never went through the collector, carried real token counts
# for the same 21 responses. Nothing covered this function.

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
    """What the loader does: exec into a module, hand back `Tools()`."""
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
    """Both-or-neither survives the wider search: v5.9.0's module-level list
    is exactly what the module lookup would otherwise reach."""
    source = COLLECTOR.replace('def open_round_usage():', 'def _open_round_usage():')
    _, handle = loaded_tool(source + TOOLS_CLASS)

    assert round_usage_scope(handle) is None


def test_an_opener_on_the_handle_does_not_pair_with_a_drain_on_the_module(loaded_tool):
    """Two halves of two builds is the case both-or-neither exists to refuse,
    and pairing per name rather than per object would reintroduce it."""
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
    """A future tool exposing them as methods must not fall through to a
    module that happens to define the same names differently."""
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
