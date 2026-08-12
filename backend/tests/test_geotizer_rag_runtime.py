from __future__ import annotations

import asyncio
import json
from pathlib import Path

from open_webui.tools.geotizer import (
    _collect_chunk_evidence,
    query_geomas_retrieval_plan,
)
from open_webui.utils.geotizer_orchestration import AgentTask
from open_webui.utils.geotizer_rag_runtime import (
    GeoMASRAGDispatcher,
    GeoMASRAGRuntimeSettings,
    ShadowTraceStore,
    drain_background_dispatches,
    execute_retrieval_plans,
    parse_collection_names,
)
from open_webui.services.project_evidence.retrieval import (
    build_grounded_retrieval_trace,
    build_retrieval_plans,
)


def _plans(*, collections: tuple[str, ...] = ('geomas_rag_v2',)):
    batch = {
        'batch_id': 'KB-GEO',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r010.a01',
                'row_id': 10,
                'group': 'Геология',
                'element': 'Стратиграфия',
                'attribute_name': 'Описание',
            }
        ],
    }
    knowledge_plan = {
        'object_profile': {
            'project_resolution': {
                'object_name': 'Тестовая площадь',
                'project_id': 'project-1',
            }
        },
        'tiers': [
            {
                'tier_id': 'direct',
                'relation_to_object': 'direct',
                'query_terms': ['Тестовая площадь'],
                'enabled': True,
            }
        ],
    }
    return build_retrieval_plans(
        batch,
        knowledge_plan,
        run_id='run-1',
        index_version='idx-1',
        collections=collections,
    )


def _settings(
    tmp_path: Path,
    *,
    active: bool = False,
    shadow: bool = False,
) -> GeoMASRAGRuntimeSettings:
    return GeoMASRAGRuntimeSettings(
        active_enabled=active,
        shadow_enabled=shadow,
        collections=('geomas_rag_v2',),
        index_version='idx-1',
        timeout_ms=500,
        max_concurrency=2,
        trace_dir=tmp_path,
    )


def _no_hit_trace(plan, collections):
    return build_grounded_retrieval_trace(
        plan,
        None,
        collections=collections,
        backend_path=['vector'],
    )


def test_runtime_settings_are_default_off_and_rollback_is_unambiguous(tmp_path) -> None:
    disabled = GeoMASRAGRuntimeSettings.from_env(
        environ={},
        data_dir=tmp_path,
    )
    assert disabled.mode == 'disabled'
    assert disabled.configuration_errors() == ()

    async def should_not_run(plan, collections):
        raise AssertionError('rollback must disable the shadow query callable')

    dispatcher = GeoMASRAGDispatcher(
        _settings(tmp_path),
        should_not_run,
    )
    assert dispatcher.submit_shadow(
        _plans(),
        run_id='rollback-run',
        object_name='Тестовая площадь',
        batch_id='KB-GEO',
    ) is None
    assert not dispatcher.trace_store.path_for('rollback-run').exists()

    active_without_index = GeoMASRAGRuntimeSettings.from_env(
        environ={'ENABLE_GEOMAS_RAG_V2': 'true'},
        data_dir=tmp_path,
    )
    assert active_without_index.mode == 'active'
    assert set(active_without_index.configuration_errors()) == {
        'GEOMAS_RAG_V2_COLLECTIONS is required',
        'GEOMAS_RAG_V2_INDEX_VERSION is required',
    }

    conflicting = GeoMASRAGRuntimeSettings.from_env(
        environ={
            'ENABLE_GEOMAS_RAG_V2': 'true',
            'ENABLE_GEOMAS_RAG_V2_SHADOW': 'true',
        },
        data_dir=tmp_path,
    )
    assert conflicting.mode == 'invalid'
    assert any('mutually exclusive' in item for item in conflicting.configuration_errors())


def test_collection_allowlist_accepts_json_or_csv_and_rejects_control_chars() -> None:
    assert parse_collection_names('["one", "two", "one"]') == ('one', 'two')
    assert parse_collection_names('one, two') == ('one', 'two')
    assert parse_collection_names(['good', 'bad\nname']) == ('good',)


