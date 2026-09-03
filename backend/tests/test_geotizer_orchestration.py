from __future__ import annotations

import asyncio
import json
from itertools import permutations

import pytest
from open_webui.services.artifacts.geotizer.prompts import (
    _contributor_prompt,
    _contributors_for_batch,
    _gis_infrastructure_rules,
    _needs_deterministic_infrastructure,
    _receives_deterministic_gis,
    _owner_prompt,
)
from open_webui.services.artifacts.geotizer.terminal import (
    _gis_error_user_message,
    _proxy_source_report_paths,
    _terminal_outcome,
)
from open_webui.services.artifacts.geotizer.workflow import (
    _deterministic_grr_schedule_evidence,
    _deterministic_infrastructure_evidence,
    _produce_valid_owner_envelope,
    run_geotizer_workflow,
)
from open_webui.services.artifacts.geotizer.observability import (
    owner_attempt_diagnostic,
)
from open_webui.services.artifacts.geotizer.owner_envelope import (
    build_accepted_field_summary,
    build_batch_tasks,
    execution_mode_for_task,
    extract_owner_envelope,
    merge_owner_envelopes,
    owner_failure_envelope,
    partition_owner_batch,
    promote_assemble_conclusions,
    recover_backend_owned_owner_envelope,
)
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.core.tasks import AgentTask
from open_webui.services.geotizer.errors import GeotizerOrchestrationError
from open_webui.services.core.text import bounded_text, extract_json_object
from open_webui.services.project_evidence.proposals import (
    apply_structured_external_field_proposals,
    apply_structured_gis_field_proposals,
    build_knowledge_search_plan,
    correct_explicitly_derived_value_origins,
    normalize_contributor_evidence,
    normalize_gis_field_proposals,
    normalize_gis_object_profile,
    repair_negative_provenance,
)

# The `PRODUCER_KIND_MAP` valve as a contour talking to today's `gis_service`
# would set it. Written out here and passed at every call site below, because
# neither `build_batch_tasks` nor `run_geotizer_workflow` has a default: the
# routing lives in Workspace now, and a test that leaned on a default would be
# exercising a fallback the production path does not have.
PRODUCER_KINDS = {
    'gis': 'gis',
    'kb': 'kb',
    'web': 'web',
    'skilled': 'skilled',
}


def test_terminal_outcome_reports_backend_audit_success() -> None:
    outcome = _terminal_outcome(
        {
            'audit': {
                'summary': {'failed': 0, 'warnings': 0},
                'gates': {
                    'publication': 'allowed',
                    'draft_xlsx_rendering': 'allowed',
                },
            },
            'xlsx': {'download_path': '/geotizer/files/run/geotizer.xlsx'},
        }
    )

    assert outcome['status'] == 'completed'
    assert outcome['audit_passed'] is True
    assert outcome['publication'] == 'allowed'


def test_terminal_outcome_exposes_blocked_publication_with_draft() -> None:
    outcome = _terminal_outcome(
        {
            'audit': {
                'checks': [{'check_id': 'unresolved_conflicts', 'status': 'failed'}],
                'summary': {'failed': 1, 'warnings': 2},
                'gates': {
                    'publication': 'blocked',
                    'draft_xlsx_rendering': 'allowed',
                },
            },
            'xlsx': {'download_path': '/geotizer/files/run/geotizer.xlsx'},
        }
    )

    assert outcome == {
        'status': 'draft_ready_publication_blocked',
        'headline': ('сформирован как черновик; audit выявил ошибки, публикация заблокирована'),
        'audit_passed': False,
        'failed': 1,
        'warnings': 2,
        'publication': 'blocked',
        'draft_xlsx_rendering': 'allowed',
        'artifact_available': True,
    }


def test_terminal_outcome_does_not_claim_success_without_artifact() -> None:
    outcome = _terminal_outcome(
        {
            'audit': {
                'summary': {'failed': 1, 'warnings': 0},
                'gates': {
                    'publication': 'blocked',
                    'draft_xlsx_rendering': 'blocked',
                },
            }
        }
    )

    assert outcome['status'] == 'blocked'
    assert outcome['audit_passed'] is False


@pytest.mark.parametrize(
    ('retrieval_note', 'expected_origin'),
    [
        (
            'Тип переработки по аналогии с рудно-россыпными месторождениями',
            'analogue',
        ),
        (
            'Главные нерудные минералы по региональному геологическому контексту',
            'analogue',
        ),
        (
            'Второстепенные минералы-носители на основе региональной геологии',
            'analogue',
        ),
        (
            'Вредные примеси по геохимическим данным региона',
            'analogue',
        ),
        (
            'Категория сложности по модели prospectivity',
            'calculated',
        ),
        (
            'Тип отработки по типу месторождения',
            'calculated',
        ),
        (
            'Прямое значение атрибута объекта',
            'direct',
        ),
    ],
)
def test_explicit_derivation_note_corrects_false_direct_origin(
    retrieval_note,
    expected_origin,
):
    value = envelope()
    value['patches'][0].update(
        {
            'status': 'filled',
            'value': 'candidate',
            'value_origin': 'direct',
            'retrieval_note': retrieval_note,
        }
    )

    corrected = correct_explicitly_derived_value_origins(value)

    assert corrected['patches'][0]['value_origin'] == expected_origin
    assert value['patches'][0]['value_origin'] == 'direct'


@pytest.mark.parametrize('declared_origin', ['calculated', 'analogue'])
def test_explicit_origin_is_never_downgraded(declared_origin):
    value = envelope()
    value['patches'][0].update(
        {
            'status': 'filled',
            'value': 'candidate',
            'value_origin': declared_origin,
            'retrieval_note': 'Прямое значение атрибута объекта',
        }
    )

    corrected = correct_explicitly_derived_value_origins(value)

    assert corrected['patches'][0]['value_origin'] == declared_origin


def test_correction_runs_after_mislabeled_structured_gis_proposal():
    value = envelope()
    value['patches'][0].update(
        {
            'status': 'not_found',
            'value': None,
            'value_origin': None,
        }
    )
    evidence = [
        {
            'source_domain': 'gis',
            'field_proposals': [
                {
                    'field_key': 'f1',
                    'value': '2-3',
                    'unit': 'months',
                    'value_origin': 'direct',
                    'relation_to_object': 'regional_context',
                    'source_id': 'gis-climate',
                    'source_title': 'Polar Urals climate',
                    'source_locator': {
                        'project_id': 'Object',
                        'layer_id': 'location',
                        'feature_or_query': 'regional climate inference',
                    },
                    'retrieval_note': ('Value derived from regional analogue data'),
                }
            ],
        }
    ]

    composed = apply_structured_gis_field_proposals(
        batch(),
        value,
        evidence,
    )
    corrected = correct_explicitly_derived_value_origins(composed)

    assert corrected['patches'][0]['value_origin'] == 'analogue'


def test_prospectivity_score_cannot_fill_resource_quantity():
    resource_batch = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'resource',
                'row_id': 44,
                'attribute_name': 'значение',
            }
        ],
    }
    owner = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [{'source_id': 'negative', 'source_type': 'knowledge_base'}],
        'patches': [
            {
                'field_key': 'resource',
                'value': None,
                'status': 'not_found',
                'source_refs': ['negative'],
                'source_locator': {'query': 'resource search'},
            }
        ],
    }
    evidence = [
        {
            'source_domain': 'kb',
            'field_proposals': [
                {
                    'field_key': 'resource',
                    'value': 0.94,
                    'unit': None,
                    'value_origin': 'calculated',
                    'value_kind': 'prospectivity_score',
                    'temporal_role': 'current_fact',
                    'entity_role': 'target_object',
                    'relation_to_object': 'direct',
                    'source_id': 'datacube-score',
                    'source_title': 'DataCube score',
                    'source_locator': {'artifact': 'scores.csv'},
                    'retrieval_note': 'Calculated prospectivity score.',
                }
            ],
        }
    ]

    composed = apply_structured_external_field_proposals(
        resource_batch,
        owner,
        evidence,
    )

    assert composed['patches'][0]['status'] == 'not_found'


def test_typed_calculated_resource_estimate_is_accepted():
    resource_batch = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'resource',
                'row_id': 44,
                'attribute_name': 'значение',
            }
        ],
    }
    owner = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [{'source_id': 'negative', 'source_type': 'knowledge_base'}],
        'patches': [
            {
                'field_key': 'resource',
                'value': None,
                'status': 'not_found',
                'source_refs': ['negative'],
                'source_locator': {'query': 'resource search'},
            }
        ],
    }
    evidence = [
        {
            'source_domain': 'kb',
            'field_proposals': [
                {
                    'field_key': 'resource',
                    'value': 12.5,
                    'unit': 'т Au',
                    'value_origin': 'calculated',
                    'value_kind': 'resource_estimate',
                    'temporal_role': 'current_fact',
                    'entity_role': 'target_object',
                    'entity_id': 'ore-node-1',
                    'entity_scope': 'ore_node',
                    'estimate_state': 'author_estimate',
                    'resource_estimate_id': 'estimate-1',
                    'source_document_id': 'report-v1',
                    'source_url': '/api/v1/files/report-v1',
                    'relation_to_object': 'direct',
                    'source_id': 'resource-calculation',
                    'source_title': 'Resource calculation',
                    'source_locator': {'document': 'report', 'page': 42},
                    'retrieval_note': ('Calculated resource estimate from documented volume and grade assumptions.'),
                }
            ],
        }
    ]

    composed = apply_structured_external_field_proposals(
        resource_batch,
        owner,
        evidence,
    )

    assert composed['patches'][0]['status'] == 'filled'
    assert composed['patches'][0]['value_origin'] == 'calculated'
    assert composed['patches'][0]['source_locator']['value_kind'] == ('resource_estimate')
    assert any(source.get('url') == '/api/v1/files/report-v1' for source in composed['source_inventory'])


def test_resource_site_without_named_identity_is_rejected():
    resource_batch = {
        **batch(),
        'batch_id': 'KB-RESOURCE-TECH',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r050.a01',
                'row_id': 50,
                'attribute_name': 'значение',
            }
        ],
    }
    raw = envelope()
    raw['batch_id'] = 'KB-RESOURCE-TECH'
    raw['patches'][0].update(
        {
            'field_key': 'geotizer_object.v1.r050.a01',
            'value': None,
            'status': 'not_found',
            'value_origin': None,
        }
    )
    proposal = {
        'field_key': 'geotizer_object.v1.r050.a01',
        'value': 10,
        'unit': 'т',
        'value_origin': 'calculated',
        'value_kind': 'resource_estimate',
        'entity_role': 'target_object',
        'entity_id': 'slot-1',
        'entity_scope': 'named_subarea',
        'estimate_state': 'conditional_p1',
        'resource_estimate_id': 'estimate-slot-1',
        'source_document_id': 'project-v1',
        'relation_to_object': 'direct',
        'source_id': 'project',
        'source_title': 'Project',
        'source_locator': {'page': 42},
        'retrieval_note': 'Commodity split labeled as Site 1.',
    }

    result = apply_structured_external_field_proposals(
        resource_batch,
        raw,
        [{'source_domain': 'kb', 'field_proposals': [proposal]}],
    )

    assert result['patches'][0]['status'] == 'not_found'


