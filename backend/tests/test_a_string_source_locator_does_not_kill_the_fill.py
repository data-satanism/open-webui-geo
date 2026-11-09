"""A `source_locator` is either a mapping or a `key=value; ...` string, and readers and
writers keep the string form's keys."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import asyncio
import json

import pytest

from open_webui.services.core.text import locator_map
from open_webui.services.artifacts.geotizer.owner_envelope import (
    classify_rule_excluded_patches,
    inject_row_declared_work_stage,
)
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow
from open_webui.services.project_evidence.retrieval import evidence_locator_identity

from test_geotizer_orchestration import batch, envelope

LAYER_READ = (
    'project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0; '
    'geometry=full; coordinates=EPSG:4326; area=EPSG:6933'
)


def test_the_string_form_keeps_its_keys():
    """`locator_map` parses the string form into its keys."""
    parsed = locator_map(LAYER_READ)

    assert parsed['project_id'] == 'lekyn_new_data'
    assert parsed['layer_id'] == 'СЛХ_025834_ТП'
    assert parsed['feature_index'] == '0'
    assert parsed['coordinates'] == 'EPSG:4326'


def test_a_mapping_passes_through_unchanged():
    assert locator_map({'page': 12, 'document_id': 'd'}) == {'page': 12, 'document_id': 'd'}


@pytest.mark.parametrize('value', [None, 7, [], 'no equals signs here', ''])
def test_anything_else_is_an_empty_mapping(value):
    """`locator_map` returns an empty mapping for anything that is neither a mapping nor
    a parseable string."""
    assert locator_map(value) == {}


def test_a_half_formed_string_keeps_the_parts_that_parse():
    """`locator_map` keeps the segments of a string that parse and drops the rest."""
    assert locator_map('project_id=p; garbage; layer_id=L') == {
        'project_id': 'p',
        'layer_id': 'L',
    }


def test_the_reader_that_killed_batch_two_survives_a_string():
    """`evidence_locator_identity` accepts a string or None locator."""
    assert evidence_locator_identity(LAYER_READ) == ('', '', '', '', '')
    assert evidence_locator_identity(None) == ('', '', '', '', '')


def _grr_batch():
    return {
        'batch_id': 'KB-GRR-FACTORS',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v3',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': 'geotizer_object.v1.r068.a01',
                'row_id': 68,
                'attribute_name': 'вид',
            }
        ],
        'evidence_routes': [],
    }


def test_the_work_stage_injection_keeps_the_layer_read():
    """`inject_row_declared_work_stage` adds `work_stage` to a string locator's parsed
    keys."""
    value = _grr_batch()
    env = {
        'source_inventory': [{'source_id': 's1', 'source_type': 'gis', 'title': 'GIS'}],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r068.a01',
                'value': 'маршруты',
                'unit': None,
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['s1'],
                'source_locator': LAYER_READ,
                'retrieval_note': 'layer read',
            }
        ],
    }

    repaired, notes = inject_row_declared_work_stage(value, env)
    locator = repaired['patches'][0]['source_locator']

    assert locator['work_stage'] == 'routes'
    assert locator['layer_id'] == 'СЛХ_025834_ТП'
    assert notes


def test_the_rule_exclusion_keeps_the_layer_read():
    value = _grr_batch()
    env = {
        'source_inventory': [{'source_id': 's1', 'source_type': 'gis', 'title': 'GIS'}],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r068.a01',
                'value': None,
                'unit': None,
                'status': 'not_found',
                'value_origin': None,
                'source_refs': ['s1'],
                'source_locator': LAYER_READ,
                'retrieval_note': (
                    "Исторические работы; отклонено rule "
                    "'historical_actual_is_not_plan'"
                ),
            }
        ],
    }

    repaired, notes = classify_rule_excluded_patches(value, env)
    locator = repaired['patches'][0]['source_locator']

    assert notes, 'the rule did not fire; the assertion below proves nothing'
    assert locator['if_not_why_not']['rule'] == 'historical_actual_is_not_plan'
    assert locator['layer_id'] == 'СЛХ_025834_ТП'


def test_a_fill_completes_with_a_string_locator_in_batch_two():
    """A fill with string locators in its second batch reaches `finalized` and keeps the
    layer read."""
    served = {'n': 0}
    submitted: list[dict] = []

    def _batch(index):
        value = batch()
        value['batch_id'] = 'GIS-DC' if index == 1 else 'KB-LIC-LEGAL'
        return value

    async def gis_call(payload):
        if payload['action'] == 'start':
            served['n'] = 1
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-layer-read',
                'object_name': 'Лекын',
                'datacube': {},
                'batches_total': 2,
                'next_batch': _batch(1),
                'fields': [
                    {
                        'field_key': 'geotizer_object.v1.r002.a01',
                        'row_id': 2,
                        'status': 'filled',
                        'value': 'ЯНАО',
                        'value_origin': 'direct',
                        'source_refs': ['gis-licence-scope-abc'],
                        'source_locator': LAYER_READ,
                        'group': 'Лицензия',
                        'attribute_name': 'название',
                    }
                ],
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            served['n'] += 1
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-layer-read',
                'next_batch': _batch(2) if served['n'] <= 2 else None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-layer-read',
            'counts': {'filled': 1},
            'xlsx': {'download_path': '/geotizer/files/run-layer-read/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        raw = envelope()
        raw['patches'][0]['source_locator'] = LAYER_READ
        return json.dumps(raw, ensure_ascii=False)

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
        )
    )

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 2, 'the run did not reach batch 2'
    locators = [
        patch['source_locator']
        for payload in submitted
        for patch in payload.get('patches') or []
    ]
    assert any(
        isinstance(item, str) or 'layer_id' in locator_map(item) for item in locators
    )


def test_a_semantic_rule_reads_a_qualifier_out_of_a_string_locator():
    """`validate_owner_envelope` reads the `work_stage` qualifier out of a string
    locator."""
    from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope

    value = _grr_batch()

    def _env(stage):
        return {
            'source_inventory': [
                {'source_id': 's1', 'source_type': 'gis', 'title': 'GIS'}
            ],
            'patches': [
                {
                    'field_key': 'geotizer_object.v1.r068.a01',
                    'value': 'маршруты',
                    'unit': None,
                    'status': 'filled',
                    'value_origin': 'direct',
                    'source_refs': ['s1'],
                    'source_locator': f'{LAYER_READ}; work_stage={stage}',
                    'retrieval_note': 'layer read',
                }
            ],
        }

    right = [v for v in validate_owner_envelope(value, _env('routes'))
             if 'work_stage is incompatible' in v]
    wrong = [v for v in validate_owner_envelope(value, _env('drilling'))
             if 'work_stage is incompatible' in v]

    assert right == []
    assert wrong, 'the rule did not see the qualifier in the string locator'


def test_a_string_locator_is_normalised_before_the_state_is_saved():
    """`normalize_patch_source_locators` turns string locators into mappings and reports
    how many it converted."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        normalize_patch_source_locators,
    )

    env = {
        'patches': [
            {'field_key': 'geotizer_object.v1.r002.a01', 'source_locator': LAYER_READ},
            {'field_key': 'geotizer_object.v1.r003.a01', 'source_locator': {'page': 1}},
            {'field_key': 'geotizer_object.v1.r004.a01', 'source_locator': None},
        ]
    }

    repaired, notes = normalize_patch_source_locators(env)
    shapes = [patch['source_locator'] for patch in repaired['patches']]

    assert shapes[0]['layer_id'] == 'СЛХ_025834_ТП'
    assert shapes[1] == {'page': 1}
    assert shapes[2] is None
    assert '1 ячеек' in render_run_notes(notes)[0]


def test_nothing_to_normalise_says_nothing():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        normalize_patch_source_locators,
    )

    env = {'patches': [{'field_key': 'f', 'source_locator': {'page': 1}}]}

    assert normalize_patch_source_locators(env)[1] == []


def test_the_workflow_normalises_before_it_repairs():
    """`workflow.py` calls `normalize_patch_source_locators` before
    `inject_row_declared_work_stage`."""
    from pathlib import Path

    import open_webui.services.artifacts.geotizer.workflow as module

    source = Path(module.__file__).read_text(encoding='utf-8')

    assert source.index('normalize_patch_source_locators(envelope)') < source.index(
        'inject_row_declared_work_stage(next_batch, envelope)'
    )
