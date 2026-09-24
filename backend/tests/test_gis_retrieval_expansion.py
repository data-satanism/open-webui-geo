"""`gis_retrieval_expansion` records which GIS absences sent the run searching elsewhere
and whether the search answered."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    gis_retrieval_expansion,
)


def trace(role: str, code: str, *, accepted: bool = False) -> dict:
    return {'semantic_role': role, 'rejection_reason': code, 'accepted': accepted}


def cell(row: int, *, code: str, status: str = 'not_found', query: str | None = None) -> dict:
    locator: dict = {'absence_code': code}
    if query:
        locator['page_or_chunk_or_layer_or_feature_or_query'] = query
    return {
        'field_key': f'geotizer_object.v1.r{row:03d}.a01',
        'status': status,
        'source_locator': locator,
    }


def test_a_missing_layer_that_drove_a_search_that_found_nothing():
    """A missing layer whose cell was searched on the web and not answered is recorded
    as searched and unanswered."""
    result = gis_retrieval_expansion(
        [trace('port', 'layer_not_found')],
        [cell(82, code='layer_not_found', query="web_search, запрос 'порт'")],
    )

    assert len(result) == 1
    entry = result[0]
    assert entry['semantic_roles'] == ['port']
    assert entry['blocked_field_keys'] == ['geotizer_object.v1.r082.a01']
    assert entry['searched_elsewhere_field_keys'] == ['geotizer_object.v1.r082.a01']
    assert entry['answered_elsewhere_field_keys'] == []


def test_a_search_that_answered_is_a_different_fact_from_one_that_did_not():
    """Blocked, searched-elsewhere and answered-elsewhere cells are listed separately."""
    result = gis_retrieval_expansion(
        [trace('port', 'layer_not_found')],
        [
            cell(80, code='layer_not_found', status='filled', query='web_search, ГОК'),
            cell(81, code='layer_not_found', query='web_search, энергоузел'),
            cell(82, code='layer_not_found'),
        ],
    )

    entry = result[0]
    assert entry['blocked_field_keys'] == [
        'geotizer_object.v1.r080.a01',
        'geotizer_object.v1.r081.a01',
        'geotizer_object.v1.r082.a01',
    ]
    assert entry['searched_elsewhere_field_keys'] == [
        'geotizer_object.v1.r080.a01',
        'geotizer_object.v1.r081.a01',
    ]
    assert entry['answered_elsewhere_field_keys'] == ['geotizer_object.v1.r080.a01']


def test_the_two_sides_join_on_the_code_and_need_no_role_table():
    """Trace entries and cells join on the absence code, with no role-to-row table."""
    result = gis_retrieval_expansion(
        [
            trace('licence', 'only_the_source_feature_in_layer'),
            trace('subsoil_user', 'only_the_source_feature_in_layer'),
        ],
        [cell(86, code='only_the_source_feature_in_layer', query='web_search, лицензии')],
    )

    assert result[0]['semantic_roles'] == ['licence', 'subsoil_user']


def test_an_accepted_role_is_not_an_absence():
    """An accepted trace entry produces no absence entry."""
    result = gis_retrieval_expansion(
        [trace('road', '', accepted=True), trace('port', 'layer_not_found')],
        [cell(82, code='layer_not_found', query='web_search, порт')],
    )

    assert [entry['absence_code'] for entry in result] == ['layer_not_found']


def test_a_url_and_a_web_prefix_count_as_looking_elsewhere():
    """A `web_search` prefix, a `Web:` prefix and a URL each count as searching
    elsewhere."""
    for query in ('web_search, запрос x', 'Web: metaldaily.ru', 'https://vsluh.ru/a'):
        result = gis_retrieval_expansion(
            [trace('port', 'layer_not_found')],
            [cell(82, code='layer_not_found', query=query)],
        )

        assert result[0]['searched_elsewhere_field_keys'] == [
            'geotizer_object.v1.r082.a01'
        ], query


def test_a_kb_locator_is_not_looking_elsewhere():
    """A knowledge-base locator does not count as searching elsewhere."""
    result = gis_retrieval_expansion(
        [trace('port', 'layer_not_found')],
        [cell(82, code='layer_not_found', query='Document ID: 8b407795, стр. 3')],
    )

    assert result[0]['searched_elsewhere_field_keys'] == []


def test_a_run_with_no_absences_produces_nothing():
    assert gis_retrieval_expansion([trace('road', '', accepted=True)], []) == []


def test_a_cell_with_no_locator_is_skipped_rather_than_crashing():
    result = gis_retrieval_expansion(
        [trace('port', 'layer_not_found')],
        [{'field_key': 'geotizer_object.v1.r082.a01', 'status': 'not_found'}],
    )

    assert result[0]['blocked_field_keys'] == []
