"""83% of a run's searches had no way to say where to search.

Run `a067e802` issued 207 searches; 171 of them were `grep_knowledge_files`.
Run `0d386ccf` issued 225, of which 175. That tool took `pattern`, `file_id`,
`case_insensitive` and `count_only` — and no way for a caller to name the
collections it wanted. `query_knowledge_files` has always taken
`knowledge_ids`, and the KB specialist passes the two configured collections
to it; on the other tool it could not, so every one of those searches fell
through to the arm that enumerates every knowledge base the user can read.

What came back says so plainly. Of the 124 distinct documents run `a067e802`
retrieved, 112 belong to another tenant's corpus —
`Research_of_extruded_products_with_protein_filling.pdf` at 234 hits, and a
run of dated `.xlsx` shift logs. That is run `b389ffe6`'s unbounded corpus,
still unbounded, in the tool doing most of the searching, on a contour whose
`state.json` records `kb_scope_status: configured` with two collection ids.

So the tool now accepts `knowledge_ids`, and the fall-through stays exactly
where it was for callers that name nothing — a scope this tool was never given
must not brick knowledge search for a caller who never asked to be scoped.

`KB_COLLECTION_ALLOWLIST` used to bound what could be named, and it is gone:
access control is Open WebUI's, decided per user by role, ownership and grants,
and a deployment-wide permitted set could only subtract from what it had
already decided. The bound on `knowledge_ids` is that same check, which every
arm of both searches goes through — an id the caller cannot read is skipped
and named, never returned.
"""

from __future__ import annotations

import pytest

from open_webui.tools.builtin import grep_knowledge_files

from test_kb_collection_scope import (  # noqa: F401 - the `kb` fixture
    USER,
    _AccessGrants,
    _Knowledge,
    _Knowledges,
    _request,
    kb,
)


class _File:
    def __init__(self, identifier: str, filename: str, content: str = 'кровля пласта') -> None:
        self.id = identifier
        self.filename = filename
        self.data = {'content': content}
        self.meta = {'name': filename}


async def _grep(kb_state, *, knowledge, files, grants=(), **kwargs):
    registry = _Knowledges(knowledge, files=files)
    kb_state.install(registry, grants=_AccessGrants(grants))
    result = await grep_knowledge_files(
        'кровля',
        __request__=_request(),
        __user__=USER,
        **kwargs,
    )
    return registry, result


GEO = _Knowledge('geo-a')
OTHER = _Knowledge('extrusion')
FILES = {
    'geo-a': [_File('f-geo', 'Проект ГРР Лекын-Тальбейское 2025.pdf')],
    'extrusion': [_File('f-other', 'Research_of_extruded_products_with_protein_filling.pdf')],
}


@pytest.mark.asyncio
async def test_named_collections_are_the_only_ones_searched(kb):
    registry, result = await _grep(
        kb, knowledge=[GEO, OTHER], files=FILES, knowledge_ids=['geo-a'],
        grants=('geo-a', 'extrusion'),
    )

    assert 'Лекын' in result
    assert 'extruded' not in result
    assert registry.searched_everything == 0, 'a scoped grep must not enumerate every KB'


@pytest.mark.asyncio
async def test_naming_nothing_still_falls_through_exactly_as_before(kb):
    """Shared by every model on the contour; an unset scope brickes nobody."""
    registry, _ = await _grep(kb, knowledge=[GEO, OTHER], files=FILES,
                              grants=('geo-a', 'extrusion'))

    assert registry.searched_everything == 1


@pytest.mark.asyncio
async def test_a_named_collection_that_does_not_exist_is_skipped_by_name(kb, caplog):
    """This asserted a refusal, and the refusal was the allowlist's: a named id
    outside the deployment-wide permitted set failed the whole call.

    What is left is the id that cannot be resolved at all, which is skipped and
    named. **Named is the half that had to be added here**: this arm carried
    two bare `continue`s where `query_knowledge_files` had already gained
    `_skip_unresolvable`, so the tool doing most of the searching was the one
    that said least about what it dropped.

    Note also that `searched_everything` stays 0: a caller that named something
    and had it skipped does not fall through to every collection on the
    contour, which would answer a narrow question with a wide corpus."""
    with caplog.at_level('INFO', logger='open_webui.tools.builtin'):
        registry, result = await _grep(
            kb, knowledge=[GEO, OTHER], files=FILES,
            knowledge_ids=['geo-a', 'no-such-collection'], grants=('geo-a', 'extrusion'),
        )

    assert 'Лекын' in result
    assert 'extruded' not in result
    assert registry.searched_everything == 0
    logged = ' '.join(record.getMessage() for record in caplog.records)
    assert 'no-such-collection' in logged
    assert 'does not exist' in logged


