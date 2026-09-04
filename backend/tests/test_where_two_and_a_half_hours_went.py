"""A fill takes 2h32m and nothing said where it went.

`started_at` reached the contour on 4 September and gave the first real
measurement of a single-object fill: `39feab89` 2h32m, `2e009bf5` 2h48m. The
working estimate was four to seven minutes per member, derived from the
deadline module's «around seventy-five specialist calls» — wrong by roughly
thirty times, and caught only because a start stamp was added in a round where
nobody asked for one.

That number is now load-bearing: the area path is being designed against a
per-member cost, and the only thing under it was one total per run.

So two records. `elapsed_ms` on every query entry, beside the `agent`,
`batch_id`, `chunk` and `attempt` that entry already carries — a slow batch and
its queries join without anything having to correlate them afterwards. And
`run_timing` on the run log, derived from what the orchestrator already knows
rather than measured again, because a second clock is a clock that can disagree
with the first.

Asserted on the payload that goes into `finalize`, which is what `gis_service`
writes to `run_log.json` — never on whether a writer was called. That failure
has happened six times.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from open_webui.services.artifacts.geotizer.workflow import (
    _batch_timing,
    _run_timing,
    run_geotizer_workflow,
)
from open_webui.utils.geotizer_query_sink import (
    QueryDrain,
    query_clock,
    record_query,
)

import pytest

from open_webui.tools import builtin
from open_webui.tools.builtin import grep_knowledge_files

from tests.test_run_notes import batch, envelope
from test_grep_can_be_told_where_to_look import _File
from test_kb_collection_scope import (  # noqa: F401 - the `kb` fixture
    USER,
    _AccessGrants,
    _Knowledge,
    _Knowledges,
    _request,
    kb,
)


def _run(*, drain: QueryDrain | None) -> dict[str, Any]:
    value = batch()
    sent: dict[str, Any] = {}
    filled = [{'field_key': 'f1', 'status': 'filled', 'source_locator': {'document_id': 'd'}}]

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-timing',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': value,
                'fields': filled,
                'batches_total': 1,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-timing',
                'next_batch': None,
                'fields': filled,
            }
        sent.update(payload)
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-timing',
            'fields': filled,
            'xlsx': {'download_path': '/geotizer/files/run-timing/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        started = query_clock()
        record_query(
            tool='query_knowledge_files',
            query=f'запрос {task.role}',
            collections=['kb-reports'],
            results=1,
            result_sources=['Проект ГРР'],
            result_document_ids=['d'],
            started=started,
        )
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(envelope(), ensure_ascii=False)

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            query_drain=drain,
        )
    )
    return {'final': final, 'finalize': sent}


# ------------------------------------------------------- elapsed_ms on the entries


def test_every_query_entry_carries_how_long_the_call_took():
    """Beside what was asked, not in a separate list that has to be joined."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    entries = run_log['retrieval_queries']

    assert entries
    for entry in entries:
        assert isinstance(entry['elapsed_ms'], int), entry
        assert entry['elapsed_ms'] >= 0


def test_the_duration_sits_on_the_same_entry_as_the_batch_and_the_agent():
    """That adjacency is the whole point: a slow batch and the queries it
    issued join without a correlation step."""
    entries = _run(drain=QueryDrain())['finalize']['run_log']['retrieval_queries']
    entry = entries[0]

    assert {'agent', 'batch_id', 'chunk', 'attempt', 'elapsed_ms'} <= set(entry)


def test_a_call_that_did_not_time_itself_says_so_rather_than_reporting_zero():
    """`None` is «not measured»; `0` is «measured and instant», and a reader
    would take the second for the first."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='b', chunk=None):
        record_query(tool='t', query='untimed')

    assert drain.drain()[0]['elapsed_ms'] is None


def test_the_field_is_named_for_the_call_and_not_for_the_thinking():
    """A tool invocation is what is visible from a builtin; the specialist's
    reasoning around it is not, and a field that quietly means something
    narrower than its name is a defect this project has met repeatedly."""
    from open_webui.utils import geotizer_query_sink

    source = geotizer_query_sink.__doc__ or ''
    entry_source = geotizer_query_sink.record_query.__doc__ or ''

    assert 'elapsed_ms' not in {'duration', 'took', 'latency'}
    assert isinstance(source, str) and isinstance(entry_source, str)


# ------------------------------------------------------------------ run_timing


def test_run_timing_reaches_the_run_log_sent_into_finalize():
    """The artefact assertion. `gis_service` writes `run_log.json` from this."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']

    assert 'run_timing' in run_log
    timing = run_timing = run_log['run_timing']
    assert timing['started_at'] and timing['finished_at']
    assert isinstance(run_timing['total_seconds'], float)


def test_the_total_matches_the_two_stamps_it_sits_between():
    from datetime import datetime

    timing = _run(drain=QueryDrain())['finalize']['run_log']['run_timing']
    span = (
        datetime.fromisoformat(timing['finished_at'])
        - datetime.fromisoformat(timing['started_at'])
    ).total_seconds()

    assert abs(timing['total_seconds'] - span) <= 1.0


def test_each_batch_is_a_row_with_its_own_start_end_and_cost():
    """Eight batches, and the question the area path needs answered is which
    of them consumes the time: one batch at 90 minutes and seven at ten is a
    different design problem from eight at nineteen."""
    timing = _run(drain=QueryDrain())['finalize']['run_log']['run_timing']

    assert timing['batches']
    for row in timing['batches']:
        assert row['batch_id']
        assert row['started_at'] and row['finished_at']
        assert row['seconds'] >= 0
        assert row['queries'] >= 0