def test_active_dispatcher_accepts_only_gateway_validated_trace(tmp_path) -> None:
    plans = _plans()

    async def query_call(plan, collections):
        return _no_hit_trace(plan, collections)

    async def scenario():
        dispatcher = GeoMASRAGDispatcher(
            _settings(tmp_path, active=True),
            query_call,
        )
        traces = await dispatcher.execute_active(plans)
        assert len(traces) == 1
        assert traces[0]['query_id'] == plans[0].query_id
        assert traces[0]['failure_type'] == 'no_retrieval_hit'

    asyncio.run(scenario())


def test_invalid_gateway_trace_fails_closed_without_legacy_fallback(tmp_path) -> None:
    plans = _plans()

    async def forged_query_call(plan, collections):
        return {**_no_hit_trace(plan, collections), 'exact_query': 'free-form'}

    async def scenario():
        dispatched = await execute_retrieval_plans(
            plans,
            forged_query_call,
            collections=('geomas_rag_v2',),
            timeout_ms=500,
            max_concurrency=1,
        )
        assert dispatched[0].status == 'failed'
        assert dispatched[0].trace['failure_type'] == 'retrieval_failed'
        assert dispatched[0].trace['hits'] == []
        assert dispatched[0].trace['backend_failures'][0]['error_type'] == 'ValueError'

    asyncio.run(scenario())


def test_dispatch_timeout_becomes_typed_failure(tmp_path) -> None:
    plans = _plans()

    async def slow_query_call(plan, collections):
        await asyncio.sleep(0.2)
        return _no_hit_trace(plan, collections)

    async def scenario():
        dispatched = await execute_retrieval_plans(
            plans,
            slow_query_call,
            collections=('geomas_rag_v2',),
            timeout_ms=10,
            max_concurrency=1,
        )
        assert dispatched[0].status == 'timed_out'
        assert dispatched[0].trace['failure_type'] == 'retrieval_failed'
        assert dispatched[0].trace['backend_failures'][0]['error_type'] == 'TimeoutError'
        assert dispatched[0].latency_ms >= 90

    asyncio.run(scenario())


def test_shadow_dispatch_is_non_blocking_and_persists_non_visible_trace(tmp_path) -> None:
    plans = _plans()
    release = asyncio.Event()
    started = asyncio.Event()

    async def gated_query_call(plan, collections):
        started.set()
        await release.wait()
        return _no_hit_trace(plan, collections)

    async def scenario():
        store = ShadowTraceStore(tmp_path)
        dispatcher = GeoMASRAGDispatcher(
            _settings(tmp_path, shadow=True),
            gated_query_call,
            trace_store=store,
        )
        task = dispatcher.submit_shadow(
            plans,
            run_id='../run-1',
            object_name='Тестовая площадь',
            batch_id='KB-GEO',
        )
        assert task is not None
        await started.wait()
        assert not task.done()
        assert not store.path_for('../run-1').exists()
        assert store.path_for('../run-1').is_relative_to(tmp_path)

        release.set()
        await drain_background_dispatches()
        path = store.path_for('../run-1')
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        assert len(rows) == 1
        assert rows[0]['arm'] == 'geomas_rag_v2_shadow'
        assert rows[0]['schema'] == 'geomas.rag_shadow_dispatch.v2'
        assert rows[0]['attempt_id'].startswith('rag-attempt-')
        assert rows[0]['resume_from_record'] == 0
        assert rows[0]['is_retry'] is False
        assert rows[0]['user_visible'] is False
        assert rows[0]['trace']['query_id'] == plans[0].query_id

    asyncio.run(scenario())


