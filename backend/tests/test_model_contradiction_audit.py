"""Tests for `flag_model_contradictions`: a phenomenon row cannot be wholly
empty while the card asserts a model that entails it."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    flag_model_contradictions,
)


def patch(row: int, attribute: int, *, status: str, value=None) -> dict:
    return {
        'field_key': f'geotizer_object.v1.r{row:03d}.a{attribute:02d}',
        'status': status,
        'value': value,
        'unit': None,
        'value_origin': 'direct' if status == 'filled' else None,
    }


def porphyry_run(phenomenon_status: str = 'not_found', cells: int = 9) -> dict:
    return {
        'patches': [
            patch(16, 4, status='filled', value='медно-порфировая'),
            patch(18, 2, status='filled', value='медно-порфировое'),
            patch(
                27,
                2,
                status='filled',
                value='Медно-порфировая модель рудообразования, связанная с '
                'интрузиями Кызыгейского комплекса (вендская система)',
            ),
            *[
                patch(26, index, status=phenomenon_status)
                for index in range(1, cells + 1)
            ],
        ]
    }


def r026(envelope: dict) -> list[dict]:
    return [
        item
        for item in envelope['patches']
        if item['field_key'].startswith('geotizer_object.v1.r026.')
    ]


def test_the_real_contradiction_is_flagged_and_names_both_sides():
    envelope, notes = flag_model_contradictions(porphyry_run())

    assert len(notes) == 1
    assert 'медно-порфировая модель' in notes[0]
    assert '16, 18, 27' in notes[0]
    assert all(item['status'] == 'requires_expert_review' for item in r026(envelope))


def test_no_value_is_invented_for_the_empty_row():
    """Flagged phenomenon cells get no value, unit or origin, and their locator
    names the policy."""
    envelope, _ = flag_model_contradictions(porphyry_run())

    for item in r026(envelope):
        assert item['value'] is None
        assert item['unit'] is None
        assert item['value_origin'] is None
        assert item['source_locator']['policy'] == 'model_entails_phenomenon'
        assert 'Значение не подставлено' in item['source_locator']['selection_trace']


def test_a_partly_answered_phenomenon_row_is_not_a_contradiction():
    """A partly answered phenomenon row is not flagged."""
    envelope = porphyry_run()
    envelope['patches'][3] = patch(26, 1, status='filled', value='серицитизация')

    repaired, notes = flag_model_contradictions(envelope)

    assert notes == []
    assert [item['status'] for item in r026(repaired)] == [
        'filled',
        *['not_found'] * 8,
    ]


def test_not_applicable_counts_as_empty_just_as_not_found_does():
    """`not_applicable` cells count as empty, as `not_found` cells do."""
    _, notes = flag_model_contradictions(porphyry_run('not_applicable'))

    assert len(notes) == 1


def test_no_model_no_flag():
    """A card asserting no model flags nothing."""
    envelope = porphyry_run()
    envelope['patches'] = [
        item
        for item in envelope['patches']
        if not item['field_key'].startswith(
            ('geotizer_object.v1.r016.', 'geotizer_object.v1.r018.', 'geotizer_object.v1.r027.')
        )
    ]

    repaired, notes = flag_model_contradictions(envelope)

    assert notes == []
    assert all(item['status'] == 'not_found' for item in r026(repaired))


def test_the_stem_matches_across_a_hyphen_and_not_inside_another_word():
    """The model stem matches across a hyphen and not inside another word."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        MODEL_ENTAILED_PHENOMENA,
    )

    pattern = MODEL_ENTAILED_PHENOMENA[0]['model_pattern']

    assert pattern.search('медно-порфировое')
    assert pattern.search('Медно-порфировая модель')
    assert pattern.search('порфировая')
    assert not pattern.search('непорфировое')


def test_the_model_row_must_be_filled_to_count_as_stated():
    """A model row that is not filled asserts no model."""
    envelope = porphyry_run()
    for item in envelope['patches']:
        if not item['field_key'].startswith('geotizer_object.v1.r026.'):
            item['status'] = 'not_found'
            item['value_origin'] = None

    _, notes = flag_model_contradictions(envelope)

    assert notes == []


def test_the_envelope_is_copied_and_the_input_is_left_alone():
    envelope = porphyry_run()

    repaired, _ = flag_model_contradictions(envelope)

    assert repaired is not envelope
    assert all(item['status'] == 'not_found' for item in r026(envelope))
