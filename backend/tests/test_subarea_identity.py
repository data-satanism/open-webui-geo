"""A subarea row must name a subarea, not the object.

Rows 50–53 are the teaser's own subdivision of the licence area into named
участки. The contract checked that `site_name` was *present* and never what it
said, so on run `6056e157`:

    r50  site_name = «Лекын-Тальбейская площадь»   Ямалнедра 2007
    r51  site_name = «Лекын-Тальбейская площадь»   Коммерсантъ 2007
    r52  site_name = «Лекын-Тальбейская площадь»   Вслух.ру 2006

Three subarea rows, five filled attributes each, all carrying the licence area
itself — `object_scope.object_name` verbatim — from three different press
sources. One area-level figure spread across three rows, and every check
passed.

Not what `cohere_resource_estimate_proposals` guards: that collapses competing
identities *within* a row. This is one figure spread *across* rows, which
nothing saw.
"""

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
    """r50, r51 and r52 each carried it on this run."""
    assert _subarea_violations(row_id, OBJECT)


def test_a_real_subarea_name_passes():
    """The rows exist to hold участки 1–3, and refusing those would be worse
    than the defect."""
    assert _subarea_violations(50, 'Участок 1') == []
    assert _subarea_violations(50, 'Северный фланг') == []


def test_a_separator_is_not_a_distinction():
    """`Лекын_Талбейское` and `Лекын-Талбейское` are the same area written two
    ways, and an underscore is not a subarea."""
    assert _subarea_violations(50, 'Лекын_Талбейское', object_name='Лекын-Талбейское')
    assert _subarea_violations(50, 'лекын талбейское', object_name='Лекын-Талбейское')


def test_the_violation_names_the_value_and_says_what_the_rows_are_for():
    violation = _subarea_violations(50, OBJECT)[0]

    assert OBJECT in violation
    assert 'named subareas' in violation


def test_rows_outside_the_subarea_block_are_untouched():
    """Row 47 is the licence area's own approved estimate. Naming the object
    there is correct."""
    assert _subarea_violations(47, OBJECT) == []
    assert _subarea_violations(54, OBJECT) == []


def test_a_patch_that_is_not_filled_is_untouched():
    """`not_found` carries no figure to be attributed to the wrong row."""
    assert _subarea_violations(50, OBJECT, status='not_found') == []


def test_the_rule_is_off_when_the_caller_supplies_no_object_name():
    """The GIS batch does not carry the object name, and the parity corpus
    calls the validator without one. Guessing would make the local copy
    stricter than the service on cases the corpus checks.

    The `not object_name` guard is also what keeps an envelope with no site
    name and no object name from matching itself on two empty strings."""
    assert _subarea_violations(50, OBJECT, object_name='') == []
    assert _subarea_violations(50, '', object_name='') == []


def test_an_absent_site_name_gets_one_violation_and_not_two():
    """`_resource_patch_violations` already refuses it. Two violations for one
    mistake is how a repair loop spends an attempt fixing the same thing
    twice."""
    violations = validate_owner_envelope(
        _batch(50), _envelope(50, ''), object_name=OBJECT
    )
    about_site = [v for v in violations if 'site_name' in v or 'subarea row' in v]

    assert len(about_site) == 1
    assert 'requires named site_name' in about_site[0]


def test_the_workflow_hands_the_validator_the_resolved_scope_name():
    """The wiring, which nothing asserted.

    Deleting the object name at the two `validate_owner_envelope` call sites
    left every test above green and 109 orchestration tests with it. The rule
    also has to read the *resolved* name: this run was asked for
    `Лекын_Талбейское` and the subarea rows carried `Лекын-Тальбейская
    площадь`, which is `object_scope.object_name` and not the request.
    """
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
                # The resolved identity, spelled differently from the request.
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
    # Refused, so the cell does not ship as a filled subarea figure.
    assert patch['status'] != 'filled' or patch.get('source_locator', {}).get('site_name') != OBJECT