def test_target_object_cannot_fill_analogue_row():
    resource_batch = {
        **batch(),
        'batch_id': 'KB-RESOURCE-TECH',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r056.a01',
                'row_id': 56,
                'attribute_name': 'название',
            }
        ],
    }
    raw = envelope()
    raw['batch_id'] = 'KB-RESOURCE-TECH'
    raw['patches'][0].update(
        {
            'field_key': 'geotizer_object.v1.r056.a01',
            'value': None,
            'status': 'not_found',
            'value_origin': None,
        }
    )
    proposal = {
        'field_key': 'geotizer_object.v1.r056.a01',
        'value': 'Target',
        'value_origin': 'analogue',
        'value_kind': 'deposit_type',
        'entity_role': 'target_object',
        'entity_id': 'target',
        'entity_scope': 'analogue_deposit',
        'estimate_state': 'analogue',
        'analogue_relation': 'national_or_global_analogue',
        'source_document_id': 'presentation-v1',
        'relation_to_object': 'direct',
        'source_id': 'presentation',
        'source_title': 'Presentation',
        'source_locator': {'page': 7},
        'retrieval_note': 'Target object reused as analogue.',
    }

    result = apply_structured_external_field_proposals(
        resource_batch,
        raw,
        [{'source_domain': 'kb', 'field_proposals': [proposal]}],
    )

    assert result['patches'][0]['status'] == 'not_found'


def test_geology_hierarchy_requires_exact_entity_scope():
    geology_batch = {
        **batch(),
        'batch_id': 'KB-GEO',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r015.a01',
                'row_id': 15,
                'attribute_name': 'название',
            }
        ],
    }
    raw = envelope()
    raw['batch_id'] = 'KB-GEO'
    raw['patches'][0].update(
        {
            'field_key': 'geotizer_object.v1.r015.a01',
            'value': None,
            'status': 'not_found',
            'value_origin': None,
        }
    )
    proposal = {
        'field_key': 'geotizer_object.v1.r015.a01',
        'value': 'Polar Urals',
        'value_origin': 'direct',
        'entity_id': 'polar-urals',
        'entity_scope': 'geographic_region',
        'source_document_id': 'project-v1',
        'relation_to_object': 'direct',
        'source_id': 'project',
        'source_title': 'Project',
        'source_locator': {'page': 47},
        'retrieval_note': 'Geographic location.',
    }

    result = apply_structured_external_field_proposals(
        geology_batch,
        raw,
        [{'source_domain': 'kb', 'field_proposals': [proposal]}],
    )

    assert result['patches'][0]['status'] == 'not_found'


def test_project_presentation_disagreement_becomes_conflicted():
    plan_batch = {
        **batch(),
        'batch_id': 'KB-GRR-FACTORS',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r073.a01',
                'row_id': 73,
                'attribute_name': 'стоимость',
            }
        ],
    }
    raw = envelope()
    raw['batch_id'] = 'KB-GRR-FACTORS'
    raw['patches'][0].update(
        {
            'field_key': 'geotizer_object.v1.r073.a01',
            'value': None,
            'status': 'not_found',
            'value_origin': None,
        }
    )
    proposals = [
        {
            'field_key': 'geotizer_object.v1.r073.a01',
            'value': value,
            'unit': 'руб.',
            'value_origin': 'direct',
            'value_kind': 'planned_cost',
            'temporal_role': 'approved_plan',
            'work_stage': 'prospecting',
            'source_class': source_class,
            'source_document_id': source_id,
            'entity_role': 'target_object',
            'relation_to_object': 'direct',
            'source_id': source_id,
            'source_title': source_id,
            'source_url': f'/api/v1/files/{source_id}',
            'source_locator': {'page': page},
            'retrieval_note': 'Direct plan cost.',
        }
        for value, source_class, source_id, page in (
            (98_000_000, 'project_document', 'project-v1', 95),
            (1_827_450_000, 'presentation', 'presentation-v1', 12),
        )
    ]

    result = apply_structured_external_field_proposals(
        plan_batch,
        raw,
        [{'source_domain': 'kb', 'field_proposals': proposals}],
    )

    assert result['patches'][0]['status'] == 'conflicted'
    assert result['patches'][0]['value'] is None
    assert len(result['patches'][0]['source_refs']) == 2


def test_assemble_failure_contains_visible_review_hypothesis():
    assemble = {
        'batch_id': 'ASSEMBLE',
        'producer': 'skilled',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'factor',
                'row_id': 91,
                'element': 'Факторы осложняющие проект',
                'attribute_name': 'фактор 1',
            }
        ],
    }

    failed = owner_failure_envelope(
        assemble,
        run_id='run',
        attempts=3,
        feedback=['invalid JSON'],
        object_name='Лекын-Тальбейская площадь',
    )

    patch = failed['patches'][0]
    assert patch['status'] == 'requires_expert_review'
    assert patch['value'].startswith('ГИПОТЕЗА ДЛЯ ПРОВЕРКИ:')
    assert validate_owner_envelope(assemble, failed) == ()


def test_assemble_failure_uses_accepted_fact_in_factor_hypothesis():
    assemble = {
        'batch_id': 'ASSEMBLE',
        'producer': 'skilled',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'factor',
                'row_id': 91,
                'element': 'Факторы осложняющие проект',
                'attribute_name': 'фактор 1',
            }
        ],
    }

    failed = owner_failure_envelope(
        assemble,
        run_id='run',
        attempts=3,
        feedback=['invalid JSON'],
        object_name='Лекын-Тальбейская площадь',
        accepted_field_summary=[
            {
                'field_key': 'resource',
                'status': 'filled',
                'element': 'Ресурсы меди',
                'attribute_name': 'категория P2',
                'value': '1,2 млн т',
                'unit': 'т',
            }
        ],
    )

    value = failed['patches'][0]['value']
    assert 'Ресурсы меди' in value
    assert '1,2 млн т' in value
    assert 'возможен осложняющий фактор (фактор 1)' not in value
    assert validate_owner_envelope(assemble, failed) == ()


def test_accepted_field_summary_exposes_prior_values_for_assemble():
    summary = build_accepted_field_summary(
        {
            'fields': [
                {
                    'field_key': 'geo',
                    'group': 'Геология',
                    'element': 'Тип минерализации',
                    'attribute_name': 'тип',
                    'status': 'filled',
                    'value': 'золото-сульфидный',
                    'value_origin': 'direct',
                    'source_refs': ['report'],
                },
                {
                    'field_key': 'gap',
                    'status': 'not_found',
                    'value': None,
                },
            ]
        }
    )

    assert [item['field_key'] for item in summary] == ['geo']
    assert summary[0]['value'] == 'золото-сульфидный'


def batch():
    return {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {'field_key': 'f1', 'row_id': 1},
            {'field_key': 'f2', 'row_id': 1},
        ],
        'evidence_routes': [
            {
                'route_id': 'DATACUBE-EVIDENCE',
                'producer': 'DataCube Reviewer',
                'output': 'modeling_evidence',
                'satisfied_by': 'start.datacube',
            },
            {
                'route_id': 'KB-EVIDENCE',
                'producer': 'kb',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            },
            {
                'route_id': 'WEB-EVIDENCE',
                'producer': 'web',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            },
        ],
    }


def envelope():
    return {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {
                'source_id': 's1',
                'source_type': 'gis',
                'title': 'linked project',
            }
        ],
        'patches': [
            {
                'field_key': 'f1',
                'value': 'value',
                'status': 'filled',
                'source_refs': ['s1'],
                'source_locator': {'layer': 'licence'},
            },
            {
                'field_key': 'f2',
                'value': None,
                'status': 'not_found',
                'source_refs': ['s1'],
                'source_locator': {'query': 'field f2'},
            },
        ],
    }


def test_batch_plan_runs_contributors_before_exact_owner():
    tasks = build_batch_tasks(batch())
    assert [(task.role, task.producer) for task in tasks] == [
        ('contributor', 'kb'),
        ('contributor', 'web'),
        ('owner', 'gis'),
    ]


def test_batch_plan_owner_is_last_for_every_route_permutation():
    original = batch()
    for routes in permutations(original['evidence_routes']):
        value = {**original, 'evidence_routes': list(routes)}
        tasks = build_batch_tasks(value)
        assert tasks[-1].role == 'owner'
        assert tasks[-1].producer == value['producer']
        assert all(task.role == 'contributor' for task in tasks[:-1])
        assert all(task.producer != 'DataCube Reviewer' for task in tasks)


def test_all_owners_are_tool_free_and_contributors_keep_specialist_tools():
    tasks = build_batch_tasks(batch())

    assert all(execution_mode_for_task(task) == 'specialist_contributor' for task in tasks[:-1])
    assert execution_mode_for_task(tasks[-1]) == 'specialist_owner_completion'


def test_skilled_owner_uses_existing_tool_free_subagent():
    task = AgentTask(
        agent='skilled',
        producer='skilled',
        role='owner',
        task_id='ASSEMBLE',
        payload={},
    )

    assert execution_mode_for_task(task) == 'tool_free_owner'


def test_linked_project_gis_evidence_has_direct_authority():
    evidence = normalize_contributor_evidence(
        {
            'route_id': 'GIS-EVIDENCE',
            'producer': 'gis',
            'source_domain': 'gis',
            'relation_to_object': 'deposit_analogue',
            'output': ('geotizer_object.v1.r028.a01=1966; layer=IzuchA; feature=record-1'),
        }
    )

    assert evidence['relation_to_object'] == 'direct'
    assert evidence['evidence_authority'] == 'linked_gis_project'
    assert 'cannot negate' in evidence['negative_search_precedence']


def test_non_gis_evidence_cannot_self_promote_to_linked_project_authority():
    evidence = normalize_contributor_evidence(
        {
            'producer': 'kb',
            'source_domain': 'kb',
            'relation_to_object': 'deposit_analogue',
            'evidence_authority': 'contributor',
            'output': 'regional analogue',
        }
    )

    assert evidence['relation_to_object'] == 'deposit_analogue'
    assert evidence['evidence_authority'] == 'contributor'


