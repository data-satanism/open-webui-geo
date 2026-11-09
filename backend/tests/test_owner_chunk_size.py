"""The owner chunk size never splits a resource row, and smaller sizes cost proportionally more owner calls."""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import partition_owner_batch
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.artifacts.geotizer.workflow import MAX_OWNER_FIELDS_PER_CALL

RESOURCE_ROW_WIDTH = 6
RESOURCE_ROWS = tuple(range(44, 57))


def _resource_batch():
    """The KB-RESOURCE-TECH shape: thirteen rows, six attributes each."""
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {'field_key': f'geotizer_object.v1.r{row:03d}.a{attr:02d}', 'row_id': row}
            for row in RESOURCE_ROWS
            for attr in range(1, RESOURCE_ROW_WIDTH + 1)
        ],
    }


def _rows_split(batch, max_fields):
    chunks = partition_owner_batch(batch, max_fields=max_fields)
    seen: dict[int, set[int]] = {}
    for index, chunk in enumerate(chunks, start=1):
        for field in chunk['fields']:
            seen.setdefault(field['row_id'], set()).add(index)
    return {row for row, indexes in seen.items() if len(indexes) > 1}


def test_the_configured_chunk_size_does_not_split_a_resource_row():
    """`MAX_OWNER_FIELDS_PER_CALL` is a multiple of the resource row width and splits no resource row."""
    assert MAX_OWNER_FIELDS_PER_CALL % RESOURCE_ROW_WIDTH == 0
    assert _rows_split(_resource_batch(), MAX_OWNER_FIELDS_PER_CALL) == set()


@pytest.mark.parametrize(('max_fields', 'splits'), [(18, False), (12, False), (8, True)])
def test_the_three_proposed_sizes_divide_the_row_differently(max_fields, splits):
    """Chunk sizes 18 and 12 split no resource row; 8 does."""
    assert bool(_rows_split(_resource_batch(), max_fields)) is splits


def test_a_split_row_loses_the_consistency_check_that_would_have_caught_it():
    """A row whose patches mix `entity_id` values is refused whole and passes when validated in two halves."""
    batch = _resource_batch()
    row = 44
    row_fields = [field for field in batch['fields'] if field['row_id'] == row]

    def envelope(fields, entity_ids):
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
                    'field_key': field['field_key'],
                    'status': 'filled',
                    'value': '1',
                    'unit': 'т',
                    'value_origin': 'direct',
                    'source_refs': ['s1'],
                    'source_locator': {
                        'entity_id': entity_id,
                        'entity_scope': 'ore_node',
                        'estimate_state': 'author_estimate',
                        'resource_estimate_id': 'r1',
                    },
                    'retrieval_note': 'n',
                }
                for field, entity_id in zip(fields, entity_ids, strict=True)
            ],
        }

    ids = ['deposit-a'] * 4 + ['deposit-b'] * 2
    whole = {**batch, 'fields': row_fields}
    mixed = [v for v in validate_owner_envelope(whole, envelope(row_fields, ids)) if 'mixes entity_id' in v]
    assert mixed, 'the check catches the disagreement while the row is whole'

    first = {**batch, 'fields': row_fields[:4]}
    second = {**batch, 'fields': row_fields[4:]}
    per_chunk = [
        *validate_owner_envelope(first, envelope(row_fields[:4], ids[:4])),
        *validate_owner_envelope(second, envelope(row_fields[4:], ids[4:])),
    ]
    assert not [v for v in per_chunk if 'mixes' in v]


def test_lowering_the_size_costs_owner_calls_in_proportion():
    """The resource batch takes 5, 7 and 10 owner calls at chunk sizes 18, 12 and 8."""
    batch = _resource_batch()
    counts = {n: len(partition_owner_batch(batch, max_fields=n)) for n in (18, 12, 8)}

    assert counts == {18: 5, 12: 7, 8: 10}
