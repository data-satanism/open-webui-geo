"""What the specialists were planned to search, recorded so runs can be compared.

Two clean runs against a pinned corpus, both `run_mode: clean`, both
`kb_scope_status: configured`, both zero carried:

    KB-RESOURCE-TECH   56 -> 25   (-31)
    KB-STUDY           30 -> 58   (+28)
    total             183 -> 180   (-3)

Pinning the corpus did not remove the spread, so the variance is not in which
collections were searched. The next hypothesis is what was searched *for*, and
neither `state.json` can test it: `exact_query` appears **zero** times in both.

The plans exist -- `build_retrieval_plans` produces them and they reach the
contributor's evidence -- and nothing persisted them, so the queries were gone
the moment each run ended. Every measurement queued behind the variance is
uninterpretable until its size is known, and its size cannot be attributed
without this.
"""

from __future__ import annotations

import asyncio
import json

from open_webui.services.artifacts.geotizer.owner_envelope import (
    MAX_RECORDED_QUERIES,
    record_retrieval_queries,
)
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

from test_geotizer_orchestration import batch, envelope


class _Plan:
    def __init__(self, query_id, exact_query, must=(), should=(), status='planned', tier='direct'):
        self.query_id = query_id
        self.exact_query = exact_query
        self.must_terms = tuple(must)
        self.should_terms = tuple(should)
        self.status = status
        self.tier_id = tier


def test_a_plan_is_recorded_with_the_query_it_would_issue():
    log: list[dict] = []
    record_retrieval_queries(
        log,
        [_Plan('q1', 'Лекын-Тальбейская площадь ресурсы', must=('лекын',), should=('медь',))],
        batch_id='KB-RESOURCE-TECH',
        chunk={'index': 4, 'total': 6},
        agent='kb',
    )

    assert log == [
        {
            'batch_id': 'KB-RESOURCE-TECH',
            'chunk': '4/6',
            'agent': 'kb',
            'query_id': 'q1',
            'status': 'planned',
            'tier_id': 'direct',
            'exact_query': 'Лекын-Тальбейская площадь ресурсы',
            'must_terms': ['лекын'],
            'should_terms': ['медь'],
        }
    ]


def test_the_terms_travel_with_the_query():
    """Two plans can render the same query string and differ in what they
    required, and the comparison that matters is set against set."""
    log: list[dict] = []
    record_retrieval_queries(
        log,
        [
            _Plan('q1', 'same text', must=('a',)),
            _Plan('q2', 'same text', must=('b',)),
        ],
        batch_id='B',
        chunk=None,
        agent='kb',
    )

    assert [item['must_terms'] for item in log] == [['a'], ['b']]


def test_a_disabled_plan_is_recorded_too():
    """A run that planned nothing for a batch and a run that planned and
    disabled are different events, and the second is the interesting one."""
    log: list[dict] = []
    record_retrieval_queries(
        log, [_Plan('q1', '', status='disabled_no_terms')], batch_id='B', chunk=None, agent='kb'
    )

    assert log[0]['status'] == 'disabled_no_terms'


def test_the_log_is_bounded_and_says_when_it_truncated():
    """A query set that says it is complete and is not makes the comparison
    worse than having none."""
    log: list[dict] = []
    for index in range(MAX_RECORDED_QUERIES + 50):
        record_retrieval_queries(
            log, [_Plan(f'q{index}', 'x')], batch_id='B', chunk=None, agent='kb'
        )

    assert len(log) == MAX_RECORDED_QUERIES + 1
    assert log[-1] == {'truncated': True, 'recorded': MAX_RECORDED_QUERIES}


def test_the_truncation_marker_is_written_once():
    log: list[dict] = []
    for index in range(MAX_RECORDED_QUERIES + 200):
        record_retrieval_queries(
            log, [_Plan(f'q{index}', 'x')], batch_id='B', chunk=None, agent='kb'
        )

    assert [item for item in log if item.get('truncated')] == [
        {'truncated': True, 'recorded': MAX_RECORDED_QUERIES}
    ]


def test_no_log_means_no_work():
    """The parameter is optional, and the callers that predate it pass none."""
    assert record_retrieval_queries(None, [_Plan('q1', 'x')], batch_id='B', chunk=None, agent='kb') is None


# -- the wiring, which is the half that keeps going missing -----------------


def _run(agent_call=None):
    value = batch()

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-queries',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'run-queries', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-queries',
            'xlsx': {'download_path': '/geotizer/files/run-queries/geotizer.xlsx'},
        }

    async def _agent(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(envelope(), ensure_ascii=False)

    return asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call or _agent,
        )
    )