def test_gis_field_proposals_require_bounded_key_value_origin_and_locator():
    proposals = normalize_gis_field_proposals(
        json.dumps(
            {
                'field_proposals': [
                    {
                        'field_key': 'f1',
                        'value': 150,
                        'unit': 'km',
                        'value_origin': 'calculated',
                        'relation_to_object': 'direct',
                        'source_id': 'gis-calc',
                        'source_title': 'GIS calculation',
                        'source_locator': {
                            'project_id': 'project',
                            'layer_id': 'routes',
                            'feature_or_query': 'sum(length)',
                        },
                        'retrieval_note': 'Calculated from route geometry.',
                    },
                    {
                        'field_key': 'foreign',
                        'value': 'must be ignored',
                        'value_origin': 'direct',
                        'source_id': 'foreign',
                        'source_locator': {'layer_id': 'foreign'},
                    },
                    {
                        'field_key': 'f2',
                        'value': 'untraceable',
                        'value_origin': 'analogue',
                        'source_id': 'missing-locator',
                        'retrieval_note': 'Analogue transfer.',
                    },
                ]
            }
        ),
        allowed_field_keys=['f1', 'f2'],
    )

    assert len(proposals) == 1
    assert proposals[0].field_key == 'f1'
    assert proposals[0].value == 150
    assert proposals[0].value_origin == 'calculated'


@pytest.mark.parametrize(
    'negative_value',
    (
        'Не указано',
        'Не указано отдельно',
        ' НЕ УКАЗАНО. ',
        'не указан',
        'Не указано в доступных материалах',
        'Не указано в документе',
        'не определено',
        'not_found',
        'not-found',
        'not found in available records',
        'unknown',
    ),
)
def test_owner_preflight_rejects_gis_negative_sentinel_as_filled(
    negative_value,
):
    value = envelope()
    value['patches'][0]['value'] = negative_value

    violations = validate_owner_envelope(batch(), value)

    assert any('negative marker cannot use status=filled' in violation for violation in violations)


@pytest.mark.parametrize(
    'negative_value',
    (
        'Не выявлено',
        'Не установлено',
        'Не обнаружено',
        'Не указано',
        'нет данных',
        'not found',
        '—',
    ),
)
def test_a_negative_finding_is_recorded_and_never_fills(negative_value):
    """The search is on the record; the cell it searched is not filled by it."""
    proposals = normalize_gis_field_proposals(
        json.dumps(
            {
                'field_proposals': [
                    {
                        'field_key': 'f2',
                        'value': negative_value,
                        'value_origin': 'direct',
                        'source_id': 'gis-negative',
                        'source_locator': {'layer_id': 'layer'},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        allowed_field_keys=['f2'],
    )
    assert [proposal.value for proposal in proposals] == [negative_value]

    before = envelope()
    after = apply_structured_gis_field_proposals(
        batch(),
        before,
        [
            {
                'source_domain': 'gis',
                'field_proposals': [proposal.as_dict() for proposal in proposals],
            }
        ],
    )
    patch = next(item for item in after['patches'] if item['field_key'] == 'f2')
    untouched = next(item for item in before['patches'] if item['field_key'] == 'f2')
    assert (patch['status'], patch['value']) == (untouched['status'], untouched['value'])
    recorded = patch['source_locator']['negative_findings']
    assert [item['value'] for item in recorded] == [negative_value]
    assert recorded[0]['source_ref'] in patch['source_refs']


@pytest.mark.parametrize(
    'substantive_value',
    (
        'нет',
        'Отсутствие балансовых запасов',
        'Содержание не указано отдельно, рассчитано по данным анализов',
        'Не применялась открытая разработка',
        # Run `6af7479f`, `KB-STUDY` D33-I33: «Разведка (+ТЭО), период 1..5»
        # answered «отсутствуют» with the note «Согласованные данные GIS и KB:
        # разведка не проводилась». Exploration was never carried out, two
        # sources agreed on it, and that is an answer about the object. It is
        # an empty finding, not a failed retrieval, and the coercion must not
        # take it -- six answers deleted to fix sixteen conflicts is not a fix.
        'отсутствуют',
        'Не выявлено',
    ),
)
def test_owner_preflight_keeps_substantive_negative_facts(
    substantive_value,
):
    value = envelope()
    value['patches'][0]['value'] = substantive_value

    assert validate_owner_envelope(batch(), value) == ()


def test_an_empty_finding_is_wider_than_a_failed_retrieval():
    """Two questions, two answers, and only one of them empties a cell.

    A failed retrieval means nothing was established, so the cell is coerced
    to `not_found`. An empty finding means a search completed and returned
    nothing, which can be the object's answer -- so it is only ever used to
    keep a source that found nothing from outvoting one that did.
    """
    from open_webui.services.core.vocabulary import (
        EMPTY_FINDING_MARKERS,
        NEGATIVE_VALUE_MARKERS,
        _is_empty_finding,
        _is_negative_value_marker,
    )

    assert NEGATIVE_VALUE_MARKERS < EMPTY_FINDING_MARKERS
    for value in ('Не выявлено', 'отсутствуют', 'Не установлено', '—'):
        assert _is_empty_finding(value)
        assert not _is_negative_value_marker(value)
    for value in ('нет данных', 'Не указано', 'unknown'):
        assert _is_empty_finding(value) and _is_negative_value_marker(value)


@pytest.mark.parametrize(
    ('value_origin', 'expected_applied'),
    (
        ('direct', True),
        ('calculated', True),
        ('analogue', True),
    ),
)
def test_structured_gis_proposals_fill_negative_owner_alternatives(
    value_origin,
    expected_applied,
):
    raw = envelope()
    raw['patches'][0] = {
        'field_key': 'f1',
        'value': None,
        'status': 'not_found',
        'source_refs': ['s1'],
        'source_locator': {'query': 'negative owner result'},
    }
    relation = 'deposit_analogue' if value_origin == 'analogue' else 'direct'
    proposal = {
        'field_key': 'f1',
        'value': 42,
        'unit': 'km',
        'value_origin': value_origin,
        'relation_to_object': relation,
        'source_id': f'gis-{value_origin}',
        'source_title': 'GIS proposal',
        'source_locator': {
            'project_id': 'project',
            'layer_id': 'layer',
            'feature_or_query': 'feature=1',
        },
        'retrieval_note': f'{value_origin} basis',
    }
    result = apply_structured_gis_field_proposals(
        batch(),
        raw,
        [
            {
                'source_domain': 'gis',
                'field_proposals': [proposal],
            }
        ],
    )

    assert (result['patches'][0]['status'] == 'filled') is expected_applied
    assert result['patches'][0]['value'] == 42
    assert result['patches'][0]['value_origin'] == value_origin
    assert result['patches'][0]['source_locator']['value_origin'] == value_origin
    assert validate_owner_envelope(batch(), result) == ()


def test_calculated_gis_proposal_does_not_replace_direct_owner_fact():
    raw = envelope()
    raw['patches'][0]['value_origin'] = 'direct'
    result = apply_structured_gis_field_proposals(
        batch(),
        raw,
        [
            {
                'source_domain': 'gis',
                'field_proposals': [
                    {
                        'field_key': 'f1',
                        'value': 'alternative',
                        'value_origin': 'calculated',
                        'relation_to_object': 'direct',
                        'source_id': 'gis-calc',
                        'source_title': 'GIS calculation',
                        'source_locator': {'layer_id': 'layer'},
                        'retrieval_note': 'Calculated fallback.',
                    }
                ],
            }
        ],
    )

    assert result['patches'][0]['value'] == 'value'
    assert result['patches'][0]['value_origin'] == 'direct'
    assert {source['source_id'] for source in result['source_inventory']} == {'s1'}


def test_owner_envelope_requires_explanation_for_derived_value():
    value = envelope()
    value['patches'][0]['value_origin'] = 'calculated'
    value['patches'][0].pop('retrieval_note', None)

    violations = validate_owner_envelope(batch(), value)

    assert any('calculated requires retrieval_note' in violation for violation in violations)


def test_conflicting_equal_priority_gis_proposals_are_preserved():
    raw = envelope()
    raw['patches'][0] = {
        'field_key': 'f1',
        'value': None,
        'status': 'not_found',
        'source_refs': ['s1'],
        'source_locator': {'query': 'negative owner result'},
    }
    proposals = [
        {
            'field_key': 'f1',
            'value': value,
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': f'gis-{value}',
            'source_title': 'GIS direct',
            'source_locator': {'layer_id': 'layer'},
            'retrieval_note': 'Direct fact.',
        }
        for value in ('left', 'right')
    ]
    result = apply_structured_gis_field_proposals(
        batch(),
        raw,
        [{'source_domain': 'gis', 'field_proposals': proposals}],
    )

    assert result['patches'][0]['status'] == 'conflicted'
    assert result['patches'][0]['value'] is None
    assert len(result['patches'][0]['source_refs']) == 2
    assert len(result['source_inventory']) == 3


def test_prompts_make_direct_gis_precedence_explicit():
    tasks = build_batch_tasks(
        {
            **batch(),
            'evidence_routes': [
                {
                    'route_id': 'GIS-EVIDENCE',
                    'producer': 'gis',
                    'output': 'evidence_bundle',
                    'satisfied_by': 'contributor_call',
                }
            ],
        },
    )
    contributor = tasks[0]
    contributor_request = json.loads(
        _contributor_prompt(
            object_name='Нияюская площадь',
            run_id='run',
            task=contributor,
            next_batch=batch(),
            knowledge_search_plan={},
        )
    )
    assert any('direct object evidence' in rule for rule in contributor_request['rules'])
    assert contributor_request['output_contract']['field_proposals'][0]['value_origin'] == 'direct|calculated|analogue'

    context = {
        'batch': batch(),
        'knowledge_search_plan': {},
        'contributor_evidence': [
            normalize_contributor_evidence(
                {
                    'source_domain': 'gis',
                    'output': 'field_key=f1; value=1966; layer=IzuchA',
                }
            )
        ],
    }
    owner_request = json.loads(
        _owner_prompt(
            context=context,
            attempt=1,
            feedback=None,
            previous_output='',
        )
    )
    rules = '\n'.join(owner_request['rules'])
    assert 'knowledge-base or web miss cannot negate' in rules
    assert 'do not return not_found solely because' in rules
    assert 'Calculated or analogue alternatives are allowed' in rules
    assert set(owner_request['output_contract']) == {
        'source_inventory',
        'patches',
    }
    assert owner_request['backend_owned_envelope']['batch_id'] == 'GIS-DC'
    assert 'Return only source_inventory and patches' in rules


def test_gis_dc_prompt_requires_deterministic_infrastructure_calculations():
    infrastructure_batch = {
        **batch(),
        'batch_id': 'GIS-DC',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'element': 'Расстояние до ближайшего населенного пункта',
            },
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'element': 'Объекты инфраструктуры в радиусе 50 км',
            },
        ],
    }

    rules = _gis_infrastructure_rules(infrastructure_batch)
    rendered = '\n'.join(rules)

    assert 'nearest_features or features_within_distance' in rendered
    assert 'geotizer_object.v1.r078.a01' in rendered
    assert 'rows r084 and r085' in rendered
    assert 'value_origin=calculated' in rendered
    assert 'raw distance in metres' in rendered


def test_non_infrastructure_gis_batch_has_no_infrastructure_rules():
    assert _gis_infrastructure_rules({**batch(), 'batch_id': 'GIS-GEO'}) == []


def test_only_real_infrastructure_fields_trigger_backend_calculation():
    assert _needs_deterministic_infrastructure(
        {
            **batch(),
            'fields': [
                {'field_key': 'geotizer_object.v1.r078.a01'},
            ],
        }
    )


def test_deterministic_infrastructure_replaces_only_gis_contributor():
    infrastructure_batch = {
        **batch(),
        'fields': [
            {'field_key': 'geotizer_object.v1.r078.a01'},
        ],
        'evidence_routes': [
            {
                'route_id': 'GIS',
                'producer': 'gis',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            },
            {
                'route_id': 'KB',
                'producer': 'kb',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            },
            {
                'route_id': 'WEB',
                'producer': 'web',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            },
        ],
    }
    tasks = build_batch_tasks(infrastructure_batch)

    contributors = _contributors_for_batch(infrastructure_batch, tasks)

    assert [task.agent for task in contributors] == ['kb', 'web']
    assert any(task.role == 'owner' for task in tasks)


def test_backend_infrastructure_object_is_normalized_as_json():
    async def gis_call(payload):
        assert payload == {
            'action': 'infrastructure_proposals',
            'run_id': 'run-1',
        }
        return {
            'workflow_status': 'ready',
            'field_proposals': [
                {
                    'field_key': 'geotizer_object.v1.r078.a01',
                    'value': 16.132,
                    'unit': 'км',
                    'value_origin': 'calculated',
                    'relation_to_object': 'direct',
                    'source_id': 'gis-infrastructure',
                    'source_title': 'Nearest settlement',
                    'source_locator': {
                        'project_id': 'project',
                        'target_layer_id': 'settlement_point',
                        'raw_distance_m': 16132.0,
                    },
                    'retrieval_note': ('Calculated from full GIS geometries.'),
                }
            ],
        }

    evidence = asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch={
                **batch(),
                'fields': [
                    {
                        'field_key': 'geotizer_object.v1.r078.a01',
                    }
                ],
            },
            run_id='run-1',
            allowed_field_keys=['geotizer_object.v1.r078.a01'],
            gis_call=gis_call,
        )
    )

    assert evidence[0]['field_proposals'][0]['value'] == 16.132
    assert not _needs_deterministic_infrastructure(batch())
    assert not _needs_deterministic_infrastructure(
        {
            **batch(),
            'batch_id': 'GIS-GEO',
            'fields': [
                {'field_key': 'geotizer_object.v1.r078.a01'},
            ],
        }
    )


