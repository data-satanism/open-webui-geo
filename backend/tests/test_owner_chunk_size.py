"""What lowering `MAX_OWNER_FIELDS_PER_CALL` costs, measured rather than assumed.

Run `6056e157` failed five owner chunks, four of them full 18-field chunks,
and the brief that prompted this proposed measuring 18 / 12 / 8.

The run does not support the chunk-size hypothesis at the resolution it
offers: 4 of the 15 full KB chunks failed and 1 of the 5 partial ones did,
and the single failing partial chunk had 16 fields. There is no chunk below
16 in this run that both used the KB specialist and failed, so the comparison
that would settle it was never run.

What can be settled from here is the cost, and one hazard that has nothing to
do with the model: `partition_owner_batch` is a fixed-width slice with no row
awareness, while the row-consistency rules only see the patches inside one
chunk. Every resource row in the teaser is exactly six fields wide, so 18 and
12 divide cleanly and 8 does not -- at 8 a resource row straddles a chunk
boundary and its consistency check silently stops running.

Measured over this run's 351 fields:

    max_fields   owner calls   resource rows split   GRR rows split
            18            25                     0                0
            12            33                     0                0
             8            49                     6                4
"""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import partition_owner_batch
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope
from open_webui.services.artifacts.geotizer.workflow import MAX_OWNER_FIELDS_PER_CALL

#: Every teaser resource row (44-56) carries exactly this many attributes, and
#: the six are contiguous in batch order. It is the number a chunk size has to
#: divide.
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
    """The guard the measurement asks for.

    Nothing in `partition_owner_batch` knows what a row is, so this holds by
    arithmetic and not by construction: 18 and 12 are multiples of six and 8
    is not. Lowering the constant to a number that is not should fail the
    build rather than quietly disable a rule.
    """
    assert MAX_OWNER_FIELDS_PER_CALL % RESOURCE_ROW_WIDTH == 0
    assert _rows_split(_resource_batch(), MAX_OWNER_FIELDS_PER_CALL) == set()


@pytest.mark.parametrize(('max_fields', 'splits'), [(18, False), (12, False), (8, True)])
def test_the_three_proposed_sizes_divide_the_row_differently(max_fields, splits):
    """18 and 12 are safe on this arithmetic; 8 is not, and the brief named it."""
    assert bool(_rows_split(_resource_batch(), max_fields)) is splits


def test_a_split_row_loses_the_consistency_check_that_would_have_caught_it():
    """The consequence, not just the split.

    `_resource_row_consistency_violations` compares the qualifiers of every
    `filled` patch on the same row. It only ever sees one chunk. Two halves of
    one row that disagree about `entity_id` -- two different deposits reported
    as one row's estimate -- are caught while the row is whole and are not
    caught once the row is cut in two, and nothing reports that the check was
    skipped.
    """
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

    # Now the same six patches, cut where max_fields=8 cuts them. Chunk 1 holds
    # this row's first four fields (after the previous row's four); chunk 2
    # holds the last two.
    first = {**batch, 'fields': row_fields[:4]}
    second = {**batch, 'fields': row_fields[4:]}
    per_chunk = [
        *validate_owner_envelope(first, envelope(row_fields[:4], ids[:4])),
        *validate_owner_envelope(second, envelope(row_fields[4:], ids[4:])),
    ]
    assert not [v for v in per_chunk if 'mixes' in v]


def test_lowering_the_size_costs_owner_calls_in_proportion():
    """25 -> 33 -> 49 across this run's eight batches. Each call is a full
    specialist round, and the empty responses this was meant to address cost
    one each."""
    batch = _resource_batch()
    counts = {n: len(partition_owner_batch(batch, max_fields=n)) for n in (18, 12, 8)}

    assert counts == {18: 5, 12: 7, 8: 10}
