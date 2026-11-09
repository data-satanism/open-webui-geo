"""Tests for `elapsed_ms` on each retrieval query entry and `run_timing` on the
run log, asserted on the `run_log` sent into `finalize`."""

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
from test_kb_collection_scope import (  # noqa: F401
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


def test_every_query_entry_carries_how_long_the_call_took():
    """Every query entry carries a non-negative integer `elapsed_ms`."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    entries = run_log['retrieval_queries']

    assert entries
    for entry in entries:
        assert isinstance(entry['elapsed_ms'], int), entry
        assert entry['elapsed_ms'] >= 0


def test_the_duration_sits_on_the_same_entry_as_the_batch_and_the_agent():
    """`elapsed_ms` sits on the same entry as `agent`, `batch_id`, `chunk` and
    `attempt`."""
    entries = _run(drain=QueryDrain())['finalize']['run_log']['retrieval_queries']
    entry = entries[0]

    assert {'agent', 'batch_id', 'chunk', 'attempt', 'elapsed_ms'} <= set(entry)


def test_a_call_that_did_not_time_itself_says_so_rather_than_reporting_zero():
    """An entry recorded without a start has `elapsed_ms` None, not zero."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='b', chunk=None):
        record_query(tool='t', query='untimed')

    assert drain.drain()[0]['elapsed_ms'] is None


def test_the_field_is_named_for_the_call_and_not_for_the_thinking():
    """The name `elapsed_ms` is none of `duration`, `took` and `latency`, and the query sink module and
    `record_query` have string docstrings."""
    from open_webui.utils import geotizer_query_sink

    source = geotizer_query_sink.__doc__ or ''
    entry_source = geotizer_query_sink.record_query.__doc__ or ''

    assert 'elapsed_ms' not in {'duration', 'took', 'latency'}
    assert isinstance(source, str) and isinstance(entry_source, str)


def test_run_timing_reaches_the_run_log_sent_into_finalize():
    """`run_timing` with both stamps and a float total reaches the `run_log`
    sent into `finalize`."""
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
    """Each batch row carries its id, start, end, seconds and query count."""
    timing = _run(drain=QueryDrain())['finalize']['run_log']['run_timing']

    assert timing['batches']
    for row in timing['batches']:
        assert row['batch_id']
        assert row['started_at'] and row['finished_at']
        assert row['seconds'] >= 0
        assert row['queries'] >= 0


def test_the_batch_seconds_are_summed_and_the_remainder_is_named():
    """`run_timing` carries the sum of batch seconds, the time outside batches,
    and whether the batches were sequential."""
    timing = _run(drain=QueryDrain())['finalize']['run_log']['run_timing']

    assert timing['batches_sum_seconds'] <= timing['total_seconds'] + 1.0
    assert timing['outside_batches_seconds'] >= 0
    assert isinstance(timing['batches_are_sequential'], bool)


def test_sequential_batches_are_named_as_a_finding_not_assumed():
    """`_run_timing` marks batches sequential when their seconds sum to the
    total and not when they exceed it."""
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
    """A run with no batches is not sequential, and all its time is outside
    batches."""
    timing = _run_timing(
        started_at='a', finished_at='b', total_seconds=10.0, batches=[]
    )

    assert timing['batches_are_sequential'] is False
    assert timing['outside_batches_seconds'] == 10.0


def test_the_call_count_is_named_for_what_is_countable():
    """A batch row counts `specialist_calls_that_searched` and `queries`, and
    has no `specialist_calls`."""
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
    """`chunks` is read from the chunk labels and omitted when the batch
    searched nothing."""
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
    """A run without a query drain still times its batches, with zero queries."""
    timing = _run(drain=None)['finalize']['run_log']['run_timing']

    assert timing['batches']
    assert all(row['queries'] == 0 for row in timing['batches'])
    assert timing['total_seconds'] >= 0


@pytest.mark.asyncio
async def test_a_real_grep_times_the_call_it_records(kb):
    """`grep_knowledge_files` records its call with an integer `elapsed_ms`."""
    drain = QueryDrain()
    registry = _Knowledges([_Knowledge('geo-a')], files={'geo-a': [_File('f', 'Проект.pdf')]})
    kb.install(registry, grants=_AccessGrants(('geo-a',)))

    with drain.recording(agent='kb', batch_id='GIS-DC', chunk='1/3'):
        await grep_knowledge_files(
            'кровля',
            __request__=_request(),
            __user__=USER,
            knowledge_ids=['geo-a'],
        )

    entry = drain.drain()[0]
    assert entry['tool'] == 'grep_knowledge_files'
    assert isinstance(entry['elapsed_ms'], int), 'the site did not pass its start'


def test_every_recording_site_in_the_tools_starts_a_clock():
    """`builtin.py` has four `record_query` sites, each passing `started` from
    `query_clock()`."""
    from pathlib import Path

    source = Path(builtin.__file__).read_text(encoding='utf-8')

    assert source.count('started = query_clock()') == 4
    assert source.count('started=started,') == 4
    assert source.count('record_query(') == 4