def test_workflow_marks_gis_contributor_evidence_as_direct():
    gis_batch = {
        **batch(),
        'evidence_routes': [
            {
                'route_id': 'GIS-EVIDENCE',
                'producer': 'gis',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            }
        ],
    }

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-gis-authority',
                'object_name': 'Нияюская площадь',
                'datacube': {},
                'next_batch': gis_batch,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-gis-authority',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-gis-authority',
            'xlsx': {'download_path': ('/geotizer/files/run-gis-authority/geotizer.xlsx')},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'field_key=f1; value=1966; layer=IzuchA; feature=1'
        request = json.loads(prompt)
        evidence = request['context']['contributor_evidence']
        assert evidence[0]['source_domain'] == 'gis'
        assert evidence[0]['relation_to_object'] == 'direct'
        assert evidence[0]['evidence_authority'] == 'linked_gis_project'
        return json.dumps(envelope())

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Нияюская площадь',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )

    assert final['workflow_status'] == 'finalized'


def test_workflow_applies_structured_calculated_gis_proposal_before_submit():
    submitted = []
    gis_batch = {
        **batch(),
        'evidence_routes': [
            {
                'route_id': 'GIS-EVIDENCE',
                'producer': 'gis',
                'output': 'evidence_bundle',
                'satisfied_by': 'contributor_call',
            }
        ],
    }

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-gis-proposal',
                'object_name': 'Object',
                'datacube': {},
                'next_batch': gis_batch,
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-gis-proposal',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-gis-proposal',
            'xlsx': {'download_path': ('/geotizer/files/run-gis-proposal/geotizer.xlsx')},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return json.dumps(
                {
                    'field_proposals': [
                        {
                            'field_key': 'f1',
                            'value': 150,
                            'unit': 'km',
                            'value_origin': 'calculated',
                            'relation_to_object': 'direct',
                            'source_id': 'gis-routes',
                            'source_title': 'GIS route calculation',
                            'source_locator': {
                                'project_id': 'project',
                                'layer_id': 'routes',
                                'feature_or_query': 'sum(length)',
                            },
                            'retrieval_note': ('Calculated from linked-project route geometry.'),
                        }
                    ]
                }
            )
        value = envelope()
        value['patches'][0] = {
            'field_key': 'f1',
            'value': None,
            'status': 'not_found',
            'source_refs': ['s1'],
            'source_locator': {'query': 'owner negative result'},
        }
        return json.dumps(value)

    asyncio.run(
        run_geotizer_workflow(
            object_name='Object',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )

    patch = next(patch for patch in submitted[0]['patches'] if patch['field_key'] == 'f1')
    assert patch['status'] == 'filled'
    assert patch['value'] == 150
    assert patch['value_origin'] == 'calculated'
    assert patch['source_locator']['evidence_authority'] == ('linked_gis_project')


def test_an_owner_this_repository_does_not_recognise_is_still_planned():
    """The deletion, stated as a test.

    This used to raise: the producer was looked up in a table, then in a valve,
    and an unknown name ended the run here. Both layers are gone, so an owner
    name travels verbatim into the task and the refusal happens in
    `run_agent_task`, which owns the model valves and the tool surfaces and can
    therefore name what it does serve.

    Not a loosening. The run still stops on an agent the tool cannot serve --
    `unknown_agent` is `retryable: false` -- and it stops in the one place that
    knows the answer, instead of in two places that had to be kept in step.
    """
    value = batch()
    value['producer'] = 'InventedAgent'

    tasks = build_batch_tasks(value)

    assert tasks[-1].agent == 'InventedAgent'
    assert tasks[-1].producer == 'InventedAgent'
    assert tasks[-1].role == 'owner'


def test_partition_owner_batch_is_ordered_bounded_and_filters_routes():
    value = batch()
    value['fields'] = [{'field_key': f'f{index}', 'row_id': index // 2} for index in range(85)]
    value['evidence_routes'] = [
        {
            'route_id': 'KB-EVIDENCE',
            'producer': 'kb',
            'satisfied_by': 'contributor_call',
            'field_keys': [f'f{index}' for index in range(85)],
            'row_ids': list(range(43)),
        }
    ]
    chunks = partition_owner_batch(value, max_fields=40)
    assert [chunk['field_count'] for chunk in chunks] == [40, 40, 5]
    assert [chunk['owner_chunk'] for chunk in chunks] == [
        {'index': 1, 'total': 3},
        {'index': 2, 'total': 3},
        {'index': 3, 'total': 3},
    ]
    assert [field['field_key'] for chunk in chunks for field in chunk['fields']] == [f'f{index}' for index in range(85)]
    assert chunks[-1]['evidence_routes'][0]['field_keys'] == [f'f{index}' for index in range(80, 85)]


def test_partition_owner_batch_preserves_exact_field_partition():
    for field_count in range(1, 181):
        for max_fields in (1, 2, 3, 7, 17, 40, 59, 60):
            value = batch()
            value['fields'] = [{'field_key': f'f{index}', 'row_id': index} for index in range(field_count)]
            chunks = partition_owner_batch(value, max_fields=max_fields)
            flattened = [field['field_key'] for chunk in chunks for field in chunk['fields']]
            assert flattened == [f'f{index}' for index in range(field_count)]
            assert all(1 <= chunk['field_count'] <= max_fields for chunk in chunks)
            assert len(flattened) == len(set(flattened))


def test_merge_owner_envelopes_namespaces_conflicting_source_ids():
    value = batch()
    chunks = partition_owner_batch(value, max_fields=1)
    envelopes = []
    for index, chunk in enumerate(chunks, start=1):
        envelopes.append(
            {
                'batch_id': value['batch_id'],
                'producer': value['producer'],
                'policy_version': value['policy_version'],
                'template_version': value['template_version'],
                'source_inventory': [
                    {
                        'source_id': 'source',
                        'source_type': 'gis',
                        'title': f'chunk {index}',
                    }
                ],
                'patches': [
                    {
                        'field_key': chunk['fields'][0]['field_key'],
                        'value': None,
                        'status': 'not_found',
                        'source_refs': ['source'],
                    }
                ],
            }
        )
    merged, _ = merge_owner_envelopes(
        value,
        chunks,
        envelopes,
        run_id='run-1',
    )
    assert [source['source_id'] for source in merged['source_inventory']] == [
        'gis-dc__part_1__source',
        'gis-dc__part_2__source',
    ]
    assert [patch['source_refs'] for patch in merged['patches']] == [
        ['gis-dc__part_1__source'],
        ['gis-dc__part_2__source'],
    ]
    assert validate_owner_envelope(value, merged) == ()


def test_repair_negative_provenance_registers_actual_owner_execution():
    value = batch()
    raw = envelope()
    raw['source_inventory'] = []
    for patch in raw['patches']:
        patch['value'] = None
        patch['status'] = 'not_found'
        patch['source_refs'] = []
    repaired = repair_negative_provenance(
        value,
        raw,
        run_id='run-1',
        attempt=2,
    )
    assert validate_owner_envelope(value, repaired) == ()
    assert repaired['source_inventory'] == [
        {
            'source_id': 'derived-negative-gis-dc-part-1-attempt-2',
            'source_type': 'derived',
            'title': 'gis completed negative search for GIS-DC',
            'locator': ('run_id=run-1; batch_id=GIS-DC; owner_chunk=1/1; attempt=2'),
            'url': None,
        }
    ]
    assert all(patch['source_refs'] == ['derived-negative-gis-dc-part-1-attempt-2'] for patch in repaired['patches'])
    assert raw['source_inventory'] == []
    assert all(patch['source_refs'] == [] for patch in raw['patches'])


def test_repair_negative_provenance_does_not_mask_positive_or_unknown_refs():
    value = batch()
    raw = envelope()
    raw['source_inventory'] = []
    raw['patches'][0]['source_refs'] = []
    raw['patches'][1]['source_refs'] = ['unknown']
    repaired = repair_negative_provenance(
        value,
        raw,
        run_id='run-1',
        attempt=1,
    )
    violations = validate_owner_envelope(value, repaired)
    assert any('source_refs must be non-empty' in item for item in violations)
    assert any('unregistered source_refs' in item for item in violations)
    assert repaired['source_inventory'] == []


@pytest.mark.parametrize(
    'rendered',
    [
        json.dumps(envelope()),
        f'```json\n{json.dumps(envelope())}\n```',
        f'Result:\n{json.dumps(envelope())}',
    ],
)
def test_extract_json_object_accepts_one_unambiguous_object(rendered):
    assert extract_json_object(rendered)['batch_id'] == 'GIS-DC'


def test_extract_owner_envelope_selects_only_exact_partition_candidate():
    evidence = {'status': 'searched', 'query': 'object'}
    incomplete = {
        **envelope(),
        'patches': envelope()['patches'][:1],
    }
    rendered = '\n'.join(
        [
            json.dumps(evidence),
            json.dumps(incomplete),
            json.dumps(envelope()),
        ]
    )
    selected = extract_owner_envelope(rendered, batch())
    assert selected == envelope()


def test_extract_owner_envelope_rejects_two_distinct_exact_candidates():
    first = envelope()
    second = envelope()
    second['patches'][0]['value'] = 'different'
    rendered = f'{json.dumps(first)}\n{json.dumps(second)}'
    with pytest.raises(
        GeotizerOrchestrationError,
        match='matching_candidates=2',
    ):
        extract_owner_envelope(rendered, batch())


def test_extract_owner_envelope_recovers_exact_candidate_from_json_array():
    rendered = json.dumps([{'status': 'searched'}, envelope()])
    assert extract_owner_envelope(rendered, batch()) == envelope()


def test_backend_owned_envelope_injects_identity_into_patch_only_payload():
    payload = envelope()
    for key in (
        'batch_id',
        'producer',
        'policy_version',
        'template_version',
    ):
        payload.pop(key)

    recovered = recover_backend_owned_owner_envelope(
        json.dumps(payload),
        batch(),
        run_id='run-backend-envelope',
    )

    assert recovered is not None
    assert recovered['run_id'] == 'run-backend-envelope'
    assert recovered['batch_id'] == 'GIS-DC'
    assert recovered['producer'] == 'gis'
    assert recovered['policy_version'] == 'geotizer_assignments.v1'
    assert recovered['template_version'] == 'geotizer_object.v1'
    assert validate_owner_envelope(batch(), recovered) == ()


def test_backend_owned_envelope_overrides_untrusted_model_identity():
    payload = {
        **envelope(),
        'batch_id': 'WRONG',
        'producer': 'WRONG',
        'policy_version': 'WRONG',
        'template_version': 'WRONG',
    }

    recovered = recover_backend_owned_owner_envelope(
        json.dumps(payload),
        batch(),
        run_id='run-backend-envelope',
    )

    assert recovered is not None
    assert validate_owner_envelope(batch(), recovered) == ()


def test_owner_attempt_diagnostic_keeps_hash_and_shape_not_raw_text():
    raw = json.dumps({'patches': [], 'source_inventory': []})
    diagnostic = owner_attempt_diagnostic(raw, attempt=2)

    assert diagnostic['attempt'] == 2
    assert diagnostic['character_count'] == len(raw)
    assert len(diagnostic['sha256']) == 64
    assert diagnostic['candidate_keys'] == [['patches', 'source_inventory']]
    assert raw not in json.dumps(diagnostic)


def test_owner_envelope_requires_exact_field_partition():
    value = envelope()
    value['patches'][1]['field_key'] = 'foreign'
    violations = validate_owner_envelope(batch(), value)
    assert any('missing field_key' in item for item in violations)
    assert any('foreign field_key' in item for item in violations)


def test_owner_envelope_requires_registered_provenance_for_negative_result():
    value = envelope()
    value['patches'][1]['source_refs'] = ['missing']
    violations = validate_owner_envelope(batch(), value)
    assert any('unregistered source_refs' in item for item in violations)


def test_bounded_evidence_keeps_head_and_provenance_tail():
    value = 'A' * 100 + 'TAIL'
    result = bounded_text(value, max_chars=40)
    assert result.startswith('A' * 30)
    assert result.endswith('TAIL')
    assert 'omitted by orchestrator' in result


def test_gis_profile_keeps_deterministic_project_resolution_and_deduplicates():
    profile = normalize_gis_object_profile(
        json.dumps(
            {
                'project_resolution': {'status': 'not_found'},
                'location_terms': ['ЯНАО', '  янао  ', 'Полярный Урал'],
                'commodity_terms': ['золото'],
                'deposit_type_terms': ['золото-кварцевый'],
                'geology_terms': ['зеленокаменный пояс'],
                'evidence': [
                    {
                        'source_id': 'gis-1',
                        'layer_id': 'NiyaU_PLG',
                        'feature_or_query': 'feature=0',
                        'fact': 'ЯНАО',
                    }
                ],
            },
            ensure_ascii=False,
        ),
        object_name='Нияюская площадь',
        project_id='Нияюская_площадь',
    )

    rendered = profile.as_dict()
    assert rendered['project_resolution'] == {
        'status': 'resolved',
        'project_id': 'Нияюская_площадь',
        'object_name': 'Нияюская площадь',
        'authority': 'geotizer_start',
    }
    assert rendered['location_terms'] == ['ЯНАО', 'Полярный Урал']
    assert rendered['profile_status'] == 'ready'


def test_knowledge_search_plan_preserves_authority_order_and_direct_queries():
    profile = normalize_gis_object_profile(
        json.dumps(
            {
                'location_terms': ['ЯНАО'],
                'commodity_terms': ['золото'],
                'deposit_type_terms': ['золото-кварцевый'],
                'geology_terms': ['Полярный Урал'],
                'evidence': [{'source_id': 'gis-1'}],
            },
            ensure_ascii=False,
        ),
        object_name='Нияюская площадь',
        project_id='Нияюская_площадь',
    )
    plan = build_knowledge_search_plan(profile)

    assert [tier['relation_to_object'] for tier in plan['tiers']] == ['direct', 'regional_context', 'deposit_analogue']
    assert plan['tiers'][0]['enabled'] is True
    assert 'Нияюская площадь' in plan['tiers'][0]['query_terms']
    assert 'Нияюская_площадь' in plan['tiers'][0]['query_terms']
    assert plan['tiers'][1]['query_terms'] == ['ЯНАО', 'Полярный Урал']
    assert plan['tiers'][2]['query_terms'] == [
        'золото',
        'золото-кварцевый',
        'Полярный Урал',
    ]


def test_unavailable_gis_profile_keeps_direct_knowledge_search_enabled():
    profile = normalize_gis_object_profile(
        'not JSON',
        object_name='Нияюская площадь',
        project_id='Нияюская_площадь',
    )
    plan = build_knowledge_search_plan(profile)

    assert profile.profile_status == 'unavailable'
    assert plan['tiers'][0]['enabled'] is True
    assert plan['tiers'][1]['enabled'] is False
    assert plan['tiers'][2]['enabled'] is False


def test_gis_descriptors_without_exact_evidence_do_not_enable_indirect_search():
    profile = normalize_gis_object_profile(
        json.dumps(
            {
                'location_terms': ['ЯНАО'],
                'commodity_terms': ['золото'],
                'deposit_type_terms': ['золото-кварцевый'],
                'evidence': [],
            },
            ensure_ascii=False,
        ),
        object_name='Нияюская площадь',
        project_id='Нияюская_площадь',
    )
    plan = build_knowledge_search_plan(profile)

    assert profile.profile_status == 'partial'
    assert profile.location_terms == ()
    assert profile.commodity_terms == ()
    assert plan['tiers'][1]['enabled'] is False
    assert plan['tiers'][2]['enabled'] is False
    assert 'exact GIS evidence locator' in profile.diagnostics[0]


def test_gis_error_message_never_calls_resolved_project_missing():
    message = _gis_error_user_message(
        {
            'violations': [
                {
                    'context': {
                        'gis_project': {
                            'status': 'resolved',
                            'project_id': 'Нияюская_площадь',
                        },
                        'failure_stage': 'licence_scope_binding',
                    }
                }
            ]
        },
        fallback='generic failure',
    )

    assert 'Нияюская_площадь' in message
    assert 'найден' in message
    assert 'не найден' not in message
    assert 'licence_scope_binding' in message


def test_workflow_drives_start_contributors_owner_submit_finalize():
    calls = []
    current_batch = batch()

    async def gis_call(payload):
        calls.append(('gis', payload['action']))
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-1',
                'object_name': 'Object',
                'datacube': {'workflow_status': 'ready'},
                'next_batch': current_batch,
            }
        if payload['action'] == 'submit_batch':
            assert payload['run_id'] == 'run-1'
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-1',
                'object_name': 'Object',
                'datacube': {'workflow_status': 'ready'},
                'next_batch': None,
            }
        if payload['action'] == 'finalize':
            return {
                'workflow_status': 'finalized',
                'run_id': 'run-1',
                'object_name': 'Object',
                'counts': {'filled': 1, 'not_found': 1},
                'xlsx': {
                    'download_path': ('/geotizer/files/run-1/geotizer.xlsx'),
                    'sha256': 'abc',
                },
            }
        raise AssertionError(payload)

    async def agent_call(task, prompt, object_name, datacube):
        calls.append(('agent', task.role, task.producer))
        if task.role == 'owner':
            return json.dumps(envelope())
        return 'bounded evidence'

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Object',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )
    assert final['workflow_status'] == 'finalized'
    assert calls == [
        ('gis', 'start'),
        ('agent', 'contributor', 'kb'),
        ('agent', 'contributor', 'web'),
        ('agent', 'owner', 'gis'),
        ('gis', 'submit_batch'),
        ('gis', 'finalize'),
    ]


def test_workflow_derives_gis_profile_before_relation_aware_kb_owner():
    calls = []
    kb_batch = {
        **batch(),
        'batch_id': 'KB-GEO',
        'producer': 'kb',
        'evidence_routes': [],
    }

    async def gis_call(payload):
        calls.append(('gis', payload['action']))
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-profile',
                'project_id': 'Нияюская_площадь',
                'object_name': 'Нияюская площадь',
                'gis_project': {
                    'status': 'resolved',
                    'project_id': 'Нияюская_площадь',
                    'object_name': 'Нияюская площадь',
                },
                'datacube': {},
                'next_batch': kb_batch,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-profile',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-profile',
            'xlsx': {'download_path': ('/geotizer/files/run-profile/geotizer.xlsx')},
        }

    async def agent_call(task, prompt, object_name, datacube):
        calls.append(('agent', task.task_id))
        request = json.loads(prompt)
        if task.task_id == 'GIS-OBJECT-PROFILE':
            assert request['gis_project']['status'] == 'resolved'
            return json.dumps(
                {
                    'location_terms': ['ЯНАО'],
                    'commodity_terms': ['золото'],
                    'deposit_type_terms': ['золото-кварцевый'],
                    'geology_terms': ['Полярный Урал'],
                    'evidence': [{'source_id': 'gis-profile'}],
                },
                ensure_ascii=False,
            )

        search_plan = request['context']['knowledge_search_plan']
        assert [tier['relation_to_object'] for tier in search_plan['tiers']] == [
            'direct',
            'regional_context',
            'deposit_analogue',
        ]
        value = envelope()
        value['batch_id'] = 'KB-GEO'
        value['producer'] = 'kb'
        return json.dumps(value)

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Нияюская площадь',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )

    assert final['workflow_status'] == 'finalized'
    assert calls == [
        ('gis', 'start'),
        ('agent', 'GIS-OBJECT-PROFILE'),
        ('agent', 'KB-GEO'),
        ('gis', 'submit_batch'),
        ('gis', 'finalize'),
    ]


