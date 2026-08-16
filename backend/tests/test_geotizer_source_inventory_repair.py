"""`normalize_source_inventory`, against the Workspace Tool it was ported from.

Register A-04, and the reason the merge could not simply take this
repository's side: the repaired version was in the production Tool and the
broken one here. `merge_owner_envelopes` copies each source entry through and
only re-namespaces the id, and the local validator only ever harvested
`source_id` -- so an owner that serialized its contributor evidence as sources,
carrying `producer`, `source_domain` and `source_locator` instead of
`source_type` and `title`, passed every local check and was rejected with HTTP
422 at `submit_batch`, after the whole batch had been built.

The cases that matter are the ones a rewrite gets subtly wrong:

  the repair keeps the source rather than dropping it, because the owner had
  the evidence and only wrote it under the wrong schema;

  deduplication compares content and not `source_id`, because the id carries
  chunk and attempt suffixes that make identical entries look distinct;

  and `source_refs` are remapped onto the survivor, because merging two entries
  and leaving a patch pointing at the one that went is a dangling reference the
  submission would reject for a second reason.

Every one is also asserted against the reference implementation in
`GMM/operations/workspace-exports/geoteaser.py`, executed rather than read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer.owner_envelope import (  # noqa: E402
    normalize_source_inventory,
)

EXPORT = REPO_ROOT.parent / 'GMM/operations/workspace-exports/geoteaser.py'


def _envelope(sources, patches=()):
    return {
        'run_id': 'run-1',
        'batch_id': 'KB-LIC-LEGAL',
        'source_inventory': list(sources),
        'patches': list(patches),
    }


# -- the repair ---------------------------------------------------------------


def test_an_evidence_shaped_source_is_rebuilt_rather_than_dropped():
    """The 422. `producer` / `source_domain` / `source_locator` is the evidence
    schema; GIS wants `source_type` and `title`."""
    fixed, notes = normalize_source_inventory(
        _envelope(
            [
                {
                    'source_id': 'kb-1',
                    'producer': 'kb-agent',
                    'source_domain': 'kb',
                    'source_locator': {'doc': 'licence.pdf', 'page': 4},
                    'retrieval_note': 'лицензия  СЫК  01234  НЭ',
                }
            ]
        )
    )

    source = fixed['source_inventory'][0]
    assert source['source_id'] == 'kb-1'
    assert source['source_type'] == 'knowledge_base'
    assert source['title'] == 'kb-agent evidence'
    assert source['locator'] == json.dumps(
        {'doc': 'licence.pdf', 'page': 4}, ensure_ascii=False, sort_keys=True
    )
    assert notes == [
        '1 owner source entries were missing source_type or title '
        'and were rebuilt from their evidence fields'
    ]


@pytest.mark.parametrize(
    ('domain', 'expected'),
    [
        ('gis', 'gis'),
        ('web', 'web'),
        ('kb', 'knowledge_base'),
        ('knowledge_base', 'knowledge_base'),
        ('vision', 'vision'),
        ('KB', 'knowledge_base'),
        ('', 'derived'),
        ('something-else', 'derived'),
    ],
)
def test_the_domain_decides_the_source_type(domain, expected):
    """`derived` is the fallback rather than `unknown`: a source an owner
    produced from other sources is what an unattributed entry almost always is,
    and `unknown` would be a claim about the source rather than about us."""
    fixed, _ = normalize_source_inventory(
        _envelope([{'source_id': 's1', 'source_domain': domain, 'title': 't'}])
    )

    assert fixed['source_inventory'][0]['source_type'] == expected


def test_a_title_falls_back_through_producer_then_note_then_id():
    fixed, _ = normalize_source_inventory(
        _envelope(
            [
                {'source_id': 'a', 'producer': 'web-agent', 'retrieval_note': 'ignored'},
                {'source_id': 'b', 'retrieval_note': '  note   with   spaces  '},
                {'source_id': 'c'},
            ]
        )
    )

    assert [s['title'] for s in fixed['source_inventory']] == [
        'web-agent evidence',
        'note with spaces',
        'c',
    ]


def test_an_entry_with_no_source_id_is_dropped_and_counted():
    """The one case where dropping is right: without an id nothing can
    reference it, so keeping it would put an unreachable source in the
    inventory. Counted, because a silent drop is a lost source."""
    fixed, notes = normalize_source_inventory(
        _envelope([{'title': 'orphan', 'source_type': 'web'}, {'source_id': 'k', 'title': 't', 'source_type': 'kb'}])
    )

    assert [s['source_id'] for s in fixed['source_inventory']] == ['k']
    assert '1 source entries had no source_id and were dropped' in notes


# -- deduplication ------------------------------------------------------------


def test_two_entries_with_the_same_content_are_merged_despite_different_ids():
    """Identity is content, not `source_id`. The id carries the chunk and
    attempt suffixes `merge_owner_envelopes` adds, which make one source look
    like three."""
    fixed, notes = normalize_source_inventory(
        _envelope(
            [
                {'source_id': 'kb__part_1__x', 'source_type': 'kb', 'title': 'Лицензия', 'locator': 'p4'},
                {'source_id': 'kb__part_2__x', 'source_type': 'kb', 'title': 'Лицензия', 'locator': 'p4'},
            ]
        )
    )

    assert len(fixed['source_inventory']) == 1
    assert fixed['source_inventory'][0]['source_id'] == 'kb__part_1__x'
    assert '1 duplicate source entries were merged' in notes


def test_a_patch_pointing_at_a_merged_entry_is_remapped():
    """Otherwise merging produces a dangling `source_ref`, and the submission
    is rejected for a second reason after being repaired for the first."""
    fixed, _ = normalize_source_inventory(
        _envelope(
            [
                {'source_id': 'first', 'source_type': 'kb', 'title': 'T', 'locator': 'l'},
                {'source_id': 'second', 'source_type': 'kb', 'title': 'T', 'locator': 'l'},
            ],
            [{'field_key': 'r001.a01', 'source_refs': ['second', 'first']}],
        )
    )

    # Both refs resolve to the survivor, and the duplicate that results is
    # collapsed rather than left as a repeated reference.
    assert fixed['patches'][0]['source_refs'] == ['first']


def test_a_patch_with_no_source_refs_is_passed_through_unchanged():
    fixed, _ = normalize_source_inventory(
        _envelope(
            [{'source_id': 's', 'source_type': 'kb', 'title': 'T'}],
            [{'field_key': 'r001.a01', 'status': 'not_found'}],
        )
    )

    assert fixed['patches'][0] == {'field_key': 'r001.a01', 'status': 'not_found'}


def test_two_sources_that_differ_only_by_url_stay_separate():
    """`url` is part of the identity, so the same title from two places is two
    sources -- collapsing them would silently merge provenance."""
    fixed, notes = normalize_source_inventory(
        _envelope(
            [
                {'source_id': 'a', 'source_type': 'web', 'title': 'T', 'url': 'https://one'},
                {'source_id': 'b', 'source_type': 'web', 'title': 'T', 'url': 'https://two'},
            ]
        )
    )

    assert len(fixed['source_inventory']) == 2
    assert not any('duplicate' in note for note in notes)


# -- the boring cases ---------------------------------------------------------


def test_an_envelope_with_no_inventory_is_returned_unchanged():
    envelope = {'run_id': 'run-1', 'patches': [{'field_key': 'r001.a01'}]}

    fixed, notes = normalize_source_inventory(envelope)

    assert fixed == envelope
    assert notes == []
    assert fixed is not envelope, 'the envelope is copied, never mutated in place'


def test_a_well_formed_inventory_produces_no_notes():
    """A run that needed no repair must not report a degradation."""
    fixed, notes = normalize_source_inventory(
        _envelope([{'source_id': 's', 'source_type': 'kb', 'title': 'T', 'locator': 'l'}])
    )

    assert notes == []
    assert fixed['source_inventory'][0]['source_type'] == 'kb'


# -- the port, against the implementation it was ported from ------------------


@pytest.fixture(scope='module')
def reference():
    """`normalize_source_inventory` from the deployed Tool, executed.

    Lifted out with its one module constant rather than imported: importing the
    module would pull in Open WebUI's runtime, which is the coupling the
    extraction removed.
    """
    if not EXPORT.is_file():
        pytest.skip(f'no Workspace export at {EXPORT}')
    import ast
    import collections.abc

    tree = ast.parse(EXPORT.read_text(encoding='utf-8'))
    kept = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == 'normalize_source_inventory')
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == '_DOMAIN_TO_SOURCE_TYPE' for t in node.targets
            )
        )
    ]
    assert len(kept) == 2, 'the export no longer defines these'
    namespace: dict = {
        'json': json,
        'Any': object,
        'Mapping': collections.abc.Mapping,
    }
    exec(  # noqa: S102 - executing the attested export is the point of the test
        compile(ast.Module(body=kept, type_ignores=[]), str(EXPORT), 'exec'), namespace
    )
    return namespace['normalize_source_inventory']


CASES = [
    _envelope([]),
    _envelope([{'source_id': 'kb-1', 'producer': 'kb-agent', 'source_domain': 'kb'}]),
    _envelope([{'source_id': 's', 'source_type': 'web', 'title': 'T', 'url': 'https://x'}]),
    _envelope(
        [
            {'source_id': 'a', 'source_type': 'kb', 'title': 'T', 'locator': 'l'},
            {'source_id': 'b', 'source_type': 'kb', 'title': 'T', 'locator': 'l'},
        ],
        [{'field_key': 'r001.a01', 'source_refs': ['b', 'a']}],
    ),
    _envelope([{'title': 'no id'}, {'source_id': 'k'}]),
    _envelope(
        [{'source_id': 'v', 'source_domain': 'vision', 'source_locator': ['a', 'b']}],
        [{'field_key': 'r002.a01', 'status': 'not_found'}],
    ),
    _envelope([{'source_id': 'x', 'source_domain': 'MADE-UP', 'retrieval_note': 'x' * 300}]),
]


@pytest.mark.parametrize('envelope', CASES, ids=range(len(CASES)))
def test_the_port_repairs_exactly_what_the_deployed_tool_repairs(reference, envelope):
    """§5 parity for this definition, at the only level available without a
    contour: same envelope in, same envelope and same notes out."""
    theirs, their_notes = reference(dict(envelope))
    ours, our_notes = normalize_source_inventory(dict(envelope))

    assert ours == theirs
    assert our_notes == their_notes
