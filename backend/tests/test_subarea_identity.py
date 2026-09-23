"""A subarea row (rows 50-53) must name a subarea, not the object."""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.validation import (
    NAMED_SUBAREA_ROWS,
    validate_owner_envelope,
)

OBJECT = 'Лекын-Тальбейская площадь'


def _batch(row_id):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': f'geotizer_object.v1.r{row_id:03d}.a01', 'row_id': row_id}],
    }


def _envelope(row_id, site_name, *, status='filled'):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 's1', 'source_type': 'knowledge_base', 'title': 't', 'locator': 'p', 'url': None}
        ],
        'patches': [
            {
                'field_key': f'geotizer_object.v1.r{row_id:03d}.a01',
                'status': status,
                'value': '12' if status == 'filled' else None,
                'unit': 'т' if status == 'filled' else None,
                'value_origin': 'direct' if status == 'filled' else None,
                'source_refs': ['s1'],
                'retrieval_note': 'n',
                'source_locator': {
                    'entity_id': 'e1',
                    'entity_scope': 'named_subarea',
                    'estimate_state': 'author_estimate',
                    'resource_estimate_id': 'r1',
                    'site_name': site_name,
                },
            }
        ],
    }


def _subarea_violations(row_id, site_name, *, object_name=OBJECT, status='filled'):
    return [
        violation
        for violation in validate_owner_envelope(
            _batch(row_id), _envelope(row_id, site_name, status=status), object_name=object_name
        )
        if 'subarea row' in violation
    ]


@pytest.mark.parametrize('row_id', list(NAMED_SUBAREA_ROWS))
def test_the_object_name_is_refused_on_every_subarea_row(row_id):
    """The object name is refused as `site_name` on every subarea row."""
    assert _subarea_violations(row_id, OBJECT)


def test_a_real_subarea_name_passes():
    """A real subarea name passes."""
    assert _subarea_violations(50, 'Участок 1') == []
    assert _subarea_violations(50, 'Северный фланг') == []


def test_a_separator_is_not_a_distinction():
    """The object name matches across separators and case."""
    assert _subarea_violations(50, 'Лекын_Талбейское', object_name='Лекын-Талбейское')
    assert _subarea_violations(50, 'лекын талбейское', object_name='Лекын-Талбейское')


def test_the_violation_names_the_value_and_says_what_the_rows_are_for():
    violation = _subarea_violations(50, OBJECT)[0]

    assert OBJECT in violation
    assert 'named subareas' in violation


def test_rows_outside_the_subarea_block_are_untouched():
    """Rows outside `NAMED_SUBAREA_ROWS` may name the object."""
    assert _subarea_violations(47, OBJECT) == []
    assert _subarea_violations(54, OBJECT) == []


def test_a_patch_that_is_not_filled_is_untouched():
    """A patch that is not `filled` is not checked."""
    assert _subarea_violations(50, OBJECT, status='not_found') == []


def test_the_rule_is_off_when_the_caller_supplies_no_object_name():
    """Without an object name the rule does not run, including for an empty `site_name`."""
    assert _subarea_violations(50, OBJECT, object_name='') == []
    assert _subarea_violations(50, '', object_name='') == []


def test_an_absent_site_name_gets_one_violation_and_not_two():
    """An absent `site_name` gets only the resource rule's violation."""
    violations = validate_owner_envelope(
        _batch(50), _envelope(50, ''), object_name=OBJECT
    )
    about_site = [v for v in violations if 'site_name' in v or 'subarea row' in v]

    assert len(about_site) == 1
    assert 'requires named site_name' in about_site[0]


def test_the_workflow_hands_the_validator_the_resolved_scope_name():
    """`run_geotizer_workflow` validates subarea rows against the resolved
    `object_scope.object_name`."""
    import asyncio
    import json

    value = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': 'geotizer_object.v1.r050.a01', 'row_id': 50}],
    }
    submitted = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-subarea',
                'object_name': 'Лекын_Талбейское',
                'object_scope': {'object_name': OBJECT},
                'datacube': {},
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            return {'workflow_status': 'collecting', 'run_id': 'run-subarea', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-subarea',
            'xlsx': {'download_path': '/geotizer/files/run-subarea/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(_envelope(50, OBJECT), ensure_ascii=False)

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын_Талбейское',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
        )
    )

    assert submitted, 'no batch was submitted'
    patch = submitted[0]['patches'][0]
    assert patch['status'] != 'filled' or patch.get('source_locator', {}).get('site_name') != OBJECT