def test_workflow_chunks_large_owner_output_and_submits_one_atomic_batch():
    large = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': f'f{index}', 'row_id': index} for index in range(81)],
        'evidence_routes': [],
    }
    owner_calls = 0
    submitted = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-large',
                'object_name': 'Object',
                'datacube': {},
                'next_batch': large,
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-large',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-large',
            'xlsx': {
                'download_path': '/geotizer/files/run-large/geotizer.xlsx',
            },
        }

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal owner_calls
        owner_calls += 1
        request = json.loads(prompt)
        chunk = request['context']['batch']
        source_id = 'shared-source'
        return json.dumps(
            {
                'batch_id': large['batch_id'],
                'producer': large['producer'],
                'policy_version': large['policy_version'],
                'template_version': large['template_version'],
                'source_inventory': [
                    {
                        'source_id': source_id,
                        'source_type': 'knowledge_base',
                        'title': f'chunk {chunk["owner_chunk"]["index"]}',
                    }
                ],
                'patches': [
                    {
                        'field_key': field['field_key'],
                        'value': None,
                        'status': 'not_found',
                        'source_refs': [source_id],
                    }
                    for field in chunk['fields']
                ],
            }
        )

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Object',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )
    assert final['workflow_status'] == 'finalized'
    assert owner_calls == 5
    assert len(submitted) == 1
    assert len(submitted[0]['patches']) == 81
    assert len(submitted[0]['source_inventory']) == 5
    assert {source['source_id'] for source in submitted[0]['source_inventory']} == {
        'kb-resource-tech__part_1__shared-source',
        'kb-resource-tech__part_2__shared-source',
        'kb-resource-tech__part_3__shared-source',
        'kb-resource-tech__part_4__shared-source',
        'kb-resource-tech__part_5__shared-source',
    }
    assert {patch['source_refs'][0] for patch in submitted[0]['patches']} == {
        'kb-resource-tech__part_1__shared-source',
        'kb-resource-tech__part_2__shared-source',
        'kb-resource-tech__part_3__shared-source',
        'kb-resource-tech__part_4__shared-source',
        'kb-resource-tech__part_5__shared-source',
    }


