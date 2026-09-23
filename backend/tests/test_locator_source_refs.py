"""A source ref recorded inside a locator must name a source in the inventory."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import render_run_notes
from open_webui.services.artifacts.geotizer.owner_envelope import (
    register_locator_only_sources,
)
from open_webui.services.artifacts.geotizer.validation import (
    _locator_ref_violations,
    locator_source_refs,
)

BATCH = {
    'batch_id': 'KB-GRR-FACTORS',
    'producer': 'kb',
    'policy_version': 'geotizer_assignments.v3',
    'template_version': 'geotizer_object.v1',
    'owner_chunk': {'index': 1, 'total': 3},
    'fields': [{'field_key': 'geotizer_object.v1.r068.a05', 'row_id': 68}],
}


def patch(locator):
    return {
        'field_key': 'geotizer_object.v1.r068.a05',
        'value': None,
        'status': 'not_found',
        'source_refs': ['registered'],
        'source_locator': locator,
    }


def envelope(*patches):
    return {
        'source_inventory': [
            {'source_id': 'registered', 'source_type': 'web', 'title': 'Статья'}
        ],
        'patches': list(patches),
    }


def test_the_walk_finds_a_ref_wherever_it_sits():
    """`locator_source_refs` finds a ref at any depth of the locator."""
    locator = {
        'negative_findings': [{'source_ref': 'a', 'locator': {}}],
        'candidates': [{'source_ref': 'b'}, {'locator': {'source_ref': 'c'}}],
        'spatial_divergence': {'measured': [{'source_ref': 'd'}], 'read': [{'source_ref': 'e'}]},
        'source_refs': ['f'],
        'nested': [[{'source_ref': 'g'}]],
    }

    assert sorted(locator_source_refs(locator)) == ['a', 'b', 'c', 'd', 'e', 'f', 'g']


def test_a_locator_that_is_not_a_mapping_yields_nothing():
    assert locator_source_refs('стр. 12') == []
    assert locator_source_refs(None) == []


def test_an_unregistered_nested_ref_gets_a_source_that_says_so():
    """An unregistered ref inside a locator is registered as a `derived` source that
    says who cited it and where."""
    given = envelope(
        patch(
            {
                'negative_findings': [
                    {
                        'source_ref': 'vsluh-2007-07-03__geotizer_object.v1.r068.a05',
                        'value': 'не найден',
                    }
                ]
            }
        )
    )
    repaired, notes = register_locator_only_sources(BATCH, given, run_id='run-1')

    by_id = {source['source_id']: source for source in repaired['source_inventory']}
    added = by_id['vsluh-2007-07-03__geotizer_object.v1.r068.a05']

    assert added['source_type'] == 'derived'
    assert 'without registering it' in added['title']
    assert 'field_key=geotizer_object.v1.r068.a05' in added['locator']
    assert 'vsluh-2007-07-03' in render_run_notes(notes)[0]

    assert _locator_ref_violations(0, repaired['patches'][0], set(by_id)) == []


def test_a_ref_that_is_already_registered_is_left_alone():
    given = envelope(patch({'candidates': [{'source_ref': 'registered'}]}))
    repaired, notes = register_locator_only_sources(BATCH, given, run_id='run-1')

    assert notes == []
    assert len(repaired['source_inventory']) == 1


def test_one_source_for_a_ref_cited_by_several_cells():
    given = envelope(
        patch({'candidates': [{'source_ref': 'ghost'}]}),
        {**patch({'negative_findings': [{'source_ref': 'ghost'}]}), 'field_key': 'geotizer_object.v1.r069.a05'},
    )
    repaired, notes = register_locator_only_sources(BATCH, given, run_id='run-1')

    ids = [source['source_id'] for source in repaired['source_inventory']]
    assert ids.count('ghost') == 1
    assert len(notes) == 1


def test_the_contract_still_refuses_a_ref_nothing_registered():
    """`_locator_ref_violations` refuses a locator ref missing from the inventory."""
    violations = _locator_ref_violations(
        4,
        patch({'candidates': [{'source_ref': 'ghost'}, {'source_ref': 'registered'}]}),
        {'registered'},
    )

    assert violations == [
        "patches[4] source_locator records unregistered source_refs: ['ghost']; "
        'add them to source_inventory or remove the reference'
    ]
