"""`source_locator` is polymorphic, and a reader that assumed otherwise was P0.

Measured across two consecutive runs of the same object, identically:

    source_locator types: {'dict': 347, 'str': 4}

The four strings are GIS layer reads. `gis_service`'s scope resolution mints a
*human-readable* source locator —

    project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0;
    geometry=full; coordinates=EPSG:4326; area=EPSG:6933

— and the scope binding copies it onto the fields it binds: rows 2, 3, 8 and
12. Those rows belong to `KB-LIC-LEGAL`, the second batch. So one `.get()` on
that path kills the fill at batch 2, which is what

    {"status": "geotizer_failed", "code": "AttributeError",
     "message": "'str' object has no attribute 'get'"}

was. `evidence_locator_identity` was the reader; its three call sites pass
`... or {}`, which defends against `None` and lets a string straight through.

**Parsing, not guarding.** Two writers in this repository already had the
`isinstance(...) else {}` guard, so they did not crash — they dropped
`layer_id`, `project_id` and `feature_index` and wrote their own key onto an
empty locator instead. A crash fixed by losing data is not fixed, and that
form is worse because nothing reports it.
"""

from __future__ import annotations

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

#: Verbatim from run `05169ef1`, field `geotizer_object.v1.r002.a01`.
LAYER_READ = (
    'project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0; '
    'geometry=full; coordinates=EPSG:4326; area=EPSG:6933'
)


# -- the parser --------------------------------------------------------------


def test_the_string_form_keeps_its_keys():
    """The whole reason this parses rather than guards."""
    parsed = locator_map(LAYER_READ)

    assert parsed['project_id'] == 'lekyn_new_data'
    assert parsed['layer_id'] == 'СЛХ_025834_ТП'
    assert parsed['feature_index'] == '0'
    assert parsed['coordinates'] == 'EPSG:4326'


def test_a_mapping_passes_through_unchanged():
    assert locator_map({'page': 12, 'document_id': 'd'}) == {'page': 12, 'document_id': 'd'}


@pytest.mark.parametrize('value', [None, 7, [], 'no equals signs here', ''])
def test_anything_else_is_an_empty_mapping(value):
    """There is nothing to parse and no key worth inventing."""
    assert locator_map(value) == {}


def test_a_half_formed_string_keeps_the_parts_that_parse():
    """A locator is minted by a formatter, not typed, so a stray segment is a
    reason to keep the rest rather than to discard all of it."""
    assert locator_map('project_id=p; garbage; layer_id=L') == {
        'project_id': 'p',
        'layer_id': 'L',
    }


# -- the reader that crashed -------------------------------------------------


def test_the_reader_that_killed_batch_two_survives_a_string():
    """`'str' object has no attribute 'get'`, exactly."""
    assert evidence_locator_identity(LAYER_READ) == ('', '', '', '', '')
    assert evidence_locator_identity(None) == ('', '', '', '', '')


# -- the writers that were dropping it ---------------------------------------


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
    """It guarded and therefore did not crash -- and replaced the locator with
    `{}` before writing `work_stage` into it, so `layer_id` vanished from the
    cell the qualifier was being added to."""
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
                # Worded to match `_RULE_EXCLUSION`, so the rule actually
                # fires. A test that only asserts when it happens to fire
                # asserts nothing, which is what this one did.
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


# -- and a fill completes ----------------------------------------------------


def test_a_fill_completes_with_a_string_locator_in_batch_two():
    """Not «a dict locator works» -- that already passed. The batch that owns
    the layer reads is driven with one, and the run has to reach `finalized`.
    """
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
                # The scope binding has already put a string locator on the
                # fields it bound, before any batch is submitted.
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
    # And the layer read survived to the submitted patch rather than being
    # replaced by an empty mapping on the way.
    locators = [
        patch['source_locator']
        for payload in submitted
        for patch in payload.get('patches') or []
    ]
    assert any(
        isinstance(item, str) or 'layer_id' in locator_map(item) for item in locators
    )


# -- and the semantic rules see it -------------------------------------------


def test_a_semantic_rule_reads_a_qualifier_out_of_a_string_locator():
    """`semantic = {}` for a string meant every semantic rule silently skipped
    the four layer reads -- the subarea rule, the resource rules and the GRR
    stage rule all saw a field with no qualifiers and passed it. A rule that
    stops running is not a rule that allows something."""
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
