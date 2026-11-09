"""An admin naming a collection saw it; an admin enumerating did not.

Every knowledge search has two shapes. Name a collection and the id is checked
one row at a time -- `user_role == 'admin' or kb.user_id == user_id or
AccessGrants.has_access(...)`. Name none and the corpus is enumerated by a SQL
filter carrying `user_id` and `group_ids`, which
`AccessGrants.has_permission_filter` turns into «owner OR has a matching
grant». Ownership and grants are in both. **Role was in only the first.**

So an admin operator could open the geology corpus in the workspace and see it,
while the KB specialist -- which enumerates before it reads -- got back the
three collections that account had happened to create. The specialist was not
at fault: it called `search_knowledge_bases`, got extrusion collections, and
reported the miss honestly. It searched what it was allowed to see.

**These assert the corpus, not the filter dict.** A test that checked for
`'user_id' not in filter` would pass on a fix that shaped the dict correctly
and then passed it to something that ignored it, and it would fail on a
correct fix written another way. `_ScopedKnowledges` below implements the rule
`has_permission_filter` documents -- no `user_id` and no `group_ids` means no
principal condition and an untouched query -- and
`test_an_empty_filter_is_what_leaves_the_query_unfiltered` pins that rule
against the real function, so the fake is not merely agreeing with itself.

Behavioural rather than marker-based, for the reason
`test_kb_scope_skipping.py` gives: these are large, active upstream bodies, and
a merge that rewrites one takes any `# GEOTIZER-SEAM` marker with it while a
marker count still passes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from open_webui.tools.builtin import (
    grep_knowledge_files,
    list_knowledge_bases,
    query_knowledge_files,
    search_knowledge_bases,
    search_knowledge_files,
)

from test_kb_collection_scope import (  # noqa: F401 - the `kb` fixture
    _AccessGrants,
    _File,
    _Files,
    _Knowledge,
    _Knowledges,
    _request,
    kb,
)

ADMIN = {'id': 'admin-1', 'role': 'admin'}
USER = {'id': 'user-1', 'role': 'user'}

class _Kb(_Knowledge):
    """`_Knowledge` plus the two fields the listing tools read off a row.

    Local rather than added to the shared stub: three other files build
    `_Knowledge` for searches that never render a row, and widening the shared
    shape to suit this file would make those fixtures describe a KB more fully
    than the code under test ever asks them to.
    """

    def __init__(self, kid, *, user_id, description=''):
        super().__init__(kid, user_id=user_id)
        self.description = description
        self.data = {}
        self.updated_at = 0
        self.created_at = 0


class _Doc(_File):
    """`_File` plus the timestamp `search_knowledge_files` renders."""

    def __init__(self, fid, content=''):
        super().__init__(fid, content)
        self.updated_at = 0


#: `admin-1` created neither of the last two. `someone-else` owns both;
#: `shared` additionally carries a read grant that `user-1` holds.
MINE = _Kb('mine', user_id='admin-1')
THEIRS = _Kb('theirs', user_id='someone-else')
SHARED = _Kb('shared', user_id='someone-else')


class _ScopedKnowledges(_Knowledges):
    """`search_knowledge_bases` / `search_knowledge_files` as the database runs them.

    `AccessGrants.has_permission_filter` reads exactly two keys off the filter.
    With neither present it appends no clause and hands the query back whole;
    with either present the query becomes «owner OR a matching grant». Nothing
    else in the dict -- and no role -- reaches the WHERE clause.
    """

    def __init__(self, rows, files=None, grants=()):
        super().__init__(rows, files=files)
        self.grants = set(grants)
        self.filters: list[dict] = []

    def _visible(self, filter):
        self.filters.append(dict(filter or {}))
        scoped = (filter or {}).get('user_id') or (filter or {}).get('group_ids')
        if not scoped:
            return list(self.everything)
        user_id = (filter or {}).get('user_id')
        return [
            row
            for row in self.everything
            if row.user_id == user_id or row.id in self.grants
        ]

    async def search_knowledge_bases(self, user_id, filter=None, skip=0, limit=0):
        self.searched_everything += 1
        visible = self._visible(filter)
        # `skip`/`limit` are honoured because one caller pages until it gets a
        # short page. A stub that ignored them would loop forever rather than
        # fail, which is the kind of green a fixture should not be able to buy.
        page = visible[skip:]
        return SimpleNamespace(items=page[:limit] if limit else page)

    async def search_knowledge_files(self, filter=None, skip=0, limit=0):
        visible = {row.id for row in self._visible(filter)}
        return SimpleNamespace(
            items=[
                file
                for kb_id, group in self.files.items()
                if kb_id in visible
                for file in group
            ]
        )


def _registry(kb_state, **kwargs):
    registry = _ScopedKnowledges([MINE, THEIRS, SHARED], **kwargs)
    kb_state.install(registry, grants=_AccessGrants(registry.grants))
    return registry


# -- the enumerations that name no collection --------------------------------


async def _enumerate(search, user):
    """`list_knowledge_bases` takes no query; `search_knowledge_bases` takes one
    positionally. An empty query matches every row in both."""
    if search is list_knowledge_bases:
        return json.loads(await search(__request__=_request(), __user__=user))
    return json.loads(await search('', __request__=_request(), __user__=user))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'search',
    [list_knowledge_bases, search_knowledge_bases],
    ids=['list_knowledge_bases', 'search_knowledge_bases'],
)
async def test_an_admin_enumerating_sees_a_collection_another_user_owns(kb, search):
    """The case that found this. The operator could see the geology corpus as
    admin and the specialist could not, through the same account."""
    _registry(kb)

    result = await _enumerate(search, ADMIN)

    assert {row['id'] for row in result} == {'mine', 'theirs', 'shared'}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'search',
    [list_knowledge_bases, search_knowledge_bases],
    ids=['list_knowledge_bases', 'search_knowledge_bases'],
)
async def test_a_standard_user_enumerating_sees_ownership_and_grants_only(kb, search):
    """What must not move. `theirs` carries no grant this user holds, and a fix
    that widened too far would return it here."""
    _registry(kb, grants=('shared',))

    result = await _enumerate(search, USER)

    assert {row['id'] for row in result} == {'shared'}, 'ownership plus grants, nothing more'


@pytest.mark.asyncio
async def test_a_standard_user_with_no_grant_at_all_sees_nothing_of_anothers(kb):
    """The narrower half of the same assertion, stated separately because it is
    the one that catches a fix which dropped the filter for everyone."""
    _registry(kb)

    result = await _enumerate(list_knowledge_bases, USER)

    assert result == []


@pytest.mark.asyncio
async def test_an_admin_searching_files_reaches_another_users_collection(kb):
    """`search_knowledge_files`, whose named `knowledge_id` arm three lines
    above already passed an admin on role alone."""
    _registry(kb, files={'theirs': [_Doc('f-theirs', 'кровля пласта')]})

    result = json.loads(await search_knowledge_files('кровля', __request__=_request(), __user__=ADMIN))

    assert [file['id'] for file in result] == ['f-theirs']


@pytest.mark.asyncio
async def test_a_standard_user_searching_files_does_not(kb):
    _registry(kb, files={'theirs': [_Doc('f-theirs', 'кровля пласта')]})

    result = json.loads(await search_knowledge_files('кровля', __request__=_request(), __user__=USER))

    assert result == []


@pytest.mark.asyncio
async def test_an_admin_grepping_with_nothing_attached_reads_another_users_files(kb):
    """The fall-through arm of the tool that issued 83% of a run's searches."""
    registry = _registry(kb, files={'theirs': [_File('f-theirs', 'кровля пласта')]})
    kb.install(
        registry,
        files=_Files([_File('f-theirs', 'кровля пласта')]),
        grants=_AccessGrants(),
    )

    result = await grep_knowledge_files('кровля', __request__=_request(), __user__=ADMIN)

    assert result.startswith('f-theirs ')