def test_workflow_repairs_invalid_owner_output_before_submission():
    owner_attempts = 0
    gis_actions = []

    async def gis_call(payload):
        gis_actions.append(payload['action'])
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-1',
                'object_name': 'Object',
                'datacube': {},
                'next_batch': batch(),
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-1',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-1',
            'xlsx': {'download_path': '/geotizer/files/run-1/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal owner_attempts
        if task.role == 'contributor':
            return 'evidence'
        owner_attempts += 1
        if owner_attempts == 1:
            return '{"patches": []}'
        return json.dumps(envelope())

    asyncio.run(
        run_geotizer_workflow(
            object_name='Object',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )
    assert owner_attempts == 2
    assert gis_actions.count('submit_batch') == 1


def test_lekyn_regression_strict_owner_envelope_keeps_legacy_path():
    value = batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    calls = 0

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal calls
        calls += 1
        return json.dumps(envelope(), ensure_ascii=False)

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={
                'batch': value,
                'contributor_evidence': [],
                'accepted_field_summary': [],
            },
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-lekyn-regression',
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
            datacube=None,
        )
    )

    assert calls == 1
    assert result['patches'] == envelope()['patches']
    # Not byte-identical to what the owner sent, and that is the port of
    # `normalize_source_inventory` (register A-04). Every source is rebuilt to
    # the five keys `GeotizerSource` declares -- `source_id`, `source_type`,
    # `title`, `locator`, `url` -- so an entry that was already well formed
    # gains the two optional ones it omitted. That is the submission schema's
    # own shape, not an addition to it, and normalising the good case is what
    # makes the repaired case indistinguishable from it downstream.
    assert result['source_inventory'] == [
        {**source, 'locator': '', 'url': None} for source in envelope()['source_inventory']
    ]
    assert result['run_id'] == 'run-lekyn-regression'
    assert validate_owner_envelope(value, result) == ()


def test_owner_structured_proposals_survive_invalid_envelope():
    value = batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    raw = json.dumps(
        {
            'field_proposals': [
                {
                    'field_key': 'f1',
                    'value': 'object-specific recovered value',
                    'unit': None,
                    'value_origin': 'direct',
                    'value_kind': 'other',
                    'temporal_role': 'current_fact',
                    'entity_role': 'target_object',
                    'relation_to_object': 'direct',
                    'source_id': 'owner-proposal-1',
                    'source_title': 'Object source',
                    'source_locator': {'page': 4},
                    'retrieval_note': 'Exact object fact on page 4.',
                }
            ]
        }
    )

    async def agent_call(task, prompt, object_name, datacube):
        return raw

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={
                'batch': value,
                'contributor_evidence': [],
                'accepted_field_summary': [],
            },
            next_batch=value,
            object_name='Верхне-Колпинская площадь',
            run_id='run-owner-proposal',
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
            datacube=None,
        )
    )

    patches = {patch['field_key']: patch for patch in result['patches']}
    assert patches['f1']['status'] == 'filled'
    assert patches['f1']['value'] == 'object-specific recovered value'
    assert patches['f2']['status'] == 'requires_expert_review'
    assert validate_owner_envelope(value, result) == ()


def test_owner_failure_preserves_attempt_shape_diagnostics():
    value = batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')

    async def agent_call(task, prompt, object_name, datacube):
        return '{"patches": []}'

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={
                'batch': value,
                'contributor_evidence': [],
                'accepted_field_summary': [],
            },
            next_batch=value,
            object_name='Object',
            run_id='run-owner-diagnostics',
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
            datacube=None,
        )
    )

    diagnostics = result['patches'][0]['source_locator']['owner_attempt_diagnostics']
    # Two, not three. This owner returns the same `{"patches": []}` every time,
    # so the second attempt produces the violation set the first did and the
    # loop stops rather than spend a third on feedback that cannot lead
    # anywhere. The claim narrowed on 2026-09-02 with run `06fec58d`, which
    # spent three attempts of 21 816, 19 532 and 21 959 characters on one
    # identical objection and lost 25 cells; what this test is about — that
    # every attempt keeps its own diagnostics rather than being overwritten by
    # the last — is unchanged and is what the assertion below still pins.
    assert [item['attempt'] for item in diagnostics] == [1, 2]
    assert all(item['candidate_count'] == 1 for item in diagnostics)
    assert validate_owner_envelope(value, result) == ()


def test_workflow_fails_closed_after_invalid_owner_attempts():
    owner_attempts = 0
    submitted = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-fail-closed',
                'object_name': 'Object',
                'datacube': {},
                'next_batch': batch(),
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-fail-closed',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-fail-closed',
            'xlsx': {
                'download_path': ('/geotizer/files/run-fail-closed/geotizer.xlsx'),
            },
        }

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal owner_attempts
        if task.role == 'contributor':
            return 'bounded evidence'
        owner_attempts += 1
        return '{"patches": []}'

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Object',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
        )
    )
    assert final['workflow_status'] == 'finalized'
    # Two, not three: this owner repeats one invalid envelope, so the loop
    # recognises an unchanged violation set and stops. Failing closed is what
    # this test is named for and it still does — the assertions below are
    # untouched.
    assert owner_attempts == 2
    assert len(submitted) == 1
    assert {patch['status'] for patch in submitted[0]['patches']} == {'requires_expert_review'}
    assert submitted[0]['source_inventory'][0]['source_type'] == 'orchestration'
    assert validate_owner_envelope(batch(), submitted[0]) == ()


def test_owner_failure_envelope_is_deterministic_and_field_complete():
    first = owner_failure_envelope(
        batch(),
        run_id='run-1',
        attempts=3,
        feedback=['invalid patches'],
    )
    second = owner_failure_envelope(
        batch(),
        run_id='run-1',
        attempts=3,
        feedback=['invalid patches'],
    )
    assert first == second
    assert [patch['field_key'] for patch in first['patches']] == ['f1', 'f2']
    assert validate_owner_envelope(batch(), first) == ()


def test_invalid_owner_rejects_licence_derived_grr_schedule():
    value = {
        **batch(),
        'batch_id': 'KB-GRR-FACTORS',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r068.a05',
                'row_id': 68,
                'element': 'Бурение',
                'attribute_name': 'Сроки',
            }
        ],
        'field_count': 1,
    }
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    context = {
        'batch': value,
        'contributor_evidence': [
            {
                'route_id': 'GIS-GRR-SCHEDULE-DETERMINISTIC',
                'producer': 'gis_service',
                'source_domain': 'gis',
                'field_proposals': [
                    {
                        'field_key': 'geotizer_object.v1.r068.a05',
                        'value': 'РАСЧЁТНОЕ ЗНАЧЕНИЕ: 2025–2026 гг.',
                        'unit': 'период',
                        'value_origin': 'calculated',
                        'relation_to_object': 'direct',
                        'source_id': 'grr-schedule-1',
                        'source_title': 'GRR schedule',
                        'source_locator': {'operation': 'licence_term_phase_allocation'},
                        'retrieval_note': ('Calculated alternative schedule, not a direct approved calendar.'),
                        'temporal_role': 'proposed_plan',
                    }
                ],
            }
        ],
        'accepted_field_summary': [],
    }

    async def agent_call(task, prompt, object_name, datacube):
        return '{"patches": []}'

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context=context,
            next_batch=value,
            object_name='Object',
            run_id='run-grr-fail-closed',
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
            datacube=None,
        )
    )

    assert result['patches'][0]['status'] == 'requires_expert_review'
    assert result['patches'][0].get('value_origin') is None
    assert validate_owner_envelope(value, result) == ()


def test_invalid_assemble_owner_promotes_substantive_fallback_conclusion():
    value = {
        **batch(),
        'batch_id': 'ASSEMBLE',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r098.a01',
                'row_id': 98,
                'element': 'Заключение',
                'attribute_name': 'значение',
            }
        ],
        'field_count': 1,
    }
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    context = {
        'batch': value,
        'contributor_evidence': [],
        'accepted_field_summary': [
            {
                'field_key': 'geotizer_object.v1.r015.a01',
                'status': 'filled',
                'value': 'Подтверждённый геологический факт',
                'source_refs': ['kb-15'],
            }
        ],
    }

    async def agent_call(task, prompt, object_name, datacube):
        return '{"patches": []}'

    result = asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context=context,
            next_batch=value,
            object_name='Object',
            run_id='run-assemble-fail-closed',
            agent_call=agent_call,
            # Not injected here: this case is about the envelope, and a run
            # with no drain records no queries, which is the production
            # behaviour on any contour that has not wired one.
            query_drain=None,
            datacube=None,
        )
    )

    patch = result['patches'][0]
    assert patch['status'] == 'filled'
    assert patch['value_origin'] == 'calculated'
    assert patch['value'].startswith('РАСЧЁТНОЕ ЗНАЧЕНИЕ:')
    assert validate_owner_envelope(value, result) == ()


