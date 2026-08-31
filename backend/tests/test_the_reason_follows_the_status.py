"""A reason composed for one status must not outlive it.

Run `803ce041`. `flag_invalid_scope_conclusions` moved 40 cells out of
`not_found` and into `requires_expert_review`, which is A-88's rule working as
built — a search that never opened a corpus has found nothing about the
corpus. 28 of those 40 went out still reading «Значение не найдено».

That sentence is `state_the_negative_search`'s projection, and it is composed
against `not_found`'s vocabulary: it asserts the search ran and came back
empty. On an `invalid_scope` cell it asserts the opposite of the finding. A
reviewer reads the sentence before the label, so the cell told them the
knowledge base had been consulted and had no answer — the exact claim the rule
exists to withdraw.

Two guards here, because there are two failures. The first is the 40 cells:
`flag_invalid_scope_conclusions` writes its own reason now. The second is the
shape — nine passes in `owner_envelope` move a status after the projection has
run, and any of them can strand it.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    INVALID_SCOPE_REASON_RU,
    PROJECTED_REASON_STATUS_KEY,
    flag_invalid_scope_conclusions,
    retire_stale_projected_reasons,
    state_the_negative_search,
)

BATCH = {'batch_id': 'KB-STUDY', 'fields': [{'field_key': 'geotizer_object.v1.r070.a02'}]}


def _empty_cell_searched_through_a_non_corpus() -> dict:
    return {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r070.a02',
                'status': 'not_found',
                'value': None,
                'source_locator': {
                    'page_or_chunk_or_layer_or_feature_or_query': (
                        'lekyn_new_data: no direct plan found'
                    )
                },
            }
        ]
    }


def test_the_projection_writes_the_not_found_sentence_first():
    """The precondition. Without this the rest proves nothing."""
    projected, notes = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )

    assert len(notes) == 1
    patch = projected['patches'][0]
    assert patch['retrieval_note'].startswith('Значение не найдено.')
    assert patch['source_locator'][PROJECTED_REASON_STATUS_KEY] == 'not_found'


def test_invalid_scope_replaces_the_reason_it_found():
    """The 40 cells. The status moved, so the sentence moves with it."""
    projected, _ = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )
    repaired, notes = flag_invalid_scope_conclusions(
        projected, non_corpus_names=['lekyn_new_data']
    )

    patch = repaired['patches'][0]
    assert patch['status'] == 'requires_expert_review'
    assert patch['retrieval_note'] == INVALID_SCOPE_REASON_RU
    assert 'Значение не найдено' not in patch['retrieval_note']
    assert 'База знаний не открывалась' in patch['retrieval_note']
    # The long trace stays where it was: it explains the repair, and the
    # reason states the finding. Removing either would lose one of them.
    assert patch['source_locator']['policy'] == 'invalid_scope'
    assert 'поиск не состоялся' in patch['source_locator']['selection_trace']
    assert len(notes) == 1


def test_the_stamp_follows_the_status_invalid_scope_set():
    """So the card-wide guard does not then retire the reason just written."""
    projected, _ = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )
    repaired, _ = flag_invalid_scope_conclusions(
        projected, non_corpus_names=['lekyn_new_data']
    )

    settled, notes = retire_stale_projected_reasons(repaired)

    assert notes == []
    assert settled['patches'][0]['retrieval_note'] == INVALID_SCOPE_REASON_RU


def test_a_reason_stranded_by_any_other_pass_is_retired():
    """The shape, not the instance. Nine passes can move a status; this one
    stands for all of them — a projection written for `not_found` on a patch
    that no longer is."""
    projected, _ = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )
    stranded = {
        'patches': [
            {**projected['patches'][0], 'status': 'conflicted'},
        ]
    }

    settled, notes = retire_stale_projected_reasons(stranded)

    patch = settled['patches'][0]
    assert patch['retrieval_note'] == ''
    assert PROJECTED_REASON_STATUS_KEY not in patch['source_locator']
    assert len(notes) == 1
    assert 'написанную для прежнего' in notes[0]['template']


def test_a_reason_the_owner_wrote_is_never_retired():
    """Only a projection carries the stamp. An owner's own sentence is
    evidence, and this pass has no standing to remove it."""
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r070.a02',
                'status': 'requires_expert_review',
                'value': None,
                'retrieval_note': 'Документ найден, но противоречит приложению.',
                'source_locator': {
                    'page_or_chunk_or_layer_or_feature_or_query': 'KB: отчёт, с. 12'
                },
            }
        ]
    }

    settled, notes = retire_stale_projected_reasons(envelope)

    assert notes == []
    assert settled['patches'][0]['retrieval_note'] == (
        'Документ найден, но противоречит приложению.'
    )


def test_a_projection_still_matching_its_status_is_left_alone():
    """The guard fires on disagreement, not on the presence of a stamp."""
    projected, _ = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )

    settled, notes = retire_stale_projected_reasons(projected)

    assert notes == []
    assert settled['patches'][0]['retrieval_note'].startswith('Значение не найдено.')