@pytest.mark.asyncio
async def test_a_standard_user_grepping_does_not_reach_them(kb):
    registry = _registry(kb, files={'theirs': [_File('f-theirs', 'кровля пласта')]})
    kb.install(
        registry,
        files=_Files([_File('f-theirs', 'кровля пласта')]),
        grants=_AccessGrants(),
    )

    result = await grep_knowledge_files('кровля', __request__=_request(), __user__=USER)

    assert 'f-theirs' not in result


@pytest.mark.asyncio
async def test_an_admin_querying_with_nothing_attached_reaches_every_collection(kb):
    _registry(kb)

    await query_knowledge_files('кровля', __request__=_request(), __user__=ADMIN)

    assert kb.queried == [['mine', 'theirs', 'shared']]


@pytest.mark.asyncio
async def test_a_standard_user_querying_reaches_only_what_they_may_read(kb):
    _registry(kb, grants=('shared',))

    await query_knowledge_files('кровля', __request__=_request(), __user__=USER)

    assert kb.queried == [['shared']]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('user', 'expected'),
    [(ADMIN, {'mine', 'theirs', 'shared'}), (USER, {'shared'})],
    ids=['admin', 'standard_user'],
)
async def test_the_semantic_search_offers_the_vector_index_what_it_may_read(
    kb, monkeypatch, user, expected
):
    """`query_knowledge_bases` -- the semantic one -- pages the same
    enumeration and hands
    each page's ids to the vector index as a filter, so an id the enumeration
    withheld can never come back however close the embedding is.

    The stub echoes the ids it was asked about, which makes the returned list
    exactly the corpus the enumeration admitted."""
    import open_webui.tools.builtin as builtin

    _registry(kb, grants=('shared',))

    async def _embedding(_query, prefix=None, user=None):
        return [0.0]

    request = _request()
    request.app.state.EMBEDDING_FUNCTION = _embedding

    class _Vectors:
        @staticmethod
        async def search(*, collection_name, vectors, filter, limit):
            offered = filter['knowledge_base_id']['$in']
            return SimpleNamespace(
                ids=[list(offered)], distances=[[0.5] * len(offered)]
            )

    monkeypatch.setattr(
        'open_webui.retrieval.vector.async_client.ASYNC_VECTOR_DB_CLIENT', _Vectors
    )

    result = json.loads(
        await builtin.query_knowledge_bases(
            'кровля', count=10, __request__=request, __user__=user
        )
    )

    assert {row['id'] for row in result} == expected