def test_filled_negative_marker_is_rejected():
    value = envelope()
    value['patches'][0].update(
        {
            'status': 'filled',
            'value': 'Не найдено',
            'value_origin': 'direct',
        }
    )

    assert any(
        'negative marker cannot use status=filled' in violation for violation in validate_owner_envelope(batch(), value)
    )


def test_standard_workflow_does_not_request_licence_derived_grr_schedule():
    called = False

    async def gis_call(payload):
        nonlocal called
        called = True
        raise AssertionError(payload)

    evidence = asyncio.run(
        _deterministic_grr_schedule_evidence(
            next_batch={'batch_id': 'KB-GRR-FACTORS'},
            run_id='run-grr',
            allowed_field_keys=['geotizer_object.v1.r068.a05'],
            gis_call=gis_call,
        )
    )

    assert evidence == []
    assert called is False


def test_source_report_proxy_paths_are_bounded_to_known_artifacts():
    final = {
        'source_report': {
            'markdown': {'download_path': '/geotizer/files/run-1/source_report.md'},
            'pdf': {'download_path': '/geotizer/files/run-1/source_report.pdf'},
            'state': {'download_path': '/geotizer/files/run-1/state.json'},
        }
    }

    assert _proxy_source_report_paths(final) == {
        'markdown': '/api/v1/geotizer/files/run-1/source_report.md',
        'pdf': '/api/v1/geotizer/files/run-1/source_report.pdf',
        'state': '/api/v1/geotizer/files/run-1/state.json',
    }


def test_assemble_conclusion_becomes_explicit_calculated_value():
    next_batch = {
        'batch_id': 'ASSEMBLE',
        'producer': 'skilled',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r098.a01',
                'row_id': 98,
                'element': 'Заключение',
                'attribute_name': 'значение',
            }
        ],
    }
    envelope = {
        'batch_id': 'ASSEMBLE',
        'producer': 'skilled',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {
                'source_id': 'synthesis-1',
                'source_type': 'orchestration',
                'title': 'Accepted facts synthesis',
            }
        ],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r098.a01',
                'status': 'requires_expert_review',
                'value': (
                    'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: объект имеет подтверждённые '
                    'геологические признаки, результаты изученности и '
                    'инфраструктурные предпосылки, однако ресурсная и '
                    'технологическая неопределённость должна быть закрыта '
                    'следующей стадией работ.'
                ),
                'unit': None,
                'value_origin': None,
                'source_refs': ['synthesis-1'],
                'source_locator': {'summary': True},
                'retrieval_note': 'Review draft.',
            }
        ],
    }
    accepted = [
        {
            'field_key': 'geotizer_object.v1.r015.a01',
            'status': 'filled',
            'value': 'Geology fact',
            'source_refs': ['kb-15'],
        }
    ]

    promoted = promote_assemble_conclusions(
        next_batch,
        envelope,
        accepted,
    )

    patch = promoted['patches'][0]
    assert patch['status'] == 'filled'
    assert patch['value_origin'] == 'calculated'
    assert patch['value'].startswith('РАСЧЁТНОЕ ЗНАЧЕНИЕ:')
    assert patch['source_locator']['accepted_field_keys'] == ['geotizer_object.v1.r015.a01']
    assert validate_owner_envelope(next_batch, promoted) == ()


def test_the_failure_envelope_records_every_attempts_violations():
    """Run `5880a164`, `KB-GRR-FACTORS`: the owner returned 9,372 characters,
    then 11,687 carrying a real `patches`/`source_inventory` envelope, then
    nothing. The card reported `Agent returned an empty response` -- true of the
    third attempt and useless as a diagnosis, because the violation that
    rejected the well-formed envelope had been overwritten.

    So the histogram of what the contract actually refuses could not be built
    from a run's own state, which is what a round of work was spent discovering.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import owner_failure_envelope

    fallback = owner_failure_envelope(
        batch(),
        run_id='run-1',
        attempts=3,
        feedback=['Agent returned an empty response'],
        feedback_by_attempt=[
            {'attempt': 1, 'violations': []},
            {'attempt': 2, 'violations': ['patches[3].status is unsupported']},
            {'attempt': 3, 'violations': ['Agent returned an empty response']},
        ],
    )

    locator = fallback['patches'][0]['source_locator']
    assert [entry['attempt'] for entry in locator['owner_attempt_feedback']] == [1, 2, 3]
    assert locator['owner_attempt_feedback'][1]['violations'] == [
        'patches[3].status is unsupported'
    ]
    # The note still shows the last attempt's feedback: that is what the reader
    # sees first and what the model was last told.
    assert 'Agent returned an empty response' in fallback['patches'][0]['retrieval_note']


def test_an_envelope_that_never_failed_records_no_attempt_feedback():
    """The default stays empty rather than absent, so a reader can tell "no
    attempts were rejected" from "this run predates the record"."""
    from open_webui.services.artifacts.geotizer.owner_envelope import owner_failure_envelope

    fallback = owner_failure_envelope(batch(), run_id='run-1', attempts=3, feedback=[])

    assert fallback['patches'][0]['source_locator']['owner_attempt_feedback'] == []


def test_the_gis_execution_trace_reaches_the_batch_evidence():
    """`Расширение использования GIS` §5.2. The protocol is produced by
    `gis_service` and has to survive into the run; §3.3.2 is what it is for --
    a value in the card could not be traced to the layer, feature, CRS and
    operation that produced it, and an absent value could not be explained."""
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    trace = [
        {
            'trace_id': 'abc123',
            'semantic_role': 'road',
            'status': 'success',
            'raw_measurement': 9471.123456,
            'calculation_crs': 'EPSG:32642',
        },
        {
            'trace_id': 'def456',
            'semantic_role': 'port',
            'status': 'not_found',
            'rejection_reason': 'layer_not_found',
        },
    ]

    async def gis_call(payload):
        assert payload['action'] == 'infrastructure_proposals'
        return {
            'workflow_status': 'ready',
            'field_proposals': [],
            'warnings': [],
            'unanswerable_field_keys': [],
            'gis_execution_trace': trace,
        }

    infrastructure_batch = {
        **batch(),
        'batch_id': 'GIS-DC',
        'fields': [{'field_key': 'geotizer_object.v1.r084.a01', 'row_id': 84}],
    }
    evidence = asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch=infrastructure_batch,
            run_id='run-1',
            allowed_field_keys=['geotizer_object.v1.r084.a01'],
            gis_call=gis_call,
        )
    )

    assert evidence, 'the infrastructure batch must produce deterministic evidence'
    carried = evidence[0]['gis_execution_trace']
    assert [item['semantic_role'] for item in carried] == ['road', 'port']
    # The role that computed nothing is the one a reader most needs explained.
    assert carried[1]['rejection_reason'] == 'layer_not_found'
    assert carried[0]['raw_measurement'] == 9471.123456


def test_the_note_language_is_stated_and_the_values_are_exempt():
    """The card explains itself in two languages, and the split is drifting.

    Measured across three runs: 19% of `05169ef1`'s 351 notes are English,
    42% of `6af7479f`'s, 46% of `8a02f724`'s. Every one lands in the XLSX
    comment column and in the DOCX a Russian-speaking Competent Person reads,
    beside the deterministic notes this pipeline writes in Russian.

    Nothing in the contract had ever said which language a note is in, so the
    model picked per batch. The exemption matters as much as the rule: a
    licence number, a mineral name and a company name are evidence, not prose,
    and translating them would corrupt the value to tidy the note.
    """
    from open_webui.services.artifacts.geotizer.prompts import _owner_prompt

    prompt = _owner_prompt(
        context={'batch': batch()},
        attempt=1,
        feedback=None,
        previous_output='',
    )

    assert 'Write retrieval_note in Russian' in prompt
    assert 'Do not translate values' in prompt


def test_the_gis_calculation_runs_once_per_run_not_once_per_chunk():
    """`GIS-DC` is chunked, and every chunk holding an infrastructure row asks
    for the whole twelve-role calculation. Nothing in that calculation depends
    on the chunk -- it measures the licence polygon against the linked project.

    Run `08330f72` ran it twice: `run_log.json` holds 24 trace entries for 12
    roles, pairwise identical `trace_id`s and two different `duration_ms`,
    which is the same geodatabase read done twice and recorded twice.
    """
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    calls: list[Mapping[str, Any]] = []

    async def gis_call(payload):
        calls.append(payload)
        return {
            'workflow_status': 'ready',
            'field_proposals': [],
            'warnings': [],
            'unanswerable_field_keys': [],
            'gis_execution_trace': [{'trace_id': 'abc123', 'semantic_role': 'road'}],
        }

    def chunk(field_key, row_id):
        return {**batch(), 'batch_id': 'GIS-DC', 'fields': [{'field_key': field_key, 'row_id': row_id}]}

    cache: dict[str, Any] = {}

    async def both_chunks():
        first = await _deterministic_infrastructure_evidence(
            next_batch=chunk('geotizer_object.v1.r084.a01', 84),
            run_id='run-1',
            allowed_field_keys=['geotizer_object.v1.r084.a01'],
            gis_call=gis_call,
            cache=cache,
        )
        second = await _deterministic_infrastructure_evidence(
            next_batch=chunk('geotizer_object.v1.r088.a02', 88),
            run_id='run-1',
            allowed_field_keys=['geotizer_object.v1.r088.a02'],
            gis_call=gis_call,
            cache=cache,
        )
        return first, second

    first, second = asyncio.run(both_chunks())

    assert len(calls) == 1, 'the second chunk must reuse the first chunk’s calculation'
    assert first and second, 'both chunks still receive the evidence'
    assert second[0]['gis_execution_trace'] == first[0]['gis_execution_trace']


def test_the_layer_manifest_reaches_the_cache_and_not_the_owner():
    """The inventory is a fact about the run, and the largest block in the
    payload. It belongs in `run_log.json`, which reads it out of this cache,
    and not in the JSON blob a chunk hands the owner -- which is already the
    prompt that has returned zero characters on four runs.
    """
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    manifest = {
        'project_id': 'lekyn_new_data',
        'layer_count': 2,
        'layers': [{'layer_id': 'road', 'semantic_roles': ['road']}],
        'roles': {'road': {'layer_ids': ['road']}},
    }

    async def gis_call(payload):
        return {
            'workflow_status': 'ready',
            'field_proposals': [],
            'warnings': [],
            'unanswerable_field_keys': [],
            'gis_execution_trace': [],
            'layer_manifest': manifest,
        }

    cache: dict[str, Any] = {}
    evidence = asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch={
                **batch(),
                'batch_id': 'GIS-DC',
                'fields': [{'field_key': 'geotizer_object.v1.r084.a01', 'row_id': 84}],
            },
            run_id='run-1',
            allowed_field_keys=['geotizer_object.v1.r084.a01'],
            gis_call=gis_call,
            cache=cache,
        )
    )

    assert cache['run-1']['layer_manifest'] == manifest
    assert 'layer_manifest' not in evidence[0]['output']
    assert 'lekyn_new_data' not in evidence[0]['output']


