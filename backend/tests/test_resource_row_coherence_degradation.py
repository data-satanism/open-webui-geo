"""A row that reports two estimates is one wrong row, not a failed run.

Run `6a791799` ended on «resource row 48 mixes resource_estimate_id:
['RE-2001-PKH', 'RE-2025-PROJ']» -- a `GeotizerOrchestrationError` out of
`merge_owner_envelopes`, with every other batch already answered and nothing
written. The whole card was thrown away over six cells.

This is the only rule in the envelope contract that can first fail at merge
time, which is why it is the only one degraded here. Everything else
`validate_owner_envelope` checks is per patch -- and so already checked when
the chunk was accepted -- or structural, and a marked row cannot repair a
partition. The two tests at the bottom are what would notice if that stopped
being true.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
import pytest

from open_webui.services.geotizer.errors import GeotizerOrchestrationError
from open_webui.services.artifacts.geotizer.owner_envelope import (
    INCOHERENT_ESTIMATE_ROW_TRACE,
    merge_owner_envelopes,
)
from open_webui.services.artifacts.geotizer.validation import (
    resource_row_identity_conflicts,
)
from open_webui.services.geotizer.semantics import ESTIMATE_ROW_IDENTITY_QUALIFIERS

ROW_48 = [f'geotizer_object.v1.r048.a{index:02d}' for index in range(1, 7)]
ROW_47 = [f'geotizer_object.v1.r047.a{index:02d}' for index in range(1, 7)]


def locator(estimate_id: str, **extra):
    return {
        'entity_id': 'Lekyn-Talbeyskaya',
        'entity_scope': 'licence_area',
        'estimate_state': 'current',
        'resource_estimate_id': estimate_id,
        'value_kind': 'resource_quantity',
        **extra,
    }


def batch(field_keys):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v3',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {'field_key': key, 'row_id': int(key.split('.r')[1][:3])}
            for key in field_keys
        ],
        'evidence_routes': [],
    }


def envelope(value, patches):
    return {
        'batch_id': value['batch_id'],
        'producer': value['producer'],
        'policy_version': value['policy_version'],
        'template_version': value['template_version'],
        'source_inventory': [
            {'source_id': 'src', 'source_type': 'document', 'title': 'Отчёт'}
        ],
        'patches': patches,
    }


def filled(field_key, value, estimate_id):
    return {
        'field_key': field_key,
        'value': value,
        'status': 'filled',
        'value_origin': 'direct',
        'source_refs': ['src'],
        'source_locator': locator(estimate_id),
        'retrieval_note': 'Из отчёта.',
    }


def merged_for(patches, field_keys):
    value = batch(field_keys)
    return merge_owner_envelopes(value, [value], [envelope(value, patches)], run_id='run-1')


def by_key(merged):
    return {patch['field_key']: patch for patch in merged['patches']}


# ---------------------------------------------------------- the row degrades


def test_a_row_reporting_two_estimates_is_marked_and_the_run_continues():
    patches = [
        filled(ROW_48[0], '250 тыс. т', 'RE-2001-PKH'),
        filled(ROW_48[1], '12 млн т', 'RE-2001-PKH'),
        filled(ROW_48[2], '1,2 %', 'RE-2025-PROJ'),
        *[
            {
                **filled(key, f'значение {index}', 'RE-2007-APPROVED'),
                'source_locator': locator('RE-2007-APPROVED', estimate_state='approved'),
            }
            for index, key in enumerate(ROW_47)
        ],
    ]
    merged, notes = merged_for(patches, [*ROW_48[:3], *ROW_47])
    patch_by_key = by_key(merged)

    for key in ROW_48[:3]:
        patch = patch_by_key[key]
        assert patch['status'] == 'requires_expert_review'
        assert 'RE-2001-PKH' in patch['value'] and 'RE-2025-PROJ' in patch['value']
        # The value the cell actually carried survives inside the review text.
        # A row nobody searched and a row whose answers cannot be read together
        # are different findings and must not render alike.
        assert patch['value_origin'] is None
        assert patch['source_locator']['coherence_refusal'] == INCOHERENT_ESTIMATE_ROW_TRACE
    assert '250 тыс. т' in patch_by_key[ROW_48[0]]['value']

    # The rest of the batch is untouched.
    for key in ROW_47:
        assert patch_by_key[key]['status'] == 'filled'

    assert len(notes) == 1
    assert '48' in render_run_notes(notes)[0] and 'RE-2001-PKH' in render_run_notes(notes)[0] and 'RE-2025-PROJ' in render_run_notes(notes)[0]


def test_a_row_split_across_two_chunks_is_caught_at_the_merge():
    """The shape that actually ended run `6a791799`.

    `partition_owner_batch` is a fixed-width slice, and a retry batch's fields
    are whatever is still empty, so its chunks do not divide into whole rows
    the way a first pass does. Each chunk here is coherent on its own; the row
    is not, and only the merged view can see it.
    """
    value = batch(ROW_48[:4])
    chunks = [batch(ROW_48[:2]), batch(ROW_48[2:4])]
    envelopes = [
        envelope(chunks[0], [
            filled(ROW_48[0], '250 тыс. т', 'RE-2001-PKH'),
            filled(ROW_48[1], '12 млн т', 'RE-2001-PKH'),
        ]),
        envelope(chunks[1], [
            filled(ROW_48[2], '1,2 %', 'RE-2025-PROJ'),
            filled(ROW_48[3], '300 м', 'RE-2025-PROJ'),
        ]),
    ]
    merged, notes = merge_owner_envelopes(value, chunks, envelopes, run_id='run-1')
    assert {patch['status'] for patch in merged['patches']} == {'requires_expert_review'}
    assert len(notes) == 1
    assert 'RE-2001-PKH' in render_run_notes(notes)[0] and 'RE-2025-PROJ' in render_run_notes(notes)[0]


def test_a_coherent_batch_is_returned_unchanged_and_says_nothing():
    patches = [filled(key, f'значение {index}', 'RE-ONE') for index, key in enumerate(ROW_48)]
    merged, notes = merged_for(patches, ROW_48)
    assert notes == []
    assert all(patch['status'] == 'filled' for patch in merged['patches'])


def test_a_structural_violation_still_ends_the_batch():
    """Degrading a row is not a licence to accept a broken envelope."""
    patches = [
        filled(ROW_48[0], '250 тыс. т', 'RE-2001-PKH'),
        {**filled(ROW_48[1], '12 млн т', 'RE-2025-PROJ'), 'source_refs': ['nowhere']},
    ]
    with pytest.raises(GeotizerOrchestrationError, match='unregistered source_refs'):
        merged_for(patches, ROW_48[:2])


# ------------------------------------------------ the identity is the contract


def test_the_conflicting_qualifiers_are_reported_per_row_as_data():
    patches = [
        filled(ROW_48[0], '250 тыс. т', 'RE-A'),
        filled(ROW_48[1], '12 млн т', 'RE-B'),
    ]
    value = batch(ROW_48[:2])
    assert resource_row_identity_conflicts(value, patches) == {
        48: {'resource_estimate_id': ['RE-A', 'RE-B']}
    }


def test_a_subarea_row_mixing_two_sites_is_a_conflict():
    """`site_name` is a row-50 qualifier the previous single list left out."""
    keys = [f'geotizer_object.v1.r050.a{index:02d}' for index in (1, 2)]
    patches = [
        {
            **filled(keys[0], '80 тыс. т', 'RE-SAME'),
            'source_locator': locator('RE-SAME', entity_scope='named_subarea', site_name='Участок 1'),
        },
        {
            **filled(keys[1], '4 млн т', 'RE-SAME'),
            'source_locator': locator('RE-SAME', entity_scope='named_subarea', site_name='Участок 2'),
        },
    ]
    assert resource_row_identity_conflicts(batch(keys), patches) == {
        50: {'site_name': ['Участок 1', 'Участок 2']}
    }


def test_two_documents_about_one_analogue_deposit_are_not_a_conflict():
    """Row 55 of run `92661b9b`, which the contract's own list would refuse."""
    keys = [f'geotizer_object.v1.r055.a{index:02d}' for index in (1, 2)]
    common = {
        'entity_id': 'saurey-deposit',
        'entity_scope': 'analogue_deposit',
        'analogue_relation': 'neighbouring_structure',
    }
    patches = [
        {
            **filled(keys[0], 'Сауреевское', 'RE-X'),
            'source_locator': {**common, 'source_document_id': 'viken-2020-pdf'},
        },
        {
            **filled(keys[1], 'медно-порфировый', 'RE-X'),
            'source_locator': {**common, 'source_document_id': 'expert-ural-2007-article'},
        },
    ]
    assert 'source_document_id' not in ESTIMATE_ROW_IDENTITY_QUALIFIERS[55]
    assert resource_row_identity_conflicts(batch(keys), patches) == {}
