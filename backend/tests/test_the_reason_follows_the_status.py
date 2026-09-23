"""Tests that a reason projected for one status does not outlive it, and that
`completeness_lines` reads the strict/basic pair only from
`audit.completeness`."""

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
    """`state_the_negative_search` writes the not-found sentence and stamps the
    status it was written for."""
    projected, notes = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )

    assert len(notes) == 1
    patch = projected['patches'][0]
    assert patch['retrieval_note'].startswith('Значение не найдено.')
    assert patch['source_locator'][PROJECTED_REASON_STATUS_KEY] == 'not_found'


def test_invalid_scope_replaces_the_reason_it_found():
    """`flag_invalid_scope_conclusions` replaces the projected reason with
    `INVALID_SCOPE_REASON_RU` and keeps its trace."""
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
    assert patch['source_locator']['policy'] == 'invalid_scope'
    assert 'поиск не состоялся' in patch['source_locator']['selection_trace']
    assert len(notes) == 1


def test_the_stamp_follows_the_status_invalid_scope_set():
    """After `flag_invalid_scope_conclusions`, `retire_stale_projected_reasons`
    keeps the new reason."""
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
    """A projected reason whose stamped status no longer matches the patch is
    cleared, with a note."""
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
    """A reason without the projection stamp is never retired."""
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
    """A projected reason whose stamp matches the status is left alone."""
    projected, _ = state_the_negative_search(
        BATCH, _empty_cell_searched_through_a_non_corpus()
    )

    settled, notes = retire_stale_projected_reasons(projected)

    assert notes == []
    assert settled['patches'][0]['retrieval_note'].startswith('Значение не найдено.')


from open_webui.services.artifacts.geotizer.terminal import (  # noqa: E402
    completeness_lines,
)


REAL_ENVELOPE = {
    'counts': {
        'pending': 0, 'filled': 118, 'not_found': 183, 'not_applicable': 0,
        'conflicted': 13, 'requires_expert_review': 37,
        'agent_contract_failed': 0,
    },
    'audit': {
        'completeness': {
            'required': 351, 'filled': 118, 'conflicted': 13,
            'requires_expert_review': 37, 'not_found': 183,
            'strict': {'filled': 118, 'of': 351},
            'basic': {'filled': 166, 'of': 351},
        }
    },
}


def test_the_writer_prints_both_figures_when_it_is_handed_them():
    """`completeness_lines` prints both the strict and the basic figure from
    `audit.completeness`."""
    text = completeness_lines(REAL_ENVELOPE)

    assert '118 из 351 (33.6%, строго)' in text
    assert '166 из 351 (47.3%, с учётом расхождений)' in text


def test_the_pair_is_read_from_the_audit_and_not_from_the_status_counts():
    """Without `audit.completeness` the pair is not rendered from the status
    counts."""
    text = completeness_lines({'counts': REAL_ENVELOPE['counts']})

    assert '- Заполнено: 118' in text
    assert 'строго' not in text


def test_neither_figure_is_invented_when_the_service_did_not_send_the_pair():
    """Without the pair only the single filled figure is printed."""
    text = completeness_lines({
        'counts': {'filled': 118, 'conflicted': 13, 'not_found': 183}
    })

    assert '- Заполнено: 118' in text
    assert 'строго' not in text
    assert 'с учётом расхождений' not in text
