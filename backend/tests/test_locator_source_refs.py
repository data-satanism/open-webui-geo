"""A ref recorded inside a locator must name a source the state holds.

`source_refs` on the patch has been checked against the inventory since the
contract existed. The refs *inside* the locator never were — and they are the
ones a reader follows to see the losing side of a conflict, or what a negative
search actually consulted.

Run `6e68eeec` is the measurement: eight refs across six cells resolved against
nothing. «vsluh-2007-07-03__geotizer_object.v1.r068.a05» on three
`negative_findings`, two `candidates` on r081.a01, two on r087.a01, one
`negative_findings` on r007.a01. None was in the chunk's inventory, so
`merge_owner_envelopes` had no rename for it and it reached the finalized state
naming a source that does not exist. `dangling_source_refs` in the
render-readiness audit caught it, and a backstop firing means the gate upstream
is missing.
"""

from __future__ import annotations

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


# ------------------------------------------------------------- the walk


def test_the_walk_finds_a_ref_wherever_it_sits():
    """Three shapes exist today; walking the structure cannot fall behind the
    next one."""
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


# --------------------------------------------------------- the repair


def test_an_unregistered_nested_ref_gets_a_source_that_says_so():
    """Run `6e68eeec`'s r068.a05, reduced."""
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
    # What is known and no more: who cited it, where, and that it was not
    # registered. Dropping the ref would lose the id, which is the one thing
    # that says what the owner was pointing at.
    assert 'without registering it' in added['title']
    assert 'field_key=geotizer_object.v1.r068.a05' in added['locator']
    assert notes and 'vsluh-2007-07-03' in notes[0]

    # And the contract is satisfied afterwards, which is the point.
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


# ------------------------------------------------------ the invariant


def test_the_contract_still_refuses_a_ref_nothing_registered():
    """Kept as the invariant the repair has to satisfy, not as the rejection.

    The repair runs before validation, so in the live pipeline this never
    fires. It fires if a later pass writes a ref after the repair, which is
    exactly the case nothing else would notice.
    """
    violations = _locator_ref_violations(
        4,
        patch({'candidates': [{'source_ref': 'ghost'}, {'source_ref': 'registered'}]}),
        {'registered'},
    )

    assert violations == [
        "patches[4] source_locator records unregistered source_refs: ['ghost']; "
        'add them to source_inventory or remove the reference'
    ]