def test_shadow_attempt_freezes_resume_offset_and_records_retry_lineage(tmp_path) -> None:
    plans = _plans()

    async def query_call(plan, collections):
        return _no_hit_trace(plan, collections)

    async def scenario():
        store = ShadowTraceStore(tmp_path)
        await store.append('run-resume', [{'schema': 'historical-record'}])
        dispatcher = GeoMASRAGDispatcher(
            _settings(tmp_path, shadow=True),
            query_call,
            trace_store=store,
        )
        attempt = await dispatcher.begin_attempt(
            run_id='run-resume',
            parent_chat_id='chat-123',
            attempt_key='message-2',
            is_retry=True,
            retry_reason='explicit_run_resume',
        )
        same_attempt = await dispatcher.begin_attempt(
            run_id='run-resume',
            parent_chat_id='chat-123',
            attempt_key='message-2',
            is_retry=True,
            retry_reason='explicit_run_resume',
        )
        assert same_attempt == attempt
        assert attempt.resume_from_record == 1

        dispatcher.submit_shadow(
            plans,
            run_id='run-resume',
            object_name='Test area',
            batch_id='KB-GEO',
            attempt=attempt,
        )
        await drain_background_dispatches()
        rows = [
            json.loads(line)
            for line in store.path_for('run-resume').read_text(encoding='utf-8').splitlines()
        ]
        assert len(rows) == 2
        record = rows[1]
        assert record['attempt_id'] == attempt.attempt_id
        assert record['parent_chat_id'] == 'chat-123'
        assert record['resume_from_record'] == 1
        assert record['is_retry'] is True
        assert record['retry_reason'] == 'explicit_run_resume'

        next_attempt = await dispatcher.begin_attempt(
            run_id='run-resume',
            parent_chat_id='chat-123',
            attempt_key='message-3',
            is_retry=True,
            retry_reason='manual_retry',
        )
        assert next_attempt.resume_from_record == 2
        assert next_attempt.attempt_id != attempt.attempt_id

    asyncio.run(scenario())


def test_shadow_configuration_failure_is_persisted_but_not_raised(tmp_path) -> None:
    settings = GeoMASRAGRuntimeSettings(
        active_enabled=False,
        shadow_enabled=True,
        collections=(),
        index_version='',
        timeout_ms=500,
        max_concurrency=1,
        trace_dir=tmp_path,
    )

    async def should_not_run(plan, collections):
        raise AssertionError('query callable must not run for invalid shadow config')

    async def scenario():
        dispatcher = GeoMASRAGDispatcher(settings, should_not_run)
        assert dispatcher.submit_shadow(
            _plans(collections=()),
            run_id='run-config-error',
            object_name='Тестовая площадь',
            batch_id='KB-GEO',
        ) is not None
        await drain_background_dispatches()
        rows = [
            json.loads(line)
            for line in dispatcher.trace_store.path_for('run-config-error')
            .read_text(encoding='utf-8')
            .splitlines()
        ]
        assert rows[0]['status'] == 'configuration_error'
        assert rows[0]['user_visible'] is False
        assert rows[0]['trace'] is None

    asyncio.run(scenario())


def test_runtime_shadow_does_not_enter_v1_contributor_evidence(tmp_path) -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    async def gated_query_call(plan, collections):
        started.set()
        await release.wait()
        return _no_hit_trace(plan, collections)

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'legacy_v1': True})

    async def gis_call(payload):
        raise AssertionError('KB-GEO collection must not invoke deterministic GIS calls')

    async def scenario():
        dispatcher = GeoMASRAGDispatcher(
            _settings(tmp_path, shadow=True),
            gated_query_call,
        )
        owner, evidence = await _collect_chunk_evidence(
            tasks=(
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='owner',
                    task_id='KB-OWNER',
                    payload={},
                ),
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='contributor',
                    task_id='KB-EVIDENCE',
                    payload={},
                ),
            ),
            next_batch={
                'batch_id': 'KB-GEO',
                'producer': 'KBagent_yulong',
                'fields': [
                    {
                        'field_key': 'geotizer_object.v1.r010.a01',
                        'row_id': 10,
                        'group': 'Геология',
                        'element': 'Стратиграфия',
                        'attribute_name': 'Описание',
                    }
                ],
            },
            object_name='Тестовая площадь',
            run_id='run-v1-visible',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=dispatcher,
            datacube=None,
            knowledge_search_plan={
                'object_profile': {
                    'project_resolution': {
                        'object_name': 'Тестовая площадь',
                        'project_id': 'project-1',
                    }
                },
                'tiers': [
                    {
                        'tier_id': 'direct',
                        'relation_to_object': 'direct',
                        'query_terms': ['Тестовая площадь'],
                        'enabled': True,
                    }
                ],
            },
            vision_evidence_call=None,
            vision_project_id=None,
        )
        assert owner.task_id == 'KB-OWNER'
        assert json.loads(evidence[0]['output']) == {'legacy_v1': True}
        assert 'retrieval_plans' not in evidence[0]
        assert 'retrieval_traces' not in evidence[0]
        await started.wait()
        release.set()
        await drain_background_dispatches()

    asyncio.run(scenario())


