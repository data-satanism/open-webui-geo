"""A value a rule refused is `requires_expert_review`, not `not_found`."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import classify_rule_excluded_patches

GRR_NOTE = (
    'Searched GIS, KB, Web, Datacube. No 2024-2026 GRR Plan found. '
    "Historical data excluded by rule 'historical_actual_is_not_plan'."
)
GRR_ROW = 71


def _batch(row_id=GRR_ROW, keys=('k1',)):
    return {'fields': [{'field_key': key, 'row_id': row_id} for key in keys]}


def _envelope(note, *, status='not_found', key='k1', locator=None):
    return {
        'patches': [
            {
                'field_key': key,
                'status': status,
                'value': None,
                'source_refs': ['s1'],
                'retrieval_note': note,
                **({'source_locator': locator} if locator is not None else {}),
            }
        ]
    }


def _classified(note, **kwargs):
    envelope, notes = classify_rule_excluded_patches(_batch(), _envelope(note, **kwargs))
    return envelope['patches'][0], notes


def test_a_rule_excluded_cell_leaves_the_not_found_bucket():
    patch, notes = _classified(GRR_NOTE)

    assert patch['status'] == 'requires_expert_review'
    assert notes


def test_the_reason_is_machine_readable_and_names_the_rule():
    """The reason carries `reason_kind: excluded_by_rule`, the rule and `decided_by:
    policy`."""
    patch, _ = _classified(GRR_NOTE)
    reason = patch['source_locator']['if_not_why_not']

    assert reason['reason_kind'] == 'excluded_by_rule'
    assert reason['rule'] == 'historical_actual_is_not_plan'
    assert reason['decided_by'] == 'policy'


def test_the_specialist_sentence_is_kept_verbatim_and_bounded():
    """The specialist's note is kept as `specialist_note`, verbatim and bounded."""
    patch, _ = _classified(GRR_NOTE)
    reason = patch['source_locator']['if_not_why_not']

    assert 'No 2024-2026 GRR Plan found' in reason['specialist_note']

    long_note = GRR_NOTE + ' ' + 'и' * 2000
    long_patch, _ = _classified(long_note)
    stated = long_patch['source_locator']['if_not_why_not']['specialist_note']

    assert len(stated) < len(long_note) // 3
    assert stated.startswith('Searched GIS')


def test_the_cell_says_it_in_the_readers_language_and_names_no_rule():
    """The cell's `retrieval_note` and `stated_reason` are `POLICY_EXCLUSION_NOTE_RU`,
    which names no rule."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        POLICY_EXCLUSION_NOTE_RU,
    )

    patch, _ = _classified(GRR_NOTE)

    assert patch['retrieval_note'] == POLICY_EXCLUSION_NOTE_RU
    assert 'historical_actual_is_not_plan' not in patch['retrieval_note']
    assert patch['source_locator']['if_not_why_not']['stated_reason'] == (
        POLICY_EXCLUSION_NOTE_RU
    )


def test_a_rule_the_row_does_not_declare_is_ignored():
    """A rule the row's `negative_cases` do not declare is ignored."""
    patch, notes = _classified("Excluded by rule 'a_rule_nobody_declared'.")

    assert patch['status'] == 'not_found'
    assert notes == []


def test_a_declared_rule_on_the_wrong_row_is_ignored():
    """A rule declared on another row is ignored."""
    envelope, notes = classify_rule_excluded_patches(
        _batch(row_id=1), _envelope(GRR_NOTE)
    )

    assert envelope['patches'][0]['status'] == 'not_found'
    assert notes == []


@pytest.mark.parametrize('status', ['filled', 'conflicted', 'requires_expert_review', 'not_applicable'])
def test_only_not_found_is_reclassified(status):
    """Only a `not_found` cell is reclassified."""
    patch, notes = _classified(GRR_NOTE, status=status)

    assert patch['status'] == status
    assert notes == []


def test_a_plain_absence_is_left_alone():
    """A `not_found` cell whose note names no rule is left unchanged."""
    patch, notes = _classified('Прямые данные о плане ГРР не найдены в доступных источниках.')

    assert patch['status'] == 'not_found'
    assert notes == []


def test_an_existing_locator_is_preserved():
    """The existing locator keys are kept beside the added reason."""
    patch, _ = _classified(GRR_NOTE, locator={'page': 12, 'work_stage': 'prospecting'})

    assert patch['source_locator']['page'] == 12
    assert patch['source_locator']['work_stage'] == 'prospecting'
    assert 'if_not_why_not' in patch['source_locator']


def test_the_input_envelope_is_not_mutated():
    """The input envelope is not mutated."""
    original = _envelope(GRR_NOTE)
    classify_rule_excluded_patches(_batch(), original)

    assert original['patches'][0]['status'] == 'not_found'
    assert 'source_locator' not in original['patches'][0]


