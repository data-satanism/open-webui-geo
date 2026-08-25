"""A value a rule refused is not a value nobody found.

Run `92661b9b` returned `KB-GRR-FACTORS` at 0/42, and 18 of those cells read:

    Searched GIS, KB, Web, Datacube. No 2024-2026 GRR Plan found.
    Historical data excluded by rule 'historical_actual_is_not_plan'.

The rule is correct and it is the fix the domain review asked for: those rows
used to fill with an investment declaration's 4 bn ₽ and three years — an
investment figure standing in as a ГРР budget, duplicated onto the `all_grr`
summary row. Wrong values were replaced by nothing.

`not_found` is still the wrong status for it. It means *we looked and there is
nothing*; the truth is *we found 2007 data and policy refused it*. The card said
less than the run knew, and it put a cell the programme deliberately emptied in
the same bucket as a cell nobody found anything for.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import classify_rule_excluded_patches

GRR_NOTE = (
    'Searched GIS, KB, Web, Datacube. No 2024-2026 GRR Plan found. '
    "Historical data excluded by rule 'historical_actual_is_not_plan'."
)
#: Row 71 is a ГРР plan row, and its `negative_cases` declare the rule above.
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
    """A reader deciding whether to rerun needs to know rerunning will not help:
    the policy will refuse the same evidence again."""
    patch, _ = _classified(GRR_NOTE)
    reason = patch['source_locator']['if_not_why_not']

    assert reason['reason_kind'] == 'excluded_by_rule'
    assert reason['rule'] == 'historical_actual_is_not_plan'
    assert reason['decided_by'] == 'policy'


def test_the_specialist_sentence_is_kept_verbatim_and_bounded():
    """What would satisfy the requirement is the specialist's own sentence --
    "No 2024-2026 GRR Plan found". This code is not in a position to know what a
    current approved ГРР plan looks like, and a generated remedy would read
    exactly like a real one."""
    patch, _ = _classified(GRR_NOTE)

    assert 'No 2024-2026 GRR Plan found' in patch['source_locator']['if_not_why_not']['stated_reason']

    long_note = GRR_NOTE + ' ' + 'и' * 2000
    long_patch, _ = _classified(long_note)
    stated = long_patch['source_locator']['if_not_why_not']['stated_reason']

    # `bounded_text` keeps 600 characters and appends a marker saying it cut,
    # so the bound is on the quoted text and not on the field. What matters is
    # that a 2 kB note cannot ride into the card whole.
    assert len(stated) < len(long_note) // 3
    assert stated.startswith('Searched GIS')


def test_a_rule_the_row_does_not_declare_is_ignored():
    """The guard against a model moving its own cell out of `not_found` by
    asserting a policy that does not exist. Only the row's own
    `negative_cases`, which `semantic_hint` publishes as `rules`, count."""
    patch, notes = _classified("Excluded by rule 'a_rule_nobody_declared'.")

    assert patch['status'] == 'not_found'
    assert notes == []


def test_a_declared_rule_on_the_wrong_row_is_ignored():
    """`historical_actual_is_not_plan` is declared on plan rows. Row 1 is a
    licence field and has no business citing it."""
    envelope, notes = classify_rule_excluded_patches(
        _batch(row_id=1), _envelope(GRR_NOTE)
    )

    assert envelope['patches'][0]['status'] == 'not_found'
    assert notes == []


@pytest.mark.parametrize('status', ['filled', 'conflicted', 'requires_expert_review', 'not_applicable'])
def test_only_not_found_is_reclassified(status):
    """A filled cell whose note happens to mention a rule was not refused by
    it, and a cell already under review does not need moving twice."""
    patch, notes = _classified(GRR_NOTE, status=status)

    assert patch['status'] == status
    assert notes == []


def test_a_plain_absence_is_left_alone():
    """The status is right for a cell nobody found anything for, and that is
    most of them."""
    patch, notes = _classified('Прямые данные о плане ГРР не найдены в доступных источниках.')

    assert patch['status'] == 'not_found'
    assert notes == []


def test_an_existing_locator_is_preserved():
    """The locator carries the evidence identity. Replacing it to add a reason
    would drop the provenance the reason is about."""
    patch, _ = _classified(GRR_NOTE, locator={'page': 12, 'work_stage': 'prospecting'})

    assert patch['source_locator']['page'] == 12
    assert patch['source_locator']['work_stage'] == 'prospecting'
    assert 'if_not_why_not' in patch['source_locator']


def test_the_input_envelope_is_not_mutated():
    """Salvage walks the pre-enrichment envelope, so a pass that mutated in
    place would rewrite the copy it falls back to."""
    original = _envelope(GRR_NOTE)
    classify_rule_excluded_patches(_batch(), original)

    assert original['patches'][0]['status'] == 'not_found'
    assert 'source_locator' not in original['patches'][0]


def test_every_reclassification_is_recorded():
    """A silent status change is how a card comes to report something nobody
    can trace."""
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
    """The wiring, which is the half that keeps going missing.

    Every test above passes with the call deleted from the retry loop. That is
    the sixth time in this codebase, so the call site gets its own assertion:
    drive the real workflow with an owner that returns a rule-excluded cell and
    read the patch that was submitted.
    """
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
    # and the run says it happened, rather than changing a status in silence
    assert any('historical_actual_is_not_plan' in note for note in final.get('run_notes') or [])
