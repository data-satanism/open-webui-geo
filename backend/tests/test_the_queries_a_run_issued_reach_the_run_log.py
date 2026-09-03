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
    MAX_RECORDED_QUERY_CHARS,
    QueryDrain,
    collapse_repeated_alternatives,
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
                searched_collections=['kb-licences'],
                results=3,
                result_sources=['Лицензия СЛХ025834ТП.pdf'],
                result_document_ids=['doc-licence'],
                result_collection_ids=['kb-licences'],
            )
            return 'bounded evidence'
        # The unscoped shape: no collection named, so the tool enumerated what
        # it could reach and read a collection nobody attached.
        record_query(
            tool='grep_knowledge_files',
            query=OWNER_QUERY,
            collections=[],
            searched_collections=['kb-reports', 'kb-extrusion'],
            results=5,
            result_sources=['Проект ГРР Лекын-Тальбейское 2025', 'Не цитированный отчёт'],
            result_document_ids=['doc-grr', 'doc-uncited'],
            result_collection_ids=['kb-reports', 'kb-extrusion'],
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
            # What the user attached to this run. A marker, not a grant: it
            # says which collections the run is about, and it is never
            # remembered past the run.
            kb_configured_collections=('kb-reports', 'kb-licences'),
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
    assert owner_entry['tool'] == 'grep_knowledge_files'
    assert owner_entry['agent']
    assert owner_entry['batch_id'] == str(batch()['batch_id'])
    assert owner_entry['attempt'] == 1
    assert owner_entry['collections'] == []
    assert owner_entry['searched_collections'] == ['kb-reports', 'kb-extrusion']
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


def test_the_bound_is_reported_beside_the_list_and_never_inside_it():
    """Runs `82365089` and `26aaf34a` both ended at exactly 401 entries, the
    last of them `{"recorded": 400, "truncated": true}` — an object with no
    agent, no tool and no query sitting among the query records. It broke two
    things: the count stopped being a measurement (401 in both runs meant only
    that both exceeded 400) and the array stopped being homogeneous."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='b', chunk=None):
        for index in range(MAX_RECORDED_QUERIES + 5):
            record_query(tool='t', query=f'q{index}')

    entries = drain.drain()

    assert len(entries) == MAX_RECORDED_QUERIES
    assert all(entry.get('tool') and entry.get('agent') for entry in entries)
    assert not any('truncated' in entry for entry in entries)
    assert drain.stats() == {
        'issued': MAX_RECORDED_QUERIES + 5,
        'recorded': MAX_RECORDED_QUERIES,
        'dropped': 5,
        'truncated': True,
        'cap': MAX_RECORDED_QUERIES,
    }


def test_issued_is_a_measurement_even_when_the_cap_did_not_bind():
    """The number a comparison of two runs' query sets rests on."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='b', chunk=None):
        for index in range(7):
            record_query(tool='t', query=f'q{index}')

    assert drain.stats()['issued'] == 7
    assert drain.stats()['dropped'] == 0
    assert drain.stats()['truncated'] is False


def test_the_cap_clears_the_volume_the_two_runs_actually_issued():
    """400 was described as «high enough not to bind in practice». It bound on
    the first pair that recorded the WEB half — 219 and 206 KB calls plus 181
    and 194 web ones — so the bound was wrong about practice."""
    assert MAX_RECORDED_QUERIES >= 4 * 401


# ---------------------------------------------- the query that was 26 KB of one word


def test_repeated_alternatives_collapse_and_match_the_same_text():
    """Run `26aaf34a` issued 26,432 characters: 2,520 alternatives of which ten
    were distinct. Run `a067e802` issued 31,943 — 5,319 and eleven. `a|b|a`
    matches exactly what `a|b` matches, so this narrows no search."""
    query = '|'.join(['линия'] * 2000 + ['дорога', 'ж/д'])

    collapsed, alternatives, distinct = collapse_repeated_alternatives(query)

    assert collapsed == 'линия|дорога|ж/д'
    assert (alternatives, distinct) == (2002, 3)
    assert len(collapsed) < len(query) / 100


def test_a_pattern_with_regex_structure_is_left_exactly_as_written():
    """Inside a group or a class, `|` can mean something else. A diagnostic may
    not change what a search matches, so the unbounded record is preferred."""
    for query in ('(a|b)|a', 'a|[b|c]|a', r'a|b\|c|a'):
        assert collapse_repeated_alternatives(query)[0] == query


def test_the_collapse_is_recorded_as_numbers_not_as_26_kb():
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='GIS-DC', chunk=None):
        record_query(tool='grep_knowledge_files', query='|'.join(['линия'] * 500))

    entry = drain.drain()[0]

    assert entry['query'] == 'линия'
    assert entry['alternatives_received'] == 500
    assert entry['alternatives_distinct'] == 1
    assert entry['query_chars_received'] == len('|'.join(['линия'] * 500))


