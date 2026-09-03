"""What a specialist searched for, on the artefact, not in a log line.

Four clean runs of one build filled 207, 191, 219 and 137 of 351 cells. The
corpus was stable — the same three documents cited in every run — and the same
document yielded 103 citations in one and 58 in another. The variance is in
what was asked of the corpus, and until now nothing recorded that.

`retrieval_queries` existed and never arrived. Not because the carrier was
wrong — `run_notes`, `gis_execution_trace`, `gis_layer_manifest` and
`gis_proposal_rejections` all reach `run_log.json` by the same route — but
because the only thing that ever wrote to it was the RAG-v2 *plan* recorder,
behind a gate an ordinary run does not pass. The plan is what an owner was
asked to look for; it is built from the batch and barely moves between runs.

So the queries are recorded where they are issued: `query_knowledge_files` and
`grep_knowledge_files`, the two builtins every orchestrated specialist search
lands in. Identity travels in a `ContextVar` the workflow opens around each
specialist call, because an orchestrated call's metadata carries no run id —
`request.state.internal` is the only marker there is.

The failure mode this file exists against has happened five times: a record
built, a carrier assumed, nothing in the artefact. So the assertions here are
on the payload that goes into `finalize`, which is what `gis_service` writes to
`run_log.json` — never on whether a writer was called.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow
from open_webui.utils.geotizer_query_sink import (
    MAX_RECORDED_QUERIES,
    QueryDrain,
    is_recording,
    record_query,
    recording_queries,
)

from tests.test_run_notes import batch, envelope

OWNER_QUERY = 'запасы золота Лекын-Тальбейское C1 C2 тыс. т руды'
CONTRIBUTOR_QUERY = 'лицензия СЛХ 02583 ТП недропользователь ИНН'


def _run(*, drain: QueryDrain | None) -> dict[str, Any]:
    """A whole fill, with specialists that search the way real ones do."""
    value = batch()
    sent: dict[str, Any] = {}

    # The state the workflow holds while it runs, which is what the citation
    # join reads: `finalize`'s own answer arrives after the run log is built.
    filled = [
        {
            'field_key': 'f1',
            'status': 'filled',
            'source_locator': {'document_id': 'doc-grr', 'page': '33'},
            'source_refs': ['kb-lic-legal__part_1__doc-licence__geotizer_object.v1.r001.a01'],
        }
    ]

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-queries-e2e',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': value,
                'fields': filled,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-queries-e2e',
                'next_batch': None,
                'fields': filled,
            }
        sent.update(payload)
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-queries-e2e',
            'fields': [
                {
                    'field_key': 'f1',
                    'status': 'filled',
                    'source_locator': 'KB: Проект ГРР Лекын-Тальбейское 2025, с. 33',
                    'source_refs': ['kb-lic__part_1'],
                }
            ],
            'xlsx': {'download_path': '/geotizer/files/run-queries-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        # What a specialist does with its tools: this is the same call the KB
        # builtins make, from inside the scope the workflow opened.
        if task.role == 'contributor':
            record_query(
                tool='query_knowledge_files',
                query=CONTRIBUTOR_QUERY,
                collections=['kb-licences'],
                results=3,
                result_sources=['Лицензия СЛХ025834ТП.pdf'],
                result_document_ids=['doc-licence'],
            )
            return 'bounded evidence'
        record_query(
            tool='query_knowledge_files',
            query=OWNER_QUERY,
            collections=['kb-reports'],
            results=5,
            result_sources=['Проект ГРР Лекын-Тальбейское 2025', 'Не цитированный отчёт'],
            result_document_ids=['doc-grr', 'doc-uncited'],
        )
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


# ------------------------------------------------------------- it arrives


def test_the_queries_reach_the_run_log_sent_into_finalize():
    """The artefact assertion. `gis_service` writes `run_log.json` from this."""
    result = _run(drain=QueryDrain())

    run_log = result['finalize'].get('run_log') or {}

    assert 'retrieval_queries' in run_log, (
        'the key must be on the run log, which is what run_log.json is written from'
    )
    assert run_log['retrieval_queries'], 'present and empty is the failure this exists against'


def test_the_query_is_recorded_verbatim():
    """Not normalised, not truncated. The question is why two runs read one
    document to different depths, and a shortened query cannot answer it."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    queries = [entry['query'] for entry in run_log['retrieval_queries']]

    assert OWNER_QUERY in queries
    assert CONTRIBUTOR_QUERY in queries


def test_each_query_says_who_issued_it_and_where():
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    owner_entry = next(
        entry for entry in run_log['retrieval_queries'] if entry['query'] == OWNER_QUERY
    )

    assert owner_entry['source'] == 'issued'
    assert owner_entry['tool'] == 'query_knowledge_files'
    assert owner_entry['agent']
    assert owner_entry['batch_id'] == str(batch()['batch_id'])
    assert owner_entry['attempt'] == 1
    assert owner_entry['collections'] == ['kb-reports']
    assert owner_entry['results'] == 5


