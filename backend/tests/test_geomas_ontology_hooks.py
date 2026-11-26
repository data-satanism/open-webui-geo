"""Tests for the three `ENABLE_GEOMAS_ONTOLOGY` hooks and the run log entry, through the real functions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import open_webui.retrieval.utils as retrieval_utils
from open_webui.services.artifacts.geotizer.owner_envelope import (
    build_batch_tasks,
    refuse_prose_in_numeric_rows,
    refuse_values_the_ontology_rules_out,
)
from open_webui.services.artifacts.geotizer.prompts import _contributor_prompt
from open_webui.services.artifacts.geotizer.workflow import (
    _produce_valid_owner_envelope,
    run_geotizer_workflow,
)
from open_webui.services.core.tasks import AgentTask
from open_webui.services.ontology.geomas import annotate_batch
from open_webui.services.project_evidence.retrieval import build_retrieval_plans

NUMBER_FIELD = 'geotizer_object.v1.r044.a03'
DATE_FIELD = 'geotizer_object.v1.r009.a01'
ENUM_FIELD = 'geotizer_object.v1.r013.a01'
KB_TASK = AgentTask(agent='kb', producer='kb', role='contributor', task_id='KB-EVIDENCE', payload={})
WEB_TASK = AgentTask(agent='web', producer='web', role='contributor', task_id='WEB-EVIDENCE', payload={})
KNOWLEDGE_PLAN = {
    'object_profile': {
        'project_resolution': {'object_name': 'Лекын-Тальбейская площадь', 'project_id': 'project-123'}
    },
    'tiers': [
        {
            'tier_id': 'direct',
            'relation_to_object': 'direct',
            'query_terms': ['Лекын-Тальбейская площадь'],
            'enabled': True,
        }
    ],
}
PROMPT_DIGEST_AT_60B35222D = {
    False: 'c84b5c8ebfddf79da830b1cc4f2b326b3617f3027e271762f25cbee0927a66f8',
    True: '4a04e2802c7bd3bcd443fff88690937eaaaa0eaf2a81352ff83298778f9f8241',
}
ONTOLOGY_RULE = 'ontology.terms are labels and synonyms'


def resource_batch() -> dict:
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r044.a01',
                'row_id': 44,
                'group': 'Ресурсы',
                'element': 'Ресурсный потенциал',
                'attribute_name': 'количество',
            },
            {
                'field_key': 'geotizer_object.v1.r058.a01',
                'row_id': 58,
                'group': 'Технология',
                'element': 'Обогащение',
                'attribute_name': 'метод',
            },
        ],
    }


def prompt(batch: dict, *, task: AgentTask = KB_TASK, rag_v2: bool = False) -> str:
    return _contributor_prompt(
        object_name='Лекын-Тальбейская площадь',
        run_id='run-1',
        task=task,
        next_batch=batch,
        knowledge_search_plan=KNOWLEDGE_PLAN,
        kb_collections=['kb-lekyn'],
        rag_v2_enabled=rag_v2,
    )


@pytest.mark.parametrize('rag_v2', [False, True])
def test_an_unannotated_kb_prompt_is_the_prompt_60b35222d_builds(rag_v2):
    built = prompt(resource_batch(), rag_v2=rag_v2)

    assert hashlib.sha256(built.encode('utf-8')).hexdigest() == PROMPT_DIGEST_AT_60B35222D[rag_v2]


def test_an_annotated_batch_carries_its_terms_into_the_kb_prompt():
    payload = json.loads(prompt(annotate_batch(resource_batch())))

    terms = payload['bounded_fields'][0]['ontology']['terms']
    assert 'Оценка ресурсов' in terms
    assert sum(ONTOLOGY_RULE in rule for rule in payload['rules']) == 1


def test_the_web_specialist_gets_no_ontology_rule():
    payload = json.loads(prompt(annotate_batch(resource_batch()), task=WEB_TASK))

    assert not any(ONTOLOGY_RULE in rule for rule in payload['rules'])


def test_rag_v2_plans_carry_the_terms_in_should_terms():
    plain = build_retrieval_plans(resource_batch(), KNOWLEDGE_PLAN, run_id='run-1', object_name='Лекын')
    annotated = build_retrieval_plans(
        annotate_batch(resource_batch()), KNOWLEDGE_PLAN, run_id='run-1', object_name='Лекын'
    )

    plain_terms = {term for plan in plain for term in plan.as_dict()['should_terms']}
    annotated_terms = {term for plan in annotated for term in plan.as_dict()['should_terms']}
    assert 'оценка ресурсов' not in {term.casefold() for term in plain_terms}
    assert 'оценка ресурсов' in {term.casefold() for term in annotated_terms}


def _batch(*fields: tuple[str, str]) -> dict:
    return {
        'batch_id': 'KB-ONTOLOGY',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {'field_key': key, 'row_id': int(key.split('.r')[1][:3]), 'attribute_name': name}
            for key, name in fields
        ],
        'evidence_routes': [
            {
                'route_id': 'KB-EVIDENCE',
                'producer': 'kb',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            }
        ],
    }


def _envelope(field_key: str, value) -> dict:
    return {
        'patches': [
            {
                'field_key': field_key,
                'status': 'filled',
                'value': value,
                'unit': None,
                'value_origin': 'direct',
                'source_refs': ['kb__doc__1'],
                'source_locator': {'page': 3},
            }
        ]
    }


REFUSED = [
    (NUMBER_FIELD, 'средние содержания', 'по данным отчёта значительные', 'ontology_value_type'),
    (DATE_FIELD, 'дата', 'в ходе работ', 'ontology_value_type'),
    (ENUM_FIELD, 'нет / да', 'возможно', 'ontology_codelist'),
]


@pytest.mark.parametrize(('field_key', 'attribute_name', 'value', 'rule'), REFUSED)
def test_a_value_the_field_type_rules_out_goes_to_the_expert(field_key, attribute_name, value, rule):
    batch = annotate_batch(_batch((field_key, attribute_name)))

    repaired, notes = refuse_values_the_ontology_rules_out(batch, _envelope(field_key, value))

    patch = repaired['patches'][0]
    reason = patch['source_locator']['if_not_why_not']
    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] == value
    assert reason['reason_kind'] == 'excluded_by_rule'
    assert reason['rule'] == rule
    assert reason['decided_by'] == 'policy'
    assert 'geoteaser 1.0.0' in reason['stated_reason']
    assert len(notes) == 1


def test_the_number_case_is_one_the_prose_rule_does_not_cover():
    batch = _batch((NUMBER_FIELD, 'средние содержания'))

    repaired, notes = refuse_prose_in_numeric_rows(batch, _envelope(NUMBER_FIELD, 'по данным отчёта значительные'))

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


@pytest.mark.parametrize(('field_key', 'attribute_name', 'value', 'rule'), REFUSED)
def test_a_field_without_ontology_is_untouched(field_key, attribute_name, value, rule):
    envelope = _envelope(field_key, value)

    repaired, notes = refuse_values_the_ontology_rules_out(_batch((field_key, attribute_name)), envelope)

    assert repaired == envelope
    assert notes == []


@pytest.mark.parametrize(
    ('field_key', 'attribute_name', 'value'),
    [
        (NUMBER_FIELD, 'средние содержания', '12,5 т'),
        (DATE_FIELD, 'дата', '12.05.2004'),
        (DATE_FIELD, 'дата', '2019'),
        (ENUM_FIELD, 'нет / да', ' Да '),
        (ENUM_FIELD, 'нет / да', 'Да.'),
        (ENUM_FIELD, 'нет / да', 'да;'),
        (ENUM_FIELD, 'нет / да', '«Нет»'),
    ],
)
def test_a_value_that_fits_its_type_is_untouched(field_key, attribute_name, value):
    envelope = _envelope(field_key, value)

    repaired, notes = refuse_values_the_ontology_rules_out(
        annotate_batch(_batch((field_key, attribute_name))), envelope
    )

    assert repaired == envelope
    assert notes == []


def test_a_patch_that_is_not_filled_is_untouched():
    envelope = _envelope(DATE_FIELD, 'в ходе работ')
    envelope['patches'][0]['status'] = 'not_found'

    repaired, _ = refuse_values_the_ontology_rules_out(annotate_batch(_batch((DATE_FIELD, 'дата'))), envelope)

    assert repaired == envelope


def _owner_run(batch: dict, agent_call) -> dict:
    owner = next(task for task in build_batch_tasks(batch) if task.role == 'owner')
    return asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': batch, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=batch,
            object_name='Лекын-Тальбейская площадь',
            run_id='run-ontology',
            agent_call=agent_call,
            query_drain=None,
            datacube=None,
        )
    )


def _rule_of(result: dict, field_key: str):
    patch = next(patch for patch in result['patches'] if patch['field_key'] == field_key)
    return patch['status'], ((patch.get('source_locator') or {}).get('if_not_why_not') or {}).get('rule')


def test_the_main_chain_refuses_through_the_owner_envelope():
    batch = annotate_batch(_batch((DATE_FIELD, 'дата')))
    envelope = {
        **{key: batch[key] for key in ('batch_id', 'producer', 'policy_version', 'template_version')},
        'source_inventory': [{'source_id': 'kb__doc__1', 'source_type': 'kb', 'title': 'Отчёт'}],
        **_envelope(DATE_FIELD, 'в ходе работ'),
    }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps(envelope, ensure_ascii=False)

    assert _rule_of(_owner_run(batch, agent_call), DATE_FIELD) == ('requires_expert_review', 'ontology_value_type')


def test_the_salvage_chain_refuses_a_recovered_proposal():
    batch = annotate_batch(_batch((DATE_FIELD, 'дата'), ('geotizer_object.v1.r009.a02', 'номер')))
    raw = json.dumps(
        {
            'field_proposals': [
                {
                    'field_key': DATE_FIELD,
                    'value': 'в ходе работ',
                    'unit': None,
                    'value_origin': 'direct',
                    'value_kind': 'other',
                    'temporal_role': 'current_fact',
                    'entity_role': 'target_object',
                    'relation_to_object': 'direct',
                    'source_id': 'owner-proposal-1',
                    'source_title': 'Отчёт',
                    'source_locator': {'page': 4},
                    'retrieval_note': 'Дата на странице 4.',
                }
            ]
        },
        ensure_ascii=False,
    )

    async def agent_call(task, prompt, object_name, datacube):
        return raw

    assert _rule_of(_owner_run(batch, agent_call), DATE_FIELD) == ('requires_expert_review', 'ontology_value_type')


def _finalized_run_log(*, ontology: bool) -> dict:
    sent: dict = {}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'ontology-e2e',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': None,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'ontology-e2e', 'next_batch': None}
        sent.update(payload)
        return {
            'workflow_status': 'finalized',
            'run_id': 'ontology-e2e',
            'xlsx': {'download_path': '/geotizer/files/ontology-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []})

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            ontology=ontology,
        )
    )
    return sent.get('run_log') or {}


def test_the_run_log_names_the_ontology_when_it_is_on():
    record = _finalized_run_log(ontology=True)['ontology']

    assert [(p['id'], p['version']) for p in record['packages']] == [
        ('geomas-core', '1.2.0'),
        ('geoteaser', '1.0.0'),
    ]


def test_the_run_log_has_no_ontology_entry_when_it_is_off():
    assert 'ontology' not in _finalized_run_log(ontology=False)


def test_the_workflow_annotates_each_batch_it_takes():
    seen: list[str] = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'ontology-batch',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': _batch((DATE_FIELD, 'дата')),
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'ontology-batch', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'ontology-batch',
            'xlsx': {'download_path': '/geotizer/files/ontology-batch/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        seen.append(prompt)
        return json.dumps({'patches': []})

    for ontology in (False, True):
        seen.clear()
        asyncio.run(
            run_geotizer_workflow(
                object_name='Лекын',
                project_id=None,
                model_run_id=None,
                run_id=None,
                allow_draft=True,
                gis_call=gis_call,
                agent_call=agent_call,
                ontology=ontology,
            )
        )
        assert seen
        assert any(ONTOLOGY_RULE in sent for sent in seen) is ontology


class _NoHits:
    def search(self, **_kwargs):
        return None


def _embedded_queries(monkeypatch, *, enabled: bool, queries: list[str]) -> list[str]:
    embedded: list[str] = []

    async def get_many(*_keys):
        return {'rag.enable_hybrid_search': False, 'rag.embedding_query_prefix': None}

    async def embedding_function(texts, prefix=None):
        embedded.extend(texts)
        return [[0.0] for _ in texts]

    monkeypatch.setattr(retrieval_utils, 'ENABLE_GEOMAS_ONTOLOGY', enabled)
    monkeypatch.setattr(retrieval_utils, 'Config', SimpleNamespace(get_many=get_many))
    monkeypatch.setattr(retrieval_utils, 'get_vector_db_client', lambda: _NoHits())
    asyncio.run(
        retrieval_utils.query_collection(
            None,
            collection_names=['kb-lekyn'],
            queries=queries,
            embedding_function=embedding_function,
            k=4,
        )
    )
    return embedded


def test_chat_retrieval_embeds_the_widened_query_when_the_switch_is_on(monkeypatch):
    embedded = _embedded_queries(monkeypatch, enabled=True, queries=['запасы C2 по Лекыну'])

    assert embedded[0] == 'запасы C2 по Лекыну'
    assert len(embedded) == 2
    assert 'Оценка ресурсов' in embedded[1]


def test_chat_retrieval_embeds_the_original_queries_when_the_switch_is_off(monkeypatch):
    assert _embedded_queries(monkeypatch, enabled=False, queries=['запасы C2 по Лекыну']) == [
        'запасы C2 по Лекыну'
    ]


@pytest.mark.parametrize('enabled', [False, True])
def test_a_question_that_names_no_concept_gets_no_extra_query(monkeypatch, enabled):
    assert _embedded_queries(monkeypatch, enabled=enabled, queries=['Какая стадия работ?']) == [
        'Какая стадия работ?'
    ]


GEOMAS_LOGGER = 'open_webui.services.ontology.geomas'


def _geomas_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == GEOMAS_LOGGER]


def test_a_widening_call_logs_its_terms_at_info_level_without_the_query(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger=GEOMAS_LOGGER):
        _embedded_queries(monkeypatch, enabled=True, queries=['запасы C2 по Лекыну', 'Какая стадия работ?'])

    [record] = _geomas_records(caplog)
    message = record.getMessage()
    assert record.levelno == logging.INFO
    assert 'geomas-core 1.2.0' in message
    assert 'expanded queries: 1,' in message
    assert 'Оценка ресурсов' in message
    assert 'Лекыну' not in message


def test_a_call_that_widens_nothing_logs_no_line(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG, logger=GEOMAS_LOGGER):
        _embedded_queries(monkeypatch, enabled=True, queries=['Какая стадия работ?'])

    assert _geomas_records(caplog) == []


def _switch(environment: dict[str, str]) -> bool:
    source = (Path(retrieval_utils.__file__).resolve().parents[1] / 'config.py').read_text(encoding='utf-8')
    [line] = [line for line in source.splitlines() if line.startswith('ENABLE_GEOMAS_ONTOLOGY = ')]
    namespace = {'os': SimpleNamespace(getenv=lambda key, default=None: environment.get(key, default))}
    exec(line, namespace)
    return namespace['ENABLE_GEOMAS_ONTOLOGY']


@pytest.mark.parametrize(
    ('environment', 'enabled'),
    [
        ({}, True),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'true'}, True),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'TRUE'}, True),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'false'}, False),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'False'}, False),
        ({'ENABLE_GEOMAS_ONTOLOGY': '0'}, False),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'off'}, False),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'no'}, False),
        ({'ENABLE_GEOMAS_ONTOLOGY': 'ture'}, False),
    ],
    ids=['unset', 'true', 'TRUE', 'false', 'False', '0', 'off', 'no', 'ture'],
)
def test_the_switch_is_on_when_unset_or_true_and_off_for_any_other_value(environment, enabled):
    assert _switch(environment) is enabled