def test_active_runtime_prefetches_gateway_trace_for_kb_contributor(tmp_path) -> None:
    async def query_call(plan, collections):
        return build_grounded_retrieval_trace(
            plan,
            {
                'documents': [['Стратиграфия площади представлена сланцами.']],
                'metadatas': [[
                    {
                        'document_id': 'doc-1',
                        'document_version': 'v1',
                        'page': 4,
                        'section_path': 'Геология/Стратиграфия',
                        'child_chunk_id': 'child-1',
                        'object_ids': json.dumps(
                            ['Тестовая площадь'],
                            ensure_ascii=False,
                        ),
                        'source_class': 'geological_report',
                        'temporal_role': 'not_temporal',
                    }
                ]],
                'distances': [[0.9]],
            },
            collections=collections,
            backend_path=['vector'],
        )

    async def agent_call(task, prompt, object_name, datacube):
        payload = json.loads(prompt)
        trace = payload['retrieval_traces'][0]
        hit = trace['hits'][0]
        return json.dumps(
            {
                'field_proposals': [
                    {
                        'field_key': 'geotizer_object.v1.r010.a01',
                        'value': 'сланцы',
                        'unit': None,
                        'value_origin': 'direct',
                        'relation_to_object': 'direct',
                        'source_id': 'doc-1',
                        'source_title': 'Геологический отчёт',
                        'source_locator': hit['source_locator'],
                        'query_id': trace['query_id'],
                        'retrieval_plan_id': trace['plan_id'],
                    }
                ]
            },
            ensure_ascii=False,
        )

    async def gis_call(payload):
        raise AssertionError('KB-GEO collection must not invoke deterministic GIS calls')

    async def scenario():
        dispatcher = GeoMASRAGDispatcher(
            _settings(tmp_path, active=True),
            query_call,
        )
        _, evidence = await _collect_chunk_evidence(
            tasks=(
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='owner',
                    task_id='KB-OWNER',
                    payload={},
                ),
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='contributor',
                    task_id='KB-EVIDENCE',
                    payload={},
                ),
            ),
            next_batch={
                'batch_id': 'KB-GEO',
                'producer': 'KBagent_yulong',
                'fields': [
                    {
                        'field_key': 'geotizer_object.v1.r010.a01',
                        'row_id': 10,
                        'group': 'Геология',
                        'element': 'Стратиграфия',
                        'attribute_name': 'Описание',
                    }
                ],
            },
            object_name='Тестовая площадь',
            run_id='run-active',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=dispatcher,
            datacube=None,
            knowledge_search_plan={
                'object_profile': {
                    'project_resolution': {
                        'object_name': 'Тестовая площадь',
                        'project_id': 'project-1',
                    }
                },
                'tiers': [
                    {
                        'tier_id': 'direct',
                        'relation_to_object': 'direct',
                        'query_terms': ['Тестовая площадь'],
                        'enabled': True,
                    }
                ],
            },
            vision_evidence_call=None,
            vision_project_id=None,
        )
        item = evidence[0]
        assert len(item['retrieval_traces']) == 1
        assert len(item['field_proposals']) == 1
        assert item['field_proposals'][0]['query_id'] == item['retrieval_traces'][0]['query_id']
        assert item['retrieval_traces'][0]['collections'] == ['geomas_rag_v2']
        assert item['retrieval_traces'][0]['index_version'] == 'idx-1'

    asyncio.run(scenario())


