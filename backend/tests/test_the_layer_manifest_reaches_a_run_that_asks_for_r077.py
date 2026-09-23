"""Tests that a run whose `GIS-DC` batch asks only for an infrastructure row outside the old prefix list still reaches
the GIS calculation and carries `gis_layer_manifest` on the run log.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from open_webui.services.artifacts.geotizer.prompts import INFRASTRUCTURE_ROW_PREFIXES
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

from test_geotizer_orchestration import batch, envelope

LAYER_COUNT = 1139

R077 = 'geotizer_object.v1.r077.a01'


def _manifest() -> dict[str, Any]:
    return {
        'schema_version': 'gis_execution_trace.v1',
        'project_id': 'Лекын-Талбейская площадь',
        'layer_count': LAYER_COUNT,
        'layers': [
            {'layer_id': f'L{i:04d}', 'display_name': f'Слой {i}',
             'feature_count': i, 'semantic_roles': []}
            for i in range(LAYER_COUNT)
        ],
        'roles': {},
    }


def _run(field_keys) -> dict[str, Any]:
    """A whole fill whose GIS-DC batch carries exactly `field_keys`."""
    value = batch()
    value['fields'] = [{'field_key': key, 'row_id': 77} for key in field_keys]
    sent: dict[str, Any] = {}
    gis_actions: list[str] = []

    async def gis_call(payload):
        gis_actions.append(payload['action'])
        if payload['action'] == 'start':
            return {'workflow_status': 'collecting', 'run_id': 'run-r077',
                    'object_name': 'Лекын', 'datacube': {}, 'next_batch': value,
                    'fields': []}
        if payload['action'] == 'infrastructure_proposals':
            return {'workflow_status': 'ready', 'project_id': 'Лекын-Талбейская площадь',
                    'field_proposals': [], 'warnings': [],
                    'unanswerable_field_keys': [], 'gis_execution_trace': [],
                    'measurements': [], 'layer_manifest': _manifest()}
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'run-r077',
                    'next_batch': None, 'fields': []}
        sent.update(payload)
        return {'workflow_status': 'finalized', 'run_id': 'run-r077', 'fields': [],
                'xlsx': {'download_path': '/geotizer/files/run-r077/geotizer.xlsx'}}

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        payload = envelope()
        payload['patches'] = [
            {'field_key': key, 'value': 'v', 'status': 'filled',
             'source_refs': ['s1'], 'source_locator': {'layer': 'licence'}}
            for key in field_keys
        ]
        return json.dumps(payload, ensure_ascii=False)

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын', project_id=None, model_run_id=None, run_id=None,
            allow_draft=True, gis_call=gis_call, agent_call=agent_call,
        )
    )
    return {'finalize': sent, 'gis_actions': gis_actions}


def test_the_manifest_reaches_the_run_log_of_an_r077_only_run():
    """An r077-only run carries a non-empty `gis_layer_manifest` on the run log."""
    run_log = _run([R077])['finalize'].get('run_log') or {}

    assert 'gis_layer_manifest' in run_log, (
        'the key must be on the run log, which is what run_log.json is written from'
    )
    assert run_log['gis_layer_manifest'], (
        'present and empty is «no gis_layer_manifest for this run» -- '
        'the failure this file exists against'
    )


def test_the_layer_count_matches_what_the_project_reports():
    run_log = _run([R077])['finalize']['run_log']
    assert run_log['gis_layer_manifest']['layer_count'] == LAYER_COUNT
    assert len(run_log['gis_layer_manifest']['layers']) == LAYER_COUNT


def test_the_calculation_is_actually_reached_for_r077():
    """An r077-only run calls `infrastructure_proposals`."""
    assert 'infrastructure_proposals' in _run([R077])['gis_actions']


def test_every_row_the_calculation_answers_reaches_the_manifest():
    """A run asking for any single row 77-88 carries `gis_layer_manifest`."""
    for row in range(77, 89):
        key = f'geotizer_object.v1.r{row:03d}.a01'
        run_log = _run([key])['finalize'].get('run_log') or {}
        assert run_log.get('gis_layer_manifest'), f'row {row} lost the manifest'


def test_the_prefix_set_covers_the_block_it_claims_to_own():
    """`INFRASTRUCTURE_ROW_PREFIXES` covers exactly rows 77-88."""
    rows = sorted(prefix.split('.')[2] for prefix in INFRASTRUCTURE_ROW_PREFIXES)
    assert rows == [f'r{row:03d}' for row in range(77, 89)]
    assert len(INFRASTRUCTURE_ROW_PREFIXES) == 12