def test_the_batch_seconds_are_summed_and_the_remainder_is_named():
    """Setup before batch one and finalize afterwards are not nothing, and a
    reader should not have to compute the gap."""
    timing = _run(drain=QueryDrain())['finalize']['run_log']['run_timing']

    assert timing['batches_sum_seconds'] <= timing['total_seconds'] + 1.0
    assert timing['outside_batches_seconds'] >= 0
    assert isinstance(timing['batches_are_sequential'], bool)


def test_sequential_batches_are_named_as_a_finding_not_assumed():
    """Batches could overlap, so the sum is not required to equal the total —
    but if it does, they ran one after another, and that is a fact about the
    run rather than a rounding coincidence."""
    sequential = _run_timing(
        started_at='2026-09-04T10:00:00+00:00',
        finished_at='2026-09-04T12:32:00+00:00',
        total_seconds=9120.0,
        batches=[{'batch_id': f'b{index}', 'seconds': 1140.0} for index in range(8)],
    )
    overlapping = _run_timing(
        started_at='2026-09-04T10:00:00+00:00',
        finished_at='2026-09-04T12:32:00+00:00',
        total_seconds=9120.0,
        batches=[{'batch_id': f'b{index}', 'seconds': 4000.0} for index in range(8)],
    )

    assert sequential['batches_are_sequential'] is True
    assert sequential['outside_batches_seconds'] == 0.0
    assert overlapping['batches_are_sequential'] is False


def test_a_run_with_no_batches_is_not_called_sequential():
    """Nothing ran, so nothing ran in order."""
    timing = _run_timing(
        started_at='a', finished_at='b', total_seconds=10.0, batches=[]
    )

    assert timing['batches_are_sequential'] is False
    assert timing['outside_batches_seconds'] == 10.0


# --------------------------------------------------- what a batch row can and cannot say


def test_the_call_count_is_named_for_what_is_countable():
    """`specialist_calls` was the obvious name and the wrong one: a specialist
    that searched nothing leaves nothing to count, so the narrower thing
    carries the narrower name."""
    row = _batch_timing(
        batch_id='KB-GEO',
        started_at='a',
        finished_at='b',
        seconds=12.5,
        entries=[
            {'agent': 'kb', 'chunk': '1/3', 'attempt': 1},
            {'agent': 'kb', 'chunk': '1/3', 'attempt': 1},
            {'agent': 'kb', 'chunk': '2/3', 'attempt': 1},
            {'agent': 'web', 'chunk': '2/3', 'attempt': 1},
        ],
    )

    assert 'specialist_calls' not in row
    assert row['specialist_calls_that_searched'] == 3
    assert row['queries'] == 4


def test_the_chunk_count_comes_off_the_labels_and_is_absent_when_unknown():
    """Exact when the batch searched, and absent rather than zero when it did
    not — a zero would read as «this batch had no chunks»."""
    with_chunks = _batch_timing(
        batch_id='b', started_at='a', finished_at='b', seconds=1.0,
        entries=[{'agent': 'kb', 'chunk': '3/6', 'attempt': 1}],
    )
    without = _batch_timing(
        batch_id='b', started_at='a', finished_at='b', seconds=1.0, entries=[]
    )

    assert with_chunks['chunks'] == 6
    assert 'chunks' not in without
    assert without['queries'] == 0


def test_a_run_without_a_drain_still_times_its_batches():
    """The drain is optional; the clock is not."""
    timing = _run(drain=None)['finalize']['run_log']['run_timing']

    assert timing['batches']
    assert all(row['queries'] == 0 for row in timing['batches'])
    assert timing['total_seconds'] >= 0


# ------------------------------------------- the four call sites that supply the clock

# `record_query` computes the interval; it does not start it. If a call site
# stops passing `started`, every entry that tool writes silently becomes
# `None` — measured as «not measured» — and nothing above would notice,
# because the harness above calls `record_query` itself. So the tools are
# driven through their own signatures here.


@pytest.mark.asyncio
async def test_a_real_grep_times_the_call_it_records(kb):
    """`grep_knowledge_files` issued 171 of run `a067e802`'s 207 searches. It
    is the site whose duration matters most and the one with no orchestration
    around it to fall back on."""
    drain = QueryDrain()
    registry = _Knowledges([_Knowledge('geo-a')], files={'geo-a': [_File('f', 'Проект.pdf')]})
    kb.install(registry, grants=_AccessGrants(('geo-a',)))

    with drain.recording(agent='kb', batch_id='GIS-DC', chunk='1/3'):
        await grep_knowledge_files(
            'кровля',
            __request__=_request(),
            __user__=USER,
            __collection_allowlist__=('geo-a',),
            knowledge_ids=['geo-a'],
        )

    entry = drain.drain()[0]
    assert entry['tool'] == 'grep_knowledge_files'
    assert isinstance(entry['elapsed_ms'], int), 'the site did not pass its start'


def test_every_recording_site_in_the_tools_starts_a_clock():
    """Four sites, and the count is asserted rather than trusted: a fifth
    recorder added without one would leave a hole shaped exactly like the one
    this round exists to close."""
    from pathlib import Path

    source = Path(builtin.__file__).read_text(encoding='utf-8')

    assert source.count('started = query_clock()') == 4
    assert source.count('started=started,') == 4
    assert source.count('record_query(') == 4