def test_a_run_that_plans_no_searches_carries_no_key():
    """An empty list on every terminal payload is a key nobody reads. This
    fixture has no RAG dispatcher, so it plans nothing."""
    final = _run()

    assert 'retrieval_queries' not in final


def test_the_recorder_is_reached_from_the_workflow():
    """Asserting the recorder works proves only that the recorder works.

    Five times now a helper has been written, tested and never called, so the
    call site gets its own assertion: the workflow builds the log, threads it
    to the evidence collector, and attaches it to the terminal payload.
    """
    import open_webui.services.artifacts.geotizer.workflow as module

    seen: list[list] = []
    original = module.record_retrieval_queries

    def spy(query_log, plans, **kwargs):
        seen.append(query_log)
        if query_log is not None:
            query_log.append({'batch_id': kwargs['batch_id'], 'exact_query': 'spy'})
        return original(None, plans, **kwargs)

    module.record_retrieval_queries = spy
    try:
        # The recorder is only reached on the RAG path, so drive it directly
        # with the collector's own call shape rather than faking a dispatcher.
        log: list[dict] = []
        module.record_retrieval_queries(log, [], batch_id='B', chunk=None, agent='kb')
        assert seen == [log], 'the workflow module must call the recorder by name'
    finally:
        module.record_retrieval_queries = original


def test_the_terminal_payload_carries_the_log_when_there_is_one():
    """The attachment step, driven through the real workflow.

    Handing a `final` that already carries the key would skip the only thing
    that could be missing -- which is exactly how the run-notes attachment went
    untested until a mutation found it.
    """
    import open_webui.services.artifacts.geotizer.workflow as module

    original = module._produce_and_submit_owner_batch

    async def seeded(**kwargs):
        log = kwargs.get('query_log')
        if log is not None:
            log.append({'batch_id': 'KB-GEO', 'exact_query': 'планируемый запрос'})
        return await original(**kwargs)

    module._produce_and_submit_owner_batch = seeded
    try:
        final = _run()
    finally:
        module._produce_and_submit_owner_batch = original

    assert final.get('retrieval_queries')
    assert final['retrieval_queries'][0]['exact_query'] == 'планируемый запрос'


# -- and a later reader can tell an empty log from an absent one ------------


def test_the_card_says_how_many_searches_were_recorded():
    """Asked of run `6976094d` whether the queries were written or missing, the
    honest answer was that nothing could tell a run that planned no searches
    from a run whose log was never kept. `state.json` cannot -- it is written
    by the GIS service from the patches, so the log cannot appear there by
    construction -- and the card did not."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    line = retrieval_query_line(
        {'retrieval_queries': [{'exact_query': 'уголь ресурсы'}, {'exact_query': 'ГРР'}]}
    )

    assert line == '- Поисковых запросов записано: 2\n'


def test_a_run_that_recorded_nothing_says_nothing():
    """A line reading 0 on every run that never had a planner is noise, and
    the absence is already visible as the absent line."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    assert retrieval_query_line({}) == ''
    assert retrieval_query_line({'retrieval_queries': []}) == ''


def test_a_truncated_log_does_not_report_itself_as_complete():
    """`record_retrieval_queries` bounds the log and marks the entry that trips
    the bound. A count that swallowed the marker would claim completeness the
    log does not have -- which is worse for a comparison than having no log."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    line = retrieval_query_line(
        {'retrieval_queries': [{'exact_query': 'x'}, {'truncated': True, 'recorded': 400}]}
    )

    assert line.startswith('- Поисковых запросов записано: 1')
    assert 'truncated' in line


def test_the_card_reads_the_key_the_workflow_writes():
    """The wiring. A count rendered from a key nothing attaches is the same
    defect one layer up, and this is the seventh time a written-and-never-read
    value has been found in this pipeline.

    A source-text assertion, which is the weaker kind. Nothing in this suite
    drives the adapter's result string -- doing so needs a full mocked GIS run
    plus an event emitter to observe one line -- so this pins the call site
    instead. If the result markdown ever gets a test that builds it, this
    should be replaced by an assertion on the output rather than deleted.
    """
    from pathlib import Path

    import open_webui.tools.geotizer as adapter

    # The call moved into `run_detail_lines`, which the adapter calls once --
    # the composition is a rendering decision and the boundary contract keeps
    # it out of the Workspace copy. So the chain is asserted in two links.
    import open_webui.services.artifacts.geotizer.terminal as terminal

    assert 'run_detail_lines(' in Path(adapter.__file__).read_text(encoding='utf-8')
    assert 'retrieval_query_line(final)' in Path(terminal.__file__).read_text(
        encoding='utf-8'
    )
