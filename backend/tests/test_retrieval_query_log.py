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


def test_the_recorder_is_reached_from_the_workflow(tmp_path):
    """Asserting the recorder works proves only that the recorder works.

    Six times now a helper has been written, tested and never called — and the
    sixth was this test. It used to replace `module.record_retrieval_queries`
    with a spy and then call **that same attribute**, asserting the spy had
    seen itself. `workflow.py`'s real call site never ran, and deleting it left
    the whole 1823-test suite green.

    So this drives `_collect_chunk_evidence` with an **active** dispatcher —
    the only condition under which the recorder is reached — and a real
    `query_log`, and asserts on what lands in the list. Delete the call and
    this fails.
    """
    import asyncio as _asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _collect_chunk_evidence,
    )
    from open_webui.services.core.tasks import AgentTask
    from open_webui.services.project_evidence.retrieval import (
        build_grounded_retrieval_trace,
    )
    from open_webui.utils.geotizer_rag_runtime import GeoMASRAGDispatcher

    from test_geotizer_rag_runtime import _settings

    async def query_call(plan, collections):
        return build_grounded_retrieval_trace(
            plan,
            {
                'documents': [['Стратиграфия площади представлена сланцами.']],
                'metadatas': [[{
                    'document_id': 'doc-1', 'document_version': 'v1', 'page': 4,
                    'section_path': 'Геология/Стратиграфия',
                    'child_chunk_id': 'child-1',
                    'object_ids': json.dumps(['Тестовая площадь'], ensure_ascii=False),
                    'source_class': 'geological_report',
                    'temporal_role': 'not_temporal',
                }]],
                'distances': [[0.9]],
            },
            collections=collections,
            backend_path=['vector'],
        )

    async def agent_call(task, prompt, object_name, datacube):
        return 'bounded evidence' if task.role == 'contributor' else json.dumps(
            {'field_proposals': []}, ensure_ascii=False
        )

    async def gis_call(payload):
        raise AssertionError('KB-GEO must not invoke deterministic GIS calls')

    query_log: list[dict] = []

    async def scenario():
        dispatcher = GeoMASRAGDispatcher(_settings(tmp_path, active=True), query_call)
        await _collect_chunk_evidence(
            tasks=(
                AgentTask(agent='kb', producer='kb', role='owner',
                          task_id='KB-OWNER', payload={}),
                AgentTask(agent='kb', producer='kb', role='contributor',
                          task_id='KB-EVIDENCE', payload={}),
            ),
            next_batch={
                'batch_id': 'KB-GEO', 'producer': 'kb',
                'owner_chunk': {'index': 1, 'total': 3},
                'fields': [{
                    'field_key': 'geotizer_object.v1.r010.a01', 'row_id': 10,
                    'group': 'Геология', 'element': 'Стратиграфия',
                    'attribute_name': 'Описание',
                }],
            },
            object_name='Тестовая площадь',
            run_id='run-recorder',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=dispatcher,
            datacube=None,
            knowledge_search_plan={},
            vision_evidence_call=None,
            vision_project_id=None,
            query_log=query_log,
        )

    _asyncio.run(scenario())

    assert query_log, (
        'the workflow must reach the recorder on the active RAG path; '
        'an empty log is the call site being absent'
    )
    assert {entry.get('batch_id') for entry in query_log} == {'KB-GEO'}
    assert any(entry.get('chunk') == '1/3' for entry in query_log), (
        'the chunk the batch names must travel with the record, rendered '
        'index/total -- this is what proves the real call site ran and not a '
        'hand-seeded list'
    )
    assert any(entry.get('agent') == 'kb' for entry in query_log)

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


def test_the_run_log_is_sent_into_finalize_not_hung_on_its_answer():
    """`retrieval_queries` and `gis_execution_trace` both read zero in every
    exported state since they shipped, and for one reason: they were attached
    to the terminal payload this function returns, and the state is written by
    `gis_service` from the patches. Nothing read them back.

    Run `8a02f724` is the measurement -- `gis_execution_trace` 0,
    `raw_measurement` 0, `retrieval_queries` 0, `layer_not_found` 0, against
    `negative_findings` 14 and `semantic_role` 20, the two that ride on a
    patch's `source_locator`.

    So the log travels *in* the finalize call. This test pins the direction,
    because the previous shape also looked correct from the caller's side.
    """
    import ast
    import inspect
    from pathlib import Path

    source = Path(
        inspect.getfile(
            __import__(
                'open_webui.services.artifacts.geotizer.workflow',
                fromlist=['workflow'],
            )
        )
    ).read_text(encoding='utf-8')
    tree = ast.parse(source)

    finalize_payloads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value == 'action'
            for key in node.keys
            if key is not None
        )
        and any(
            isinstance(value, ast.Constant) and value.value == 'finalize'
            for value in node.values
        )
    ]

    assert finalize_payloads, 'the finalize call must be findable to be checked'
    sent = ast.unparse(finalize_payloads[0])
    assert 'run_log' in sent, 'the run log must be sent into finalize, not attached to its answer'


def test_the_run_log_carries_every_run_level_record():
    """One carrier for the class, not one per item. The pattern has cost five
    separate things; a sixth fix per item would be the sixth instance.

    `gis_layer_manifest` is the fourth, and it is the reason the carrier was
    worth building: the linked project's inventory is a property of the run,
    it was read inside the infrastructure calculation and dropped when the
    calculation returned, and the working inventory had to be reconstructed by
    hand from seventeen exported states because of it.
    """
    import inspect

    from open_webui.services.artifacts.geotizer import workflow

    source = inspect.getsource(workflow)
    start = source.index('run_log = {')
    block = source[start : source.index('final = await gis_call', start)]

    for record in (
        'run_notes',
        'retrieval_queries',
        'gis_execution_trace',
        'gis_layer_manifest',
    ):
        assert f"'{record}'" in block, f'{record} must travel on the run log'
