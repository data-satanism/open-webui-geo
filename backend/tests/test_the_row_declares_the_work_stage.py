"""Three attempts, eighteen cells, one constant the backend already had.

`KB-GRR-FACTORS` chunk 1/3 on run `05169ef1` returned the same nine violations
three times:

    patches[0]  ... GRR work_stage is incompatible with row 68;
                    required: 'routes', got '(unset)'

on exactly `вид`, `срок` and `документ` of rows 68, 69 and 70 -- never on the
three quantitative attributes. Seven cells ended `agent_contract_failed`.

The model was not under-informed. `semantic_hint` puts `required_work_stage`
and lists `work_stage` in `required_qualifiers` from attempt 1, and the model
demonstrably complies elsewhere: r68 «вид», r75 and r76 all carry the right
`work_stage` in this same run. Two things were wrong instead.

**Nothing said where the qualifier goes.** `required_qualifiers` names the keys
and no destination, and the only worked example of a `source_locator` in the
output contract showed one unrelated key. On the `not_found` cells of this run
the model put `work_stage: geophysics` in the *prose* of `retrieval_note`,
which is what something told a value is required and not told where to put it
does.

**And it should not have been asked.** `GRR_WORK_STAGE_BY_ROW[row_id]` is a
constant lookup -- row 68 is always `routes`. `backend_owned_envelope` already
names this category: values "injected and validated by the backend. Do not
spend output tokens echoing them."
"""

from __future__ import annotations

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


# -- the injection -----------------------------------------------------------


def test_an_unset_work_stage_is_filled_in_from_the_row():
    batch = _grr_batch()

    repaired, notes = inject_row_declared_work_stage(batch, _envelope(batch))

    for patch in repaired['patches']:
        row = int(patch['field_key'][-7:-4])
        assert patch['source_locator']['work_stage'] == GRR_WORK_STAGE_BY_ROW[row]
    assert notes and 'work_stage' in notes[0]


def test_the_injection_is_disclosed_as_a_run_note():
    """A silent repair is how a card comes to rest on a value nobody chose --
    even when the value is a constant the backend owns."""
    batch = _grr_batch()

    _, notes = inject_row_declared_work_stage(batch, _envelope(batch))

    assert len(notes) == 1
    assert '18' in notes[0]


def test_a_work_stage_the_owner_supplied_is_left_alone():
    batch = _grr_batch(rows=(68,))
    envelope = _envelope(batch, work_stage='routes')

    repaired, notes = inject_row_declared_work_stage(batch, envelope)

    assert notes == []
    assert all(p['source_locator']['work_stage'] == 'routes' for p in repaired['patches'])


def test_a_contradicting_work_stage_is_not_repaired_away():
    """It carries information: it says the owner misread which row it was
    answering. Filling over it would turn a readable mistake into a silent one."""
    batch = _grr_batch(rows=(68,))
    envelope = _envelope(batch, work_stage='drilling')

    repaired, notes = inject_row_declared_work_stage(batch, envelope)
    violations = validate_owner_envelope(batch, repaired)

    assert notes == []
    assert all(p['source_locator']['work_stage'] == 'drilling' for p in repaired['patches'])
    assert any('work_stage is incompatible' in v for v in violations)


def test_a_cell_that_is_not_filled_is_untouched():
    """The rule only fires on `filled`, so injecting elsewhere would add a
    qualifier to a cell that is asserting absence."""
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


# -- and the result: the run stops failing on it -----------------------------


def test_the_chunk_that_failed_three_times_now_validates():
    """The whole point. This envelope -- every GRR qualifier present except the
    one the row declares -- is what the owner returned on all three attempts."""
    batch = _grr_batch()
    envelope = _envelope(batch)

    before = validate_owner_envelope(batch, envelope)
    repaired, _ = inject_row_declared_work_stage(batch, envelope)
    after = validate_owner_envelope(batch, repaired)

    assert [v for v in before if 'work_stage is incompatible' in v]
    assert [v for v in after if 'work_stage is incompatible' in v] == []


def test_the_workflow_injects_before_it_validates():
    """The wiring. A repair applied after validation repairs nothing, and this
    pipeline has produced a helper nothing called seven times."""
    from pathlib import Path

    import open_webui.services.artifacts.geotizer.workflow as module

    source = Path(module.__file__).read_text(encoding='utf-8')
    inject = source.index('inject_row_declared_work_stage(next_batch, envelope)')
    check = source.index('violations = validate_owner_envelope(')

    assert inject < check


# -- and the prompt says where a qualifier goes ------------------------------


def test_the_output_contract_shows_qualifiers_inside_the_source_locator():
    """`required_qualifiers` named the keys and no destination. The one worked
    example of a `source_locator` showed a shape with none of them in it."""
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
