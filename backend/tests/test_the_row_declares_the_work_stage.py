"""The backend injects the work stage a GRR row declares, and the owner prompt shows
where qualifiers go."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import json

from open_webui.services.artifacts.geotizer.owner_envelope import (
    inject_row_declared_work_stage,
)
from open_webui.services.artifacts.geotizer.prompts import _owner_prompt
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.geotizer.semantics import GRR_WORK_STAGE_BY_ROW


def _grr_batch(rows=(68, 69, 70)):
    fields = [
        {
            'field_key': f'geotizer_object.v1.r{row:03d}.a{index:02d}',
            'row_id': row,
            'attribute_name': name,
        }
        for row in rows
        for index, name in enumerate(
            ('вид', 'объемы', 'масштаб', 'стоимость', 'срок', 'документ'), start=1
        )
    ]
    return {
        'batch_id': 'KB-GRR-FACTORS',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v3',
        'template_version': 'geotizer_object.v1',
        'fields': fields,
        'evidence_routes': [],
        'owner_chunk': {'index': 1, 'total': 3},
    }


def _envelope(batch, *, work_stage=None, status='filled'):
    return {
        'source_inventory': [
            {'source_id': 's1', 'source_type': 'knowledge_base', 'title': 'ГРР 2025'}
        ],
        'patches': [
            {
                'field_key': field['field_key'],
                'value': 'значение' if status == 'filled' else None,
                'unit': None,
                'status': status,
                'value_origin': 'direct' if status == 'filled' else None,
                'source_refs': ['s1'],
                'source_locator': {
                    'page_or_chunk_or_layer_or_feature_or_query': 'с. 12',
                    'temporal_role': 'planned',
                    'source_document_id': 'ГРР-2025',
                    **({'work_stage': work_stage} if work_stage else {}),
                },
                'retrieval_note': 'из проекта ГРР 2025',
            }
            for field in batch['fields']
        ],
    }


def test_an_unset_work_stage_is_filled_in_from_the_row():
    batch = _grr_batch()

    repaired, notes = inject_row_declared_work_stage(batch, _envelope(batch))

    for patch in repaired['patches']:
        row = int(patch['field_key'][-7:-4])
        assert patch['source_locator']['work_stage'] == GRR_WORK_STAGE_BY_ROW[row]
    assert 'work_stage' in render_run_notes(notes)[0]


def test_the_injection_is_disclosed_as_a_run_note():
    """The injection produces one run note counting the injected cells."""
    batch = _grr_batch()

    _, notes = inject_row_declared_work_stage(batch, _envelope(batch))

    assert len(notes) == 1
    assert '18' in render_run_notes(notes)[0]


def test_a_work_stage_the_owner_supplied_is_left_alone():
    batch = _grr_batch(rows=(68,))
    envelope = _envelope(batch, work_stage='routes')

    repaired, notes = inject_row_declared_work_stage(batch, envelope)

    assert notes == []
    assert all(p['source_locator']['work_stage'] == 'routes' for p in repaired['patches'])


def test_a_contradicting_work_stage_is_not_repaired_away():
    """A work stage that contradicts the row is kept and still refused by validation."""
    batch = _grr_batch(rows=(68,))
    envelope = _envelope(batch, work_stage='drilling')

    repaired, notes = inject_row_declared_work_stage(batch, envelope)
    violations = validate_owner_envelope(batch, repaired)

    assert notes == []
    assert all(p['source_locator']['work_stage'] == 'drilling' for p in repaired['patches'])
    assert any('work_stage is incompatible' in v for v in violations)


def test_a_cell_that_is_not_filled_is_untouched():
    """A cell that is not `filled` gets no work stage."""
    batch = _grr_batch(rows=(68,))

    repaired, notes = inject_row_declared_work_stage(
        batch, _envelope(batch, status='not_found')
    )

    assert notes == []
    assert all('work_stage' not in p['source_locator'] for p in repaired['patches'])


def test_a_batch_with_no_grr_rows_is_untouched():
    batch = _grr_batch(rows=(68,))
    batch['fields'] = [{**f, 'row_id': 15} for f in batch['fields']]

    repaired, notes = inject_row_declared_work_stage(batch, _envelope(batch))

    assert notes == []
    assert all('work_stage' not in p['source_locator'] for p in repaired['patches'])


def test_the_chunk_that_failed_three_times_now_validates():
    """An envelope missing only the row-declared work stage validates after injection."""
    batch = _grr_batch()
    envelope = _envelope(batch)

    before = validate_owner_envelope(batch, envelope)
    repaired, _ = inject_row_declared_work_stage(batch, envelope)
    after = validate_owner_envelope(batch, repaired)

    assert [v for v in before if 'work_stage is incompatible' in v]
    assert [v for v in after if 'work_stage is incompatible' in v] == []


def test_the_workflow_injects_before_it_validates():
    """`workflow.py` injects the work stage before it calls `validate_owner_envelope`."""
    from pathlib import Path

    import open_webui.services.artifacts.geotizer.workflow as module

    source = Path(module.__file__).read_text(encoding='utf-8')
    inject = source.index('inject_row_declared_work_stage(next_batch, envelope)')
    check = source.index('violations = validate_owner_envelope(')

    assert inject < check


def test_the_output_contract_shows_qualifiers_inside_the_source_locator():
    """The output contract's example `source_locator` shows the required qualifiers,
    including `work_stage`."""
    batch = _grr_batch()
    prompt = _owner_prompt(
        context={'batch': batch}, attempt=1, feedback=None, previous_output=''
    )
    payload = json.loads(prompt)
    locator = payload['output_contract']['patches'][0]['source_locator']

    assert len(locator) > 1
    assert any('required_qualifiers' in str(key) for key in locator)
    assert any('work_stage' in str(value) for value in locator.values())


def test_the_prompt_still_carries_the_required_stage_per_field():
    batch = _grr_batch()
    payload = json.loads(
        _owner_prompt(context={'batch': batch}, attempt=1, feedback=None, previous_output='')
    )

    hint = payload['field_semantics']['geotizer_object.v1.r068.a01']
    assert hint['required_work_stage'] == 'routes'
    assert 'work_stage' in hint['required_qualifiers']
