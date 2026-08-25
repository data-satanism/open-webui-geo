"""A-88. The GIS project id reached the knowledge-base search plan as a term.

`build_knowledge_search_plan` put `_search_aliases(profile.project_id)` into
the direct tier unconditionally. On the Lekyn contour that id is
`lekyn_new_data` — a geodatabase handle that appears in no geological report
ever written — and the specialist read it as the name of a corpus. Its own
locators say so: «lekyn_new_data: no direct plan found», «KB: lekyn_new_data,
search for 'Геохимия' + 'план'».

Rows 68-76 went out empty on that, 42 cells, while the ГРР plan document sat
in the knowledge base and seven other batches cited it 131 times.

The id is not always a handle, which is why it cannot simply be dropped:
`Нияюская_площадь` is the object's name with an underscore, and documents are
named that way.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    flag_invalid_scope_conclusions,
)
from open_webui.services.project_evidence.proposals import (
    build_knowledge_search_plan,
    collection_scope_problems,
)
from open_webui.services.project_evidence.proposals import (
    GisObjectSearchProfile,
)

COLLECTIONS = [
    '2a0b4bcd-aa58-452e-a01d-e90cd16a3229',
    '59698dd0-d6c0-45a6-a5b0-96f3fd8bb680',
]


def profile(object_name: str, project_id: str) -> GisObjectSearchProfile:
    return GisObjectSearchProfile(
        object_name=object_name,
        project_id=project_id,
        profile_status='ready',
        location_terms=(),
        commodity_terms=(),
        deposit_type_terms=(),
        geology_terms=(),
        evidence=(),
    )


def direct_terms(plan) -> list[str]:
    return plan['tiers'][0]['query_terms']


def test_a_technical_project_handle_never_becomes_a_query_term():
    """The defect itself."""
    plan = build_knowledge_search_plan(
        profile('Лекын_Талбейское', 'lekyn_new_data'), collections=COLLECTIONS
    )

    assert not [term for term in direct_terms(plan) if 'lekyn_new_data' in term]
    assert not [term for term in direct_terms(plan) if 'new_data' in term]


def test_the_object_name_is_still_searched():
    """Removing the handle must not remove the search."""
    plan = build_knowledge_search_plan(
        profile('Лекын_Талбейское', 'lekyn_new_data'), collections=COLLECTIONS
    )

    assert 'Лекын Талбейское' in direct_terms(plan)


def test_a_project_id_that_is_the_name_respelled_is_kept():
    """`Нияюская_площадь` is a real alias — documents are named that way — and
    the underscore form is not among the object name's own variants."""
    plan = build_knowledge_search_plan(
        profile('Нияюская площадь', 'Нияюская_площадь'), collections=COLLECTIONS
    )

    assert 'Нияюская_площадь' in direct_terms(plan)


def test_a_neighbouring_object_sharing_a_leading_word_is_not_admitted():
    """The variant test is exact rather than fuzzy. A project id that merely
    starts the same way is a different object, and admitting it would put a
    neighbour's name into this object's direct terms."""
    plan = build_knowledge_search_plan(
        profile('Нияюская площадь', 'Нияюская_южная_площадь'), collections=COLLECTIONS
    )

    assert not [term for term in direct_terms(plan) if 'южная' in term.casefold()]


def test_the_plan_states_where_to_search_and_what_is_not_a_corpus():
    plan = build_knowledge_search_plan(
        profile('Лекын_Талбейское', 'lekyn_new_data'), collections=COLLECTIONS
    )
    scope = plan['corpus_scope']

    assert scope['collections'] == COLLECTIONS
    assert scope['addressed_by'] == 'collection_id'
    assert scope['not_a_corpus'] == ['lekyn_new_data']
    assert scope['status'] == 'configured'


def test_a_scope_holding_a_project_id_is_reported_invalid():
    """If the routes ever conflate a GIS source with a knowledge-base one, the
    scope says so rather than returning nothing."""
    plan = build_knowledge_search_plan(
        profile('Лекын_Талбейское', 'lekyn_new_data'),
        collections=[*COLLECTIONS, 'lekyn_new_data'],
    )

    assert plan['corpus_scope']['status'] == 'invalid'
    assert plan['corpus_scope']['invalid_entries'] == ['lekyn_new_data']


def test_collection_scope_problems_accepts_only_collection_ids():
    assert collection_scope_problems(COLLECTIONS) == []
    assert collection_scope_problems(['lekyn_new_data']) == ['lekyn_new_data']
    assert collection_scope_problems(['Канавы_ГСК']) == ['Канавы_ГСК']
    assert collection_scope_problems([]) == []


def test_the_plan_tells_the_specialist_what_to_report_when_the_scope_is_empty():
    plan = build_knowledge_search_plan(
        profile('Лекын_Талбейское', 'lekyn_new_data'), collections=COLLECTIONS
    )
    rules = ' '.join(plan['decision_rules'])

    assert 'invalid_scope' in rules
    assert 'not a corpus' in rules


def test_a_not_found_reached_through_a_non_corpus_is_not_a_finding():
    """The conclusion path. «Searched, found nothing, therefore no document»
    is a specialist accepting an empty result from a malformed scope."""
    envelope = {
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

    repaired, notes = flag_invalid_scope_conclusions(
        envelope, non_corpus_names=['lekyn_new_data']
    )

    assert len(notes) == 1
    patch = repaired['patches'][0]
    assert patch['status'] == 'requires_expert_review'
    assert patch['source_locator']['policy'] == 'invalid_scope'
    assert 'поиск не состоялся' in patch['source_locator']['selection_trace']


def test_a_not_found_from_a_real_collection_is_left_alone():
    """A genuine miss inside a real corpus is a finding, and turning it into a
    review item would bury the cells where the search never happened."""
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r070.a02',
                'status': 'not_found',
                'value': None,
                'source_locator': {
                    'page_or_chunk_or_layer_or_feature_or_query': (
                        f'KB: {COLLECTIONS[0]}, запрос «объёмы бурения»'
                    )
                },
            }
        ]
    }

    repaired, notes = flag_invalid_scope_conclusions(
        envelope, non_corpus_names=['lekyn_new_data']
    )

    assert notes == []
    assert repaired['patches'][0]['status'] == 'not_found'


def test_a_filled_cell_is_never_touched():
    """A cell answered from somewhere is answered, whatever the scope said."""
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r070.a02',
                'status': 'filled',
                'value': '2000 м',
                'source_locator': {
                    'page_or_chunk_or_layer_or_feature_or_query': 'lekyn_new_data'
                },
            }
        ]
    }

    repaired, notes = flag_invalid_scope_conclusions(
        envelope, non_corpus_names=['lekyn_new_data']
    )

    assert notes == []
    assert repaired['patches'][0]['status'] == 'filled'


def test_nothing_happens_when_there_is_no_non_corpus_name_to_look_for():
    envelope = {
        'patches': [
            {'field_key': 'x', 'status': 'not_found', 'source_locator': {'q': 'y'}}
        ]
    }

    repaired, notes = flag_invalid_scope_conclusions(envelope, non_corpus_names=[])

    assert notes == []
    assert repaired['patches'][0]['status'] == 'not_found'