@pytest.mark.asyncio
async def test_a_collection_the_caller_cannot_read_is_skipped_not_answered(kb, caplog):
    """Skipped, named, and the rest still searched — the rule this file's
    sibling `test_kb_scope_skipping.py` establishes: an unreadable id must not
    brick the whole search, and must not vanish from it either."""
    unreadable = _Knowledge('extrusion', user_id='someone-else')
    with caplog.at_level('INFO', logger='open_webui.tools.builtin'):
        registry, result = await _grep(
            kb, knowledge=[GEO, unreadable], files=FILES,
            knowledge_ids=['geo-a', 'extrusion'], grants=('geo-a',),
        )

    assert 'Лекын' in result
    assert 'extruded' not in result
    assert registry.searched_everything == 0
    logged = ' '.join(record.getMessage() for record in caplog.records)
    assert 'extrusion' in logged
    assert 'no read grant' in logged


@pytest.mark.asyncio
async def test_a_single_file_still_wins_over_a_named_collection(kb):
    """`file_id` is one named document; the branch order is unchanged."""
    registry = _Knowledges([GEO, OTHER], files=FILES)
    kb.install(registry, files=_FilesById(FILES), grants=_AccessGrants(('geo-a', 'extrusion')))

    result = await grep_knowledge_files(
        'кровля',
        file_id='f-other',
        knowledge_ids=['geo-a'],
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[{'type': 'file', 'id': 'f-other'}],
    )

    assert registry.searched_everything == 0
    assert 'Лекын' not in result


class _FilesById:
    def __init__(self, by_collection):
        self.files = {f.id: f for group in by_collection.values() for f in group}

    async def get_file_by_id(self, fid):
        return self.files.get(fid)


@pytest.mark.asyncio
async def test_the_scope_is_what_keeps_the_other_corpus_out(kb, monkeypatch):
    """Verified by removal: without the branch, the named scope is ignored and
    the search enumerates everything again."""
    import open_webui.tools.builtin as builtin

    registry, scoped = await _grep(
        kb, knowledge=[GEO, OTHER], files=FILES, knowledge_ids=['geo-a'],
        grants=('geo-a', 'extrusion'),
    )
    assert registry.searched_everything == 0

    source = builtin.grep_knowledge_files.__doc__ or ''
    assert 'knowledge_ids' in source, (
        'the parameter must be documented for a model to know it exists'
    )
    assert 'extruded' not in scoped


# ------------------------------------------- which collection each hit came from


@pytest.mark.asyncio
async def test_every_returned_file_names_the_collection_it_came_from(kb, monkeypatch):
    """`result_sources` gave a filename and the cell gave a `document_id`;
    neither said the collection, so a cell resting on an unattached corpus
    looked exactly like one resting on the attached documents."""
    recorded: list[dict] = []
    monkeypatch.setattr(
        'open_webui.tools.builtin.record_query',
        lambda **kwargs: recorded.append(kwargs),
    )

    await _grep(kb, knowledge=[GEO, OTHER], files=FILES, knowledge_ids=['geo-a'])

    entry = recorded[-1]
    assert entry['searched_collections'] == ['geo-a']
    assert entry['result_document_ids'] == ['f-geo']
    assert entry['result_collection_ids'] == ['geo-a']


@pytest.mark.asyncio
async def test_an_unscoped_search_still_names_everything_it_opened(kb, monkeypatch):
    """The 31 and 52 calls that named no collection carried every one of the
    350 and 400 hits on another tenant's corpus, and nothing in the artefact
    said which collections they had opened. The fall-through is unchanged —
    what changes is that it is no longer silent."""
    from test_kb_collection_scope import _Files

    recorded: list[dict] = []
    monkeypatch.setattr(
        'open_webui.tools.builtin.record_query',
        lambda **kwargs: recorded.append(kwargs),
    )
    registry = _Knowledges([GEO, OTHER], files=FILES)
    # The fall-through arm resolves each id through `Files`, which the scoped
    # arms do not touch.
    kb.install(
        registry,
        files=_Files([file for group in FILES.values() for file in group]),
        grants=_AccessGrants(()),
    )

    await grep_knowledge_files('кровля', __request__=_request(), __user__=USER)

    entry = recorded[-1]
    assert entry['collections'] == []
    assert sorted(entry['searched_collections']) == ['extrusion', 'geo-a']
    assert dict(zip(entry['result_document_ids'], entry['result_collection_ids'])) == {
        'f-geo': 'geo-a',
        'f-other': 'extrusion',
    }


@pytest.mark.asyncio
async def test_a_pattern_repeating_one_token_thousands_of_times_is_collapsed(kb, monkeypatch):
    """Run `26aaf34a` compiled a 26,432-character regex — `линия` and nine
    other tokens, 2,520 alternatives — against every file it could reach. It
    matches exactly what the ten distinct tokens match."""
    recorded: list[dict] = []
    monkeypatch.setattr(
        'open_webui.tools.builtin.record_query',
        lambda **kwargs: recorded.append(kwargs),
    )
    registry = _Knowledges([GEO], files=FILES)
    kb.install(registry, grants=_AccessGrants(()))

    await grep_knowledge_files(
        '|'.join(['кровля'] * 1000 + ['подошва']),
        __request__=_request(),
        __user__=USER,
        knowledge_ids=['geo-a'],
    )

    assert recorded[-1]['query'] == 'кровля|подошва'