def test_an_ordinary_query_carries_none_of_the_collapse_keys():
    """A field that is always present is a field a reader has to interpret."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='b', chunk=None):
        record_query(tool='t', query='железная дорога|ж/д')

    entry = drain.drain()[0]

    assert entry['query'] == 'железная дорога|ж/д'
    assert 'alternatives_received' not in entry
    assert 'query_truncated' not in entry


def test_one_entry_can_never_be_what_makes_a_run_log_unreadable():
    """A backstop, not a filter: post-collapse the longest query in either run
    is 267 characters, a percent-encoded URL from `fetch_url`."""
    drain = QueryDrain()
    with drain.recording(agent='web', batch_id='b', chunk=None):
        record_query(tool='fetch_url', query='x' * (MAX_RECORDED_QUERY_CHARS + 50))

    entry = drain.drain()[0]

    assert len(entry['query']) == MAX_RECORDED_QUERY_CHARS
    assert entry['query_truncated'] is True
    assert entry['query_chars'] == MAX_RECORDED_QUERY_CHARS + 50


# ------------------------------------------- which collections were actually read


def test_a_call_that_named_no_collection_still_says_what_it_read():
    """The 31 and 52 unscoped KB calls carried every one of the 350 and 400
    hits on another tenant's corpus, and nothing in the artefact said which
    collections they had opened."""
    drain = QueryDrain()
    with drain.recording(agent='kb', batch_id='KB-GEO', chunk=None):
        record_query(
            tool='grep_knowledge_files',
            query='рудопроявление',
            collections=[],
            searched_collections=['geo-1', 'geo-2', 'extrusion-9'],
        )

    entry = drain.drain()[0]

    assert entry['collections'] == []
    assert entry['searched_collections'] == ['geo-1', 'geo-2', 'extrusion-9']


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


# --------------------------------------- the collections a run read, marked or not


def test_the_run_log_says_how_many_searches_the_run_made():
    """`retrieval_query_stats`, beside `retrieval_queries` and not inside it."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']

    stats = run_log['retrieval_query_stats']

    assert stats['issued'] == len(run_log['retrieval_queries'])
    assert stats['dropped'] == 0
    assert stats['truncated'] is False


def test_the_run_log_names_the_collections_that_were_read_and_which_were_unmarked():
    """A marker, not a fence. The run read a collection the user did not attach
    and finished the search; what changes is that a reviewer can see it without
    reading four hundred query records."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']

    stats = run_log['retrieval_query_stats']

    assert stats['collections_read'] == ['kb-extrusion', 'kb-licences', 'kb-reports']
    assert stats['collections_marked'] == ['kb-licences', 'kb-reports']
    assert stats['collections_read_unmarked'] == ['kb-extrusion']


def test_a_citation_says_which_collection_it_came_from():
    """`result_sources` gives a filename and the cell gives a `document_id`;
    neither said the collection, so a cell resting on an unattached corpus was
    indistinguishable from one resting on the attached documents."""
    run_log = _run(drain=QueryDrain())['finalize']['run_log']
    entry = next(
        item for item in run_log['retrieval_queries'] if item['query'] == OWNER_QUERY
    )

    assert entry['citations'] == 1
    assert entry['cited_document_ids'] == ['doc-grr']
    assert entry['cited_collections'] == ['kb-reports']
    assert entry['cited_collections_unmarked'] == []


def test_a_cell_cited_from_an_unmarked_collection_is_named_as_such():
    """Not refused: the user may have attached the wrong thing, or the answer
    may genuinely live elsewhere. Visible."""
    from open_webui.services.artifacts.geotizer.workflow import _queries_with_citations

    issued = [
        {
            'tool': 'grep_knowledge_files',
            'query': 'экструзия',
            'result_document_ids': ['doc-hmec'],
            'result_collection_ids': ['kb-extrusion'],
        }
    ]
    fields = [{'status': 'filled', 'source_locator': {'document_id': 'doc-hmec'}}]

    entry = _queries_with_citations(issued, [], fields, ['kb-reports'])[0]

    assert entry['citations'] == 1
    assert entry['cited_collections'] == ['kb-extrusion']
    assert entry['cited_collections_unmarked'] == ['kb-extrusion']


def test_an_unknown_origin_is_left_out_rather_than_guessed():
    """The vector path of `query_knowledge_files` gets a filename and a file id
    from the store and no collection. An empty string is not a collection."""
    from open_webui.services.artifacts.geotizer.workflow import _queries_with_citations

    issued = [
        {
            'tool': 'query_knowledge_files',
            'query': 'запасы',
            'result_document_ids': ['doc-grr'],
            'result_collection_ids': [''],
        }
    ]
    fields = [{'status': 'filled', 'source_locator': {'document_id': 'doc-grr'}}]

    entry = _queries_with_citations(issued, [], fields, ['kb-reports'])[0]

    assert entry['citations'] == 1
    assert 'cited_collections' not in entry
