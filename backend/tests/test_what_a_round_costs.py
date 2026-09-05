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