def test_every_reclassification_is_recorded():
    """Every reclassified cell produces a run note naming its field key."""
    envelope, notes = classify_rule_excluded_patches(
        _batch(keys=('k1', 'k2')),
        {
            'patches': [
                {'field_key': 'k1', 'status': 'not_found', 'value': None,
                 'source_refs': ['s'], 'retrieval_note': GRR_NOTE},
                {'field_key': 'k2', 'status': 'not_found', 'value': None,
                 'source_refs': ['s'], 'retrieval_note': GRR_NOTE},
            ]
        },
    )

    assert len(notes) == 2
    assert any('k1' in note for note in render_run_notes(notes))
    assert any('k2' in note for note in render_run_notes(notes))
    assert all(patch['status'] == 'requires_expert_review' for patch in envelope['patches'])


def test_the_workflow_reaches_the_classifier():
    """`run_geotizer_workflow` reclassifies a rule-excluded cell before `submit_batch`
    and records a run note."""
    import asyncio
    import json

    value = {
        'batch_id': 'KB-GRR-FACTORS',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': 'geotizer_object.v1.r071.a01', 'row_id': GRR_ROW}],
        'evidence_routes': [],
    }
    submitted = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-rule-excluded',
                'object_name': 'Лекын',
                'object_scope': {'object_name': 'Лекын-Тальбейская площадь'},
                'datacube': {},
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            return {'workflow_status': 'collecting', 'run_id': 'run-rule-excluded', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-rule-excluded',
            'xlsx': {'download_path': '/geotizer/files/run-rule-excluded/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(
            {
                'source_inventory': [
                    {'source_id': 's1', 'source_type': 'knowledge_base', 'title': 't',
                     'locator': 'p', 'url': None}
                ],
                'patches': [
                    {
                        'field_key': 'geotizer_object.v1.r071.a01',
                        'status': 'not_found',
                        'value': None,
                        'unit': None,
                        'value_origin': None,
                        'source_refs': ['s1'],
                        'retrieval_note': GRR_NOTE,
                    }
                ],
            },
            ensure_ascii=False,
        )

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

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

    assert submitted, 'no batch was submitted'
    patch = submitted[0]['patches'][0]
    assert patch['status'] == 'requires_expert_review', patch['status']
    assert patch['source_locator']['if_not_why_not']['rule'] == 'historical_actual_is_not_plan'
    assert any('historical_actual_is_not_plan' in note for note in final.get('run_notes') or [])


GEOLOGICAL_NOTE = (
    'Экспертная оценка по смежному участку: зона дробления шириной 4-6 м. '
    'Требуется полевая проверка.'
)


def _refused_chunk_then_salvage(salvaged_patch):
    """A chunk the owner contract refused, with one cell salvaged out of it."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        owner_failure_envelope,
    )

    field = {'field_key': 'geotizer_object.v1.r019.a02', 'row_id': 19,
             'attribute_name': 'значение'}
    next_batch = {
        'batch_id': 'KB-GEO',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'owner_chunk': {'index': 1, 'total': 2},
        'accepted_field_statuses': ['agent_contract_failed'],
        'fields': [field],
    }
    return owner_failure_envelope(
        next_batch,
        run_id='r1',
        attempts=2,
        feedback=["patches[0] …"],
        object_name='Нявленга',
        candidate_envelopes=[{
            'source_inventory': [
                {'source_id': 'kb-1', 'source_type': 'knowledge_base',
                 'title': 'Отчёт', 'locator': 'стр. 4'},
            ],
            'patches': [salvaged_patch],
        }],
    )


def test_a_salvaged_cell_no_longer_carries_the_chunk_s_refusal_marks():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        SALVAGED_CELL_STRIPPED_KEYS,
    )

    envelope = _refused_chunk_then_salvage({
        'field_key': 'geotizer_object.v1.r019.a02',
        'value': None,
        'unit': None,
        'status': 'requires_expert_review',
        'value_origin': None,
        'source_refs': ['kb-1'],
        'retrieval_note': GEOLOGICAL_NOTE,
    })
    patch = envelope['patches'][0]

    assert patch['retrieval_note'] == GEOLOGICAL_NOTE
    locator = patch.get('source_locator') or {}
    for key in SALVAGED_CELL_STRIPPED_KEYS:
        assert key not in locator, key


def test_a_cell_salvage_did_not_rescue_keeps_them():
    """A cell salvage did not rescue keeps its `owner_attempt_feedback` and
    `owner_attempt_diagnostics`."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        owner_failure_envelope,
    )

    envelope = owner_failure_envelope(
        {
            'batch_id': 'KB-GEO',
            'producer': 'kb',
            'policy_version': 'geotizer_assignments.v1',
            'template_version': 'geotizer_object.v1',
            'owner_chunk': {'index': 1, 'total': 2},
            'accepted_field_statuses': ['agent_contract_failed'],
            'fields': [{'field_key': 'geotizer_object.v1.r019.a02', 'row_id': 19,
                        'attribute_name': 'значение'}],
        },
        run_id='r1',
        attempts=2,
        feedback=["patches[0] …"],
        feedback_by_attempt=[{'attempt': 1, 'violations': ["patches[0] …"]}],
        attempt_diagnostics=[{'attempt': 1, 'response_mode': 'parsed'}],
        object_name='Нявленга',
    )
    patch = envelope['patches'][0]

    assert patch['status'] == 'agent_contract_failed'
    assert patch['source_locator']['owner_attempt_feedback']
    assert patch['source_locator']['owner_attempt_diagnostics']