# -- the kb_exec path, in the other upstream file -----------------------------


@pytest.mark.asyncio
async def test_the_kb_exec_enumeration_honours_the_role_its_named_arms_honour(kb):
    """`knowledge_fs.py`'s `_get_accessible_kb_ids`. Its two named arms call
    `_has_access`, which honours admin; the enumerating arm did not.

    Reached only when `ENABLE_KB_EXEC` is on, and it defaults off -- which is
    the reason to fix it rather than to leave it: a contour that turns the flag
    on would otherwise get an `ls` showing a different corpus from the `grep`
    beside it, silently."""
    from open_webui.tools.knowledge_fs import _get_accessible_kb_ids

    _registry(kb)

    seen = await _get_accessible_kb_ids(ADMIN, model_knowledge=None)
    assert {kb_id for kb_id, _name, _description in seen} == {'mine', 'theirs', 'shared'}

    seen = await _get_accessible_kb_ids(USER, model_knowledge=None)
    assert {kb_id for kb_id, _name, _description in seen} == set()


# -- the rule the fake above encodes, against the real function ---------------


def test_an_empty_filter_is_what_leaves_the_query_unfiltered():
    """Without this the tests above prove only that my fake agrees with my fix.

    `has_permission_filter` builds SQLAlchemy expressions and does no I/O, so
    it can be asked directly. Two facts: a filter carrying neither `user_id`
    nor `group_ids` adds no WHERE clause, and one carrying `user_id` does.
    """
    from sqlalchemy import select

    from open_webui.models.access_grants import AccessGrants
    from open_webui.models.knowledge import Knowledge

    def where(filter):
        return AccessGrants.has_permission_filter(
            db=None,
            query=select(Knowledge),
            DocumentModel=Knowledge,
            filter=filter,
            resource_type='knowledge',
            permission='read',
        ).whereclause

    assert where({'query': ''}) is None, 'an admin filter must not narrow the query'
    assert where({}) is None
    assert where({'user_id': 'user-1'}) is not None
    assert where({'group_ids': ['g-1']}) is not None