def test_a_contributor_and_an_owner_are_told_apart():
    """Both search; they are different specialists and the record says so."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    by_query = {entry['query']: entry for entry in run_log['retrieval_queries']}

    assert by_query[CONTRIBUTOR_QUERY]['attempt'] is None
    assert by_query[OWNER_QUERY]['attempt'] == 1


def test_how_much_of_what_came_back_was_cited():
    """A join on the document id, and on nothing else.

    The first pair carried `citations_by_name`, a join on the filename, and it
    returned 0 on all 406 entries that had results: a KB result carries
    `Проект ГРР Лекын-Тальбейское 2025.pdf` and a locator carries
    `document_id: cdd1bdf0-…`. The two sides shared no token.
    """
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    owner_entry = next(
        entry for entry in run_log['retrieval_queries'] if entry['query'] == OWNER_QUERY
    )

    # `doc-grr` is on a filled cell's locator; `doc-uncited` is on neither.
    assert owner_entry['citations'] == 1
    assert owner_entry['cited_document_ids'] == ['doc-grr']
    assert 'citations_by_name' not in owner_entry


def test_a_document_id_inside_a_source_ref_counts_as_a_citation():
    """`kb-lic-legal__part_1__<uuid>__geotizer_object.v1.r001.a01` is where the
    id actually lives on most cells."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    contributor = next(
        entry for entry in run_log['retrieval_queries'] if entry['query'] == CONTRIBUTOR_QUERY
    )

    assert contributor['citations'] == 1
    assert contributor['cited_document_ids'] == ['doc-licence']


def test_the_field_is_absent_rather_than_zero_when_no_ids_were_recorded():
    """A field that is always zero is worse than an absent one: a reader takes
    it for a measurement and concludes nothing was cited."""
    from open_webui.services.artifacts.geotizer.workflow import _queries_with_citations

    entries = _queries_with_citations(
        [{'source': 'issued', 'query': 'q', 'result_sources': ['x.pdf']}],
        [],
        [{'status': 'filled', 'source_locator': {'document_id': 'doc-grr'}}],
    )

    assert 'citations' not in entries[0]


def test_the_terminal_payload_carries_the_same_list():
    result = _run(drain=QueryDrain())

    assert result['final']['retrieval_queries'] == result['finalize']['run_log']['retrieval_queries']


# ------------------------------------------------- and it is not invented


def test_a_run_with_no_drain_records_nothing_rather_than_something_empty():
    """Every contour that has not wired one keeps exactly its old behaviour."""
    run_log = _run(drain=None)['finalize'].get('run_log') or {}

    assert 'retrieval_queries' not in run_log


def test_a_search_outside_every_scope_is_not_recorded():
    """A person chatting with their own documents is not a run."""
    drain = QueryDrain()

    assert is_recording() is False
    record_query(tool='query_knowledge_files', query='погода в Салехарде')

    assert drain.drain() == []


def test_the_scope_restores_whatever_was_active():
    sink: list[dict[str, Any]] = []
    with recording_queries(sink, agent='kb', batch_id='outer', chunk=None):
        with recording_queries(sink, agent='web', batch_id='inner', chunk=None):
            record_query(tool='t', query='inner')
        record_query(tool='t', query='outer')

    assert [entry['batch_id'] for entry in sink] == ['inner', 'outer']
    assert is_recording() is False


def test_the_bound_is_reported_in_the_entry_that_trips_it():
    """A query set that says it is complete and is not would make the
    comparison worse than having none."""
    sink: list[dict[str, Any]] = []
    with recording_queries(sink, agent='kb', batch_id='b', chunk=None):
        for index in range(MAX_RECORDED_QUERIES + 5):
            record_query(tool='t', query=f'q{index}')

    assert len(sink) == MAX_RECORDED_QUERIES + 1
    assert sink[-1] == {'truncated': True, 'recorded': MAX_RECORDED_QUERIES}


def test_a_broken_entry_never_breaks_the_search_that_made_it():
    """A diagnostic that can lose cells is worse than no diagnostic."""

    class Exploding:
        def __str__(self) -> str:
            raise RuntimeError('no')

    sink: list[dict[str, Any]] = []
    with recording_queries(sink, agent='kb', batch_id='b', chunk=None):
        record_query(tool='t', query='fine', collections=[Exploding()])

    assert sink == []


# ------------------------------------------------- the builtins call it


def test_every_search_tool_a_specialist_uses_records_what_it_was_asked():
    """All 432 entries of the first pair read `agent: kb`, because only the two
    knowledge builtins recorded. `WEB-VERIFY: 17` was that batch's KB searches
    and not its web ones — a partial measurement read as a whole one."""
    import ast
    import inspect

    from open_webui.tools import builtin

    source = inspect.getsource(builtin)
    tree = ast.parse(source)
    recording = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and 'record_query(' in (ast.get_source_segment(source, node) or '')
    }

    assert recording == {
        'query_knowledge_files',
        'grep_knowledge_files',
        'search_web',
        'fetch_url',
    }
