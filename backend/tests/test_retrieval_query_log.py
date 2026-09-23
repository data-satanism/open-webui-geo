"""Tests that the retrieval queries a run planned are recorded, bounded, carried on the run log and counted on the card.
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
    """Each recorded query carries its own must terms."""
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
    """A disabled plan is recorded with its status."""
    log: list[dict] = []
    record_retrieval_queries(
        log, [_Plan('q1', '', status='disabled_no_terms')], batch_id='B', chunk=None, agent='kb'
    )

    assert log[0]['status'] == 'disabled_no_terms'


def test_the_log_is_bounded_and_says_when_it_truncated():
    """The log stops at `MAX_RECORDED_QUERIES` and ends with a truncation marker."""
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
    """`record_retrieval_queries` does nothing when the log is None."""
    assert record_retrieval_queries(None, [_Plan('q1', 'x')], batch_id='B', chunk=None, agent='kb') is None


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
    """A run with no RAG dispatcher carries no `retrieval_queries` key."""
    final = _run()

    assert 'retrieval_queries' not in final


def test_the_recorder_is_reached_from_the_workflow(tmp_path):
    """`_collect_chunk_evidence` with an active dispatcher records the batch's queries with its chunk and agent."""
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
    """A query recorded during the workflow reaches the terminal payload's `retrieval_queries`."""
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


def test_the_card_says_how_many_searches_were_recorded():
    """`retrieval_query_line` states the number of recorded queries."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    line = retrieval_query_line(
        {'retrieval_queries': [{'exact_query': 'уголь ресурсы'}, {'exact_query': 'ГРР'}]}
    )

    assert line == '- Поисковых запросов записано: 2\n'


def test_a_run_that_recorded_nothing_says_nothing():
    """`retrieval_query_line` returns '' when no query was recorded."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    assert retrieval_query_line({}) == ''
    assert retrieval_query_line({'retrieval_queries': []}) == ''


def test_a_truncated_log_does_not_report_itself_as_complete():
    """`retrieval_query_line` excludes the truncation marker from the count and marks the line as truncated."""
    from open_webui.services.artifacts.geotizer.terminal import retrieval_query_line

    line = retrieval_query_line(
        {'retrieval_queries': [{'exact_query': 'x'}, {'truncated': True, 'recorded': 400}]}
    )

    assert line.startswith('- Поисковых запросов записано: 1')
    assert 'truncated' in line


def test_the_card_reads_the_key_the_workflow_writes():
    """The adapter calls `run_detail_lines`, and `terminal.py` calls `retrieval_query_line(final)`."""
    from pathlib import Path

    import open_webui.tools.geotizer as adapter

    import open_webui.services.artifacts.geotizer.terminal as terminal

    assert 'run_detail_lines(' in Path(adapter.__file__).read_text(encoding='utf-8')
    assert 'retrieval_query_line(final)' in Path(terminal.__file__).read_text(
        encoding='utf-8'
    )


def test_the_run_log_is_sent_into_finalize_not_hung_on_its_answer():
    """The workflow's `finalize` payload carries `run_log`."""
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
    """The workflow's run log carries `run_notes`, `retrieval_queries`, `gis_execution_trace` and `gis_layer_manifest`.
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
