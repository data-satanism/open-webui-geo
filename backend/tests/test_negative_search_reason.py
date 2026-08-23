"""A cell that reads «не найдено» has to say why.

GT-POLICY-01. Run `d0a464be` shipped 100 `not_found` cells of which **59 carry
an empty `retrieval_note`** — 40 from `KB-STUDY`, 16 from `KB-RESOURCE-TECH`, 3
from `KB-LIC-LEGAL`. The card renders the note, so the reader sees an empty
cell and no reason at all.

The reason was never missing. All 59 carry a locator saying where the search
went, and three also carry a `negative_findings` entry saying what came back.
Same shape as the run log before it had a carrier: the fact is in the state and
not in the field anything reads.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    state_the_negative_search,
)

BATCH = {
    'batch_id': 'KB-STUDY',
    'producer': 'kb',
    'policy_version': 'geotizer_assignments.v3',
    'template_version': 'geotizer_object.v1',
    'fields': [{'field_key': 'geotizer_object.v1.r031.a04', 'row_id': 31}],
}


def patch(**overrides):
    return {
        'field_key': 'geotizer_object.v1.r031.a04',
        'value': None,
        'status': 'not_found',
        'source_refs': ['derived-negative-kb-study-part-2-attempt-1'],
        'source_locator': {
            'page_or_chunk_or_layer_or_feature_or_query': (
                'searched: lekyn_new_data, Lekyn-Talbeyskaya, Полярный Урал'
            ),
            'relation_to_object': 'direct',
        },
        **overrides,
    }


def note_of(envelope):
    return envelope['patches'][0].get('retrieval_note')


def test_the_reason_is_taken_from_the_locator():
    envelope, notes = state_the_negative_search(BATCH, {'patches': [patch()]})

    assert note_of(envelope) == (
        'Значение не найдено. Где искали: searched: lekyn_new_data, '
        'Lekyn-Talbeyskaya, Полярный Урал.'
    )
    assert notes and 'geotizer_object.v1.r031.a04' in notes[0]


def test_a_negative_finding_is_added_to_the_reason():
    """Three of the 59 also say what came back, not only where it looked."""
    locator = {
        **patch()['source_locator'],
        'negative_findings': [
            {'locator': {'page_chunk_section': 'no date found'}, 'value': 'не найден'},
            {'locator': {'page_chunk_section': 'no date found'}, 'value': 'не найден'},
            {'locator': {'page_chunk_section': 'no number found'}, 'value': 'не найден'},
        ],
    }
    envelope, _ = state_the_negative_search(
        BATCH, {'patches': [patch(source_locator=locator)]}
    )

    assert note_of(envelope).endswith(
        'Результат поиска: no date found; no number found.'
    )


def test_a_note_the_owner_wrote_is_left_alone():
    written = patch(retrieval_note='Раздел 3.6 прочитан, объёмы не приведены.')
    envelope, notes = state_the_negative_search(BATCH, {'patches': [written]})

    assert note_of(envelope) == 'Раздел 3.6 прочитан, объёмы не приведены.'
    assert notes == []


def test_nothing_is_composed_where_the_patch_says_nothing():
    """A sentence whose only content is that there is no content is not a
    reason, and would make an unrecorded search indistinguishable from a
    recorded one."""
    silent = patch(source_locator={'relation_to_object': 'direct'})
    envelope, notes = state_the_negative_search(BATCH, {'patches': [silent]})

    assert note_of(envelope) is None
    assert notes == []


def test_a_filled_cell_is_not_touched():
    filled = patch(status='filled', value='1:50 000', value_origin='direct')
    envelope, notes = state_the_negative_search(BATCH, {'patches': [filled]})

    assert note_of(envelope) is None
    assert notes == []