def test_resource_coherence_runs_before_owner_receives_evidence() -> None:
    fields = [
        {
            'field_key': f'geotizer_object.v1.r050.a0{index}',
            'row_id': 50,
            'group': 'Resources',
            'element': 'Site estimate',
            'attribute_name': f'attribute-{index}',
        }
        for index in (1, 2, 3)
    ]

    def raw_proposal(field_key, estimate_id):
        return {
            'field_key': field_key,
            'value': field_key,
            'unit': 't',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': f'source-{estimate_id}',
            'source_title': estimate_id,
            'source_locator': {'document_id': f'doc-{estimate_id}'},
            'value_kind': 'resource_estimate',
            'entity_id': 'target-object',
            'entity_scope': 'site',
            'estimate_state': 'author_estimate',
            'resource_estimate_id': estimate_id,
            'site_name': 'Site 1',
        }

    async def agent_call(task, prompt, object_name, datacube):
        proposals = (
            [
                raw_proposal(fields[0]['field_key'], 'ESTIMATE-A'),
                raw_proposal(fields[1]['field_key'], 'ESTIMATE-A'),
            ]
            if task.task_id == 'SOURCE-A'
            else [raw_proposal(fields[2]['field_key'], 'ESTIMATE-B')]
        )
        return json.dumps({'field_proposals': proposals})

    async def gis_call(payload):
        raise AssertionError('resource batch must not call deterministic GIS')

    async def scenario():
        owner, evidence = await _collect_chunk_evidence(
            tasks=(
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='owner',
                    task_id='KB-RESOURCE-TECH',
                    payload={},
                ),
                AgentTask(
                    kind='kb',
                    producer='KBagent_yulong',
                    role='contributor',
                    task_id='SOURCE-A',
                    payload={},
                ),
                AgentTask(
                    kind='web',
                    producer='WEBagent_yulong',
                    role='contributor',
                    task_id='SOURCE-B',
                    payload={},
                ),
            ),
            next_batch={
                'batch_id': 'KB-RESOURCE-TECH',
                'producer': 'KBagent_yulong',
                'fields': fields,
            },
            object_name='Test area',
            run_id='resource-coherence-run',
            gis_call=gis_call,
            agent_call=agent_call,
            rag_dispatcher=None,
            datacube=None,
            knowledge_search_plan={},
            vision_evidence_call=None,
            vision_project_id=None,
        )
        assert owner.task_id == 'KB-RESOURCE-TECH'
        proposals = [
            proposal
            for item in evidence
            for proposal in item.get('field_proposals') or []
        ]
        assert {item['resource_estimate_id'] for item in proposals} == {
            'ESTIMATE-A'
        }
        diagnostic = next(
            item
            for item in evidence
            if item['route_id'] == 'RESOURCE-ESTIMATE-COHERENCE'
        )
        payload = json.loads(diagnostic['output'])
        assert payload['diagnostics'][0][
            'selected_resource_estimate_id'
        ] == 'ESTIMATE-A'

    asyncio.run(scenario())


def test_disabled_callable_does_not_execute_when_rolled_back(monkeypatch) -> None:
    for name in (
        'ENABLE_GEOMAS_RAG_V2',
        'ENABLE_GEOMAS_RAG_V2_SHADOW',
        'GEOMAS_RAG_V2_COLLECTIONS',
        'GEOMAS_RAG_V2_INDEX_VERSION',
    ):
        monkeypatch.delenv(name, raising=False)

    async def scenario():
        raw = await query_geomas_retrieval_plan(
            _plans()[0].as_dict(),
            __request__=object(),
            __user__={'id': 'user'},
        )
        assert json.loads(raw)['error']['code'] == 'geomas_rag_v2_not_executable'

    asyncio.run(scenario())
