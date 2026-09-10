"""«no gis_layer_manifest for this run» about a project holding 1 139 layers.

A licence-first fill stopped on two violations, and the second caused the
first: no manifest reached the run, so no role could bind, so `trench` was
«unresolved» as a consequence rather than as a finding.

The manifest was never missing. `calculate_infrastructure_field_proposals`
reads it and returns `layer_manifest` unconditionally. What went wrong is one
step earlier: `_receives_deterministic_gis` decides whether a `GIS-DC` chunk
may read the calculation at all, and it matched five hand-picked row prefixes
-- r078, r081, r084, r085, r088 -- against a calculation that answers all
twelve of rows 77-88. A chunk carrying only r077 was told it does not receive
the deterministic output, so GIS was never called, so `infrastructure_cache`
stayed empty, so `gis_layer_manifest` -- harvested out of that cache -- was
`None`.

A run-level fact was riding on a per-chunk row allowlist.

The assertions are on the `run_log` handed to `finalize`, which is what
`gis_service` writes to `run_log.json`. Never on whether
`semantic_layer_manifest` was called: that distinction is why
`retrieval_queries`, `run_variance`, `citations_by_name` and six others each
cost a round.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from open_webui.services.artifacts.geotizer.prompts import INFRASTRUCTURE_ROW_PREFIXES
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

from test_geotizer_orchestration import batch, envelope

#: What `list_layers` reports for «Лекын-Талбейская площадь».
LAYER_COUNT = 1139

#: The row the failing fill asked for, and the one the old gate omitted.
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


# --------------------------------------------------------- the artefact


def test_the_manifest_reaches_the_run_log_of_an_r077_only_run():
    """The exact shape that failed."""
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
    """The cause, beside the artefact: GIS was never called at all."""
    assert 'infrastructure_proposals' in _run([R077])['gis_actions']


def test_every_row_the_calculation_answers_reaches_the_manifest():
    """Seven rows were answered and excluded: 77, 79, 80, 82, 83, 86, 87.

    Parametrised over the block rather than over the seven, so a row that
    stops being answered fails here instead of going quiet.
    """
    for row in range(77, 89):
        key = f'geotizer_object.v1.r{row:03d}.a01'
        run_log = _run([key])['finalize'].get('run_log') or {}
        assert run_log.get('gis_layer_manifest'), f'row {row} lost the manifest'


def test_the_prefix_set_covers_the_block_it_claims_to_own():
    """`GIS-DC` owns rows 77-88; the tuple must say so without being edited."""
    rows = sorted(prefix.split('.')[2] for prefix in INFRASTRUCTURE_ROW_PREFIXES)
    assert rows == [f'r{row:03d}' for row in range(77, 89)]
    assert len(INFRASTRUCTURE_ROW_PREFIXES) == 12