def test_a_second_run_does_not_reuse_the_first_run_s_calculation():
    """The cache is keyed on the run, because a different run means a
    different linked project state."""
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    calls: list[Mapping[str, Any]] = []

    async def gis_call(payload):
        calls.append(payload)
        return {
            'workflow_status': 'ready',
            'field_proposals': [],
            'warnings': [],
            'unanswerable_field_keys': [],
            'gis_execution_trace': [],
        }

    infrastructure_batch = {
        **batch(),
        'batch_id': 'GIS-DC',
        'fields': [{'field_key': 'geotizer_object.v1.r084.a01', 'row_id': 84}],
    }
    cache: dict[str, Any] = {}

    async def two_runs():
        for run_id in ('run-1', 'run-2'):
            await _deterministic_infrastructure_evidence(
                next_batch=infrastructure_batch,
                run_id=run_id,
                allowed_field_keys=['geotizer_object.v1.r084.a01'],
                gis_call=gis_call,
                cache=cache,
            )

    asyncio.run(two_runs())

    assert [payload['run_id'] for payload in calls] == ['run-1', 'run-2']


def test_a_divergence_record_survives_the_source_rename():
    """Run `84afa9e2` carried fourteen `spatial_divergence` source_refs and not
    one of them resolved against `state.sources`. `merge_owner_envelopes`
    namespaces every `source_id` with a batch and chunk prefix and rewrites the
    refs the locator holds -- but `spatial_divergence` keeps its two sides one
    level down, in `measured` and `read`, and the rename walked neither.

    This is the defect `candidates` had on `6af7479f`, on all 50 sides of 25
    conflicts, reappearing in a key that did not exist when that was fixed. The
    record exists precisely so a reader can find the measurement that lost, and
    a ref pointing at nothing is the one way to make it unfindable.
    """
    value = batch()
    chunks = partition_owner_batch(value, max_fields=1)
    envelopes = [
        {
            'batch_id': value['batch_id'],
            'producer': value['producer'],
            'policy_version': value['policy_version'],
            'template_version': value['template_version'],
            'source_inventory': [
                {'source_id': 'gis-measured', 'source_type': 'gis', 'title': 'road'},
                {'source_id': 'doc-read', 'source_type': 'knowledge_base', 'title': 'Проект ГРР'},
            ],
            'patches': [
                {
                    'field_key': chunk['fields'][0]['field_key'],
                    'value': 'п. Полярный',
                    'status': 'filled',
                    'value_origin': 'direct',
                    'source_refs': ['doc-read', 'gis-measured'],
                    'source_locator': {
                        'spatial_divergence': {
                            'kind': 'computed_against_read',
                            'measured': [{'value': 0.0, 'source_ref': 'gis-measured'}],
                            'read': [{'value': 'п. Полярный', 'source_ref': 'doc-read'}],
                        }
                    },
                }
            ],
        }
        for chunk in chunks
    ]

    merged, _ = merge_owner_envelopes(value, chunks, envelopes, run_id='run-1')
    known = {str(source['source_id']) for source in merged['source_inventory']}

    for patch in merged['patches']:
        divergence = patch['source_locator']['spatial_divergence']
        for side in ('measured', 'read'):
            for entry in divergence[side]:
                assert entry['source_ref'] in known, (
                    f"{side} ref {entry['source_ref']!r} resolves to nothing"
                )
    assert merged['patches'][0]['source_locator']['spatial_divergence']['measured'][0][
        'source_ref'
    ] == 'gis-dc__part_1__gis-measured'


def test_the_rename_reaches_a_locator_nested_inside_a_candidate():
    """The fifth place refs live, found by the state-level invariant on its
    first run: `candidates[0].locator.candidates[0].source_ref` and
    `owner_locator.candidates[…]` on r096 of run `84afa9e2`.

    Four rounds each taught this rename one more key. It walks the whole
    locator now, so the sixth place costs nothing.
    """
    value = batch()
    chunks = partition_owner_batch(value, max_fields=1)
    envelopes = [
        {
            'batch_id': value['batch_id'],
            'producer': value['producer'],
            'policy_version': value['policy_version'],
            'template_version': value['template_version'],
            'source_inventory': [
                {'source_id': 'inner-src', 'source_type': 'web', 'title': 'заметка'},
            ],
            'patches': [
                {
                    'field_key': chunk['fields'][0]['field_key'],
                    'value': 'x',
                    'status': 'filled',
                    'value_origin': 'direct',
                    'source_refs': ['inner-src'],
                    'source_locator': {
                        'owner_locator': {'candidates': [{'source_ref': 'inner-src'}]},
                        'candidates': [
                            {
                                'source_ref': 'inner-src',
                                'locator': {'candidates': [{'source_ref': 'inner-src'}]},
                            }
                        ],
                        'a_key_nobody_has_invented_yet': {
                            'deeply': [{'nested': {'source_ref': 'inner-src'}}]
                        },
                    },
                }
            ],
        }
        for chunk in chunks
    ]

    merged, _ = merge_owner_envelopes(value, chunks, envelopes, run_id='run-1')
    known = {str(source['source_id']) for source in merged['source_inventory']}
    locator = merged['patches'][0]['source_locator']

    assert locator['candidates'][0]['locator']['candidates'][0]['source_ref'] in known
    assert locator['owner_locator']['candidates'][0]['source_ref'] in known
    assert (
        locator['a_key_nobody_has_invented_yet']['deeply'][0]['nested']['source_ref'] in known
    )
    assert locator['candidates'][0]['source_ref'] == 'gis-dc__part_1__inner-src'


TRENCH_KEYS = (
    'geotizer_object.v1.r037.a01',
    'geotizer_object.v1.r037.a03',
)
STUDY_FIELDS = [
    f'geotizer_object.v1.r{row:03d}.a{index:02d}'
    for row in range(28, 44)
    for index in range(1, 7)
]


def _study_payload():
    """One calculation, both halves: an infrastructure row and a study row.

    `calculate_infrastructure_field_proposals` measures eighteen roles in one
    pass and returns them together, which is why the batch that reads it
    matters.
    """

    def proposal(field_key, value, unit, aggregate):
        return {
            'field_key': field_key,
            'value': value,
            'unit': unit,
            'value_origin': 'calculated',
            'relation_to_object': 'direct',
            'source_id': f'gis-study-{aggregate}',
            'source_title': 'GIS study aggregate: Канавы_ГСК',
            'source_locator': {
                'operation': aggregate,
                'semantic_role': 'trench',
                'source_layer_id': 'Канавы_ГСК',
            },
            'retrieval_note': 'Calculated over 34 features of Канавы_ГСК.',
        }

    return {
        'workflow_status': 'ready',
        'field_proposals': [
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'value': 16.132,
                'unit': 'км',
                'value_origin': 'calculated',
                'relation_to_object': 'direct',
                'source_id': 'gis-infrastructure',
                'source_title': 'Nearest settlement',
                'source_locator': {'project_id': 'project'},
                'retrieval_note': 'Calculated from full GIS geometries.',
            },
            proposal(TRENCH_KEYS[0], 34, None, 'feature_count'),
            proposal(TRENCH_KEYS[1], 187.0, 'м', 'mean_geometry_length_m'),
        ],
        'unanswerable_field_keys': [
            {
                'field_key': 'geotizer_object.v1.r038.a01',
                'code': 'layer_lacks_required_attribute',
            }
        ],
        'gis_execution_trace': [
            {
                'semantic_role': 'trench',
                'status': 'success',
                'accepted': True,
                'proposal_field_keys': list(TRENCH_KEYS),
            }
        ],
    }


def _evidence_for(batch_id, allowed):
    async def gis_call(payload):
        return _study_payload()

    return asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch={
                **batch(),
                'batch_id': batch_id,
                'fields': [{'field_key': key} for key in allowed],
            },
            run_id='af707b17',
            allowed_field_keys=allowed,
            gis_call=gis_call,
        )
    )


def test_the_study_rows_reach_the_batch_that_owns_them():
    """`af707b17`: `trench` succeeded, proposed r037.a01 and r037.a03, and both
    cells finalized `not_found`.

    The calculation ran and its study half was delivered to nobody. `GIS-DC`
    owns rows 77-88 and the payload is filtered to the asking batch's field
    keys, so rows 37-42 matched no batch that ever asked for them.
    """
    evidence = _evidence_for('KB-STUDY', STUDY_FIELDS)

    assert [item['field_key'] for item in evidence[0]['field_proposals']] == list(
        TRENCH_KEYS
    )


def test_the_drillhole_refusal_reaches_the_same_batch():
    """The explanation went the same way as the value.

    `Скважины_ГСК` resolves and carries `Id, Имя, Участ, POINT_X, POINT_Y`, so
    r038 is `layer_lacks_required_attribute` -- and that entry was filtered
    out by the same allowlist, leaving the row empty with no reason at all.
    """
    evidence = _evidence_for('KB-STUDY', STUDY_FIELDS)

    assert [item['field_key'] for item in evidence[0]['unanswerable_field_keys']] == [
        'geotizer_object.v1.r038.a01'
    ]


def test_each_batch_defers_the_half_it_does_not_own():
    """One calculation, two owners. A key outside the batch is not lost."""
    study = _evidence_for('KB-STUDY', STUDY_FIELDS)
    infrastructure = _evidence_for('GIS-DC', ['geotizer_object.v1.r078.a01'])

    assert study[0]['deferred_field_keys'] == ['geotizer_object.v1.r078.a01']
    assert infrastructure[0]['deferred_field_keys'] == list(TRENCH_KEYS)
    assert [item['field_key'] for item in infrastructure[0]['field_proposals']] == [
        'geotizer_object.v1.r078.a01'
    ]


def test_the_delivery_predicate_is_not_the_suppression_predicate():
    """`KB-STUDY` reads the calculation and keeps its own GIS contributor.

    `_needs_deterministic_infrastructure` also drives
    `_contributors_for_batch`, where it removes the GIS agent on the grounds
    that the deterministic call has already answered the batch. That is true
    for `GIS-DC` and false here, so the two questions are two predicates.
    """
    study_batch = {
        **batch(),
        'batch_id': 'KB-STUDY',
        'fields': [{'field_key': TRENCH_KEYS[0]}],
    }

    assert _receives_deterministic_gis(study_batch)
    assert not _needs_deterministic_infrastructure(study_batch)


def test_a_batch_that_owns_none_of_the_rows_reads_nothing():
    assert not _receives_deterministic_gis(
        {**batch(), 'batch_id': 'KB-GEO', 'fields': [{'field_key': TRENCH_KEYS[0]}]}
    )
    assert not _receives_deterministic_gis(
        {
            **batch(),
            'batch_id': 'KB-STUDY',
            'fields': [{'field_key': 'geotizer_object.v1.r028.a01'}],
        }
    )
