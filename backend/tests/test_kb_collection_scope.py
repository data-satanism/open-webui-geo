"""The corpus the KB builtins search, and the three ways it used to move.

Run `b389ffe6` searched four food-extrusion collections. The mechanism was not
the model: `query_knowledge_files` and `grep_knowledge_files` fall through to
every knowledge base the requesting user can read whenever nothing scopes them,
ordered `updated_at DESC` -- so the corpus reorders whenever anyone edits any
collection, and two runs hours apart searched different things. The 67-cell
spread between two "identical" clean runs is that churn.

Three separate silences made it hard to see, and each has a test here:

* the fall-through searched everything and said so nowhere;
* a knowledge id that does not resolve, or that the user has no grant on, was
  skipped -- so a typo and an empty corpus returned the same reply;
* a chat folder's knowledge was appended to the model's, which would let the
  folder a conversation happens to sit in widen any scope, per chat.

The last group of tests is the one that must not be lost in a later cleanup:
with nothing configured, every one of these behaviours stays exactly as it is.
These two tools belong to every model on the contour, not to GeoTeaser.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from open_webui.tools.builtin import grep_knowledge_files, query_knowledge_files
from open_webui.utils.kb_collection_scope import (
    KB_COLLECTION_ALLOWLIST_ENV,
    kb_collection_allowlist,
)
from open_webui.utils.tools import (
    clean_openai_tool_schema,
    convert_function_to_pydantic_model,
    convert_pydantic_model_to_openai_function_spec,
    get_async_tool_function_and_apply_extra_params,
    get_builtin_tools,
)

USER = {'id': 'user-1', 'role': 'user'}


class _Knowledge:
    def __init__(self, kid, *, user_id='user-1', meta=None):
        self.id = kid
        self.name = kid
        self.user_id = user_id
        self.meta = meta or {}


class _File:
    def __init__(self, fid, content=''):
        self.id = fid
        self.filename = f'{fid}.md'
        self.user_id = 'user-1'
        self.data = {'content': content}


class _Knowledges:
    """The registry, with `search_knowledge_bases` counted rather than stubbed.

    Counted because "did the fall-through run?" is the question every scoping
    test here is really asking, and a scoped call that quietly still enumerated
    every collection would otherwise pass.
    """

    def __init__(self, rows, files=None, everything=None):
        self.rows = {row.id: row for row in rows}
        self.files = files or {}
        self.everything = everything if everything is not None else list(rows)
        self.searched_everything = 0

    async def get_knowledge_by_id(self, kid):
        return self.rows.get(kid)

    async def get_files_by_id(self, kid):
        return self.files.get(kid, [])

    async def search_knowledge_bases(self, user_id, filter=None, skip=0, limit=0):
        self.searched_everything += 1
        return SimpleNamespace(items=list(self.everything))


class _Files:
    def __init__(self, files=()):
        self.files = {f.id: f for f in files}

    async def get_file_by_id(self, fid):
        return self.files.get(fid)


class _AccessGrants:
    def __init__(self, granted=()):
        self.granted = set(granted)

    async def has_access(self, *, resource_id, **_kwargs):
        return resource_id in self.granted


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(EMBEDDING_FUNCTION=lambda *a, **k: [0.0])),
    )


@pytest.fixture
def kb(monkeypatch):
    """Wire the module boundaries both searches reach through."""
    import open_webui.models.access_grants as access_grants
    import open_webui.models.files as files_module
    import open_webui.models.knowledge as knowledge_module
    import open_webui.retrieval.utils as retrieval_utils
    import open_webui.tools.builtin as builtin

    state = SimpleNamespace(queried=[])

    def install(knowledges, files=_Files(), grants=_AccessGrants()):
        monkeypatch.setattr(knowledge_module, 'Knowledges', knowledges)
        monkeypatch.setattr(files_module, 'Files', files)
        monkeypatch.setattr(access_grants, 'AccessGrants', grants)
        return knowledges

    async def _query_collection(_request, collection_names, **_kwargs):
        state.queried.append(list(collection_names))
        return {'documents': [[]], 'metadatas': [[]], 'distances': [[]]}

    monkeypatch.setattr(retrieval_utils, 'query_collection', _query_collection)
    monkeypatch.setattr(
        builtin,
        'Groups',
        SimpleNamespace(get_groups_by_member_id=lambda _uid: _no_groups()),
    )
    state.install = install
    return state


async def _no_groups():
    return []


# -- the configuration itself ----------------------------------------------


def test_the_repository_default_is_no_allowlist():
    """Empty means unset, and unset means every caller keeps today's behaviour.
    A populated default would be one deployment's collection ids applied
    silently to every other."""
    assert kb_collection_allowlist({}) == ()
    assert kb_collection_allowlist({KB_COLLECTION_ALLOWLIST_ENV: ''}) == ()


def test_the_allowlist_keeps_its_configured_order_and_drops_repeats():
    """The resolved order is the search order. A scope that reorders itself is
    the unpinned corpus again, in a smaller disguise."""
    assert kb_collection_allowlist({KB_COLLECTION_ALLOWLIST_ENV: '["b", "a", "b"]'}) == ('b', 'a')
    assert kb_collection_allowlist({KB_COLLECTION_ALLOWLIST_ENV: 'b, a'}) == ('b', 'a')


# -- the injection seam ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_allowlist_reaches_the_tool_and_never_the_model():
    """`extra_params` is filtered to declared signature parameters, and
    Pydantic drops leading-underscore names from the generated spec. So the
    bound value is server-side in both directions: the tool receives it, and
    the model is never told the argument exists."""
    bound = await get_async_tool_function_and_apply_extra_params(
        query_knowledge_files,
        {'__collection_allowlist__': ('geo-a',), '__not_a_parameter__': 'x'},
    )

    assert bound.__extra_params__ == {'__collection_allowlist__': ('geo-a',)}

    spec = clean_openai_tool_schema(
        convert_pydantic_model_to_openai_function_spec(convert_function_to_pydantic_model(query_knowledge_files))
    )

    assert set(spec['parameters']['properties']) == {'query', 'knowledge_ids', 'count'}


@pytest.mark.asyncio
async def test_get_builtin_tools_injects_the_configured_allowlist(monkeypatch):
    monkeypatch.setenv(KB_COLLECTION_ALLOWLIST_ENV, '["geo-a","geo-b"]')
    tools = await _builtin_tools(monkeypatch, folder_knowledge=[])

    for name in ('query_knowledge_files', 'grep_knowledge_files'):
        assert tools[name]['callable'].__extra_params__['__collection_allowlist__'] == (
            'geo-a',
            'geo-b',
        )


@pytest.mark.asyncio
async def test_a_chat_folder_cannot_widen_a_configured_allowlist(monkeypatch):
    """An allowlist a chat folder can widen is not an allowlist. Folder
    knowledge is appended to the model's, wins the first branch of both
    searches, and would put the configured scope out of reach -- per chat,
    invisibly, and without either side of the change appearing in the run."""
    monkeypatch.setenv(KB_COLLECTION_ALLOWLIST_ENV, '["geo-a"]')
    tools = await _builtin_tools(monkeypatch, folder_knowledge=[{'type': 'collection', 'id': 'folder-kb'}])

    assert tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__'] == []


@pytest.mark.asyncio
async def test_a_chat_folder_still_widens_when_nothing_is_configured(monkeypatch):
    """The preserved half. Folder knowledge is a feature for every caller that
    never asked to be scoped, and turning it off for them would be this change
    taking something from people it was not about."""
    monkeypatch.delenv(KB_COLLECTION_ALLOWLIST_ENV, raising=False)
    folder = [{'type': 'collection', 'id': 'folder-kb'}]
    tools = await _builtin_tools(monkeypatch, folder_knowledge=folder)

    assert tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__'] == folder


async def _builtin_tools(monkeypatch, *, folder_knowledge):
    import open_webui.utils.tools as tools_module

    class _Config:
        @staticmethod
        async def get_many(*_names):
            return {}

        @staticmethod
        async def get(_name):
            return {}

    monkeypatch.setattr(tools_module, 'Config', _Config)
    return await get_builtin_tools(
        request=_request(),
        extra_params={'__user__': USER, '__metadata__': {'folder_knowledge': folder_knowledge}},
        features={},
        model={},
    )


# -- the scoped path ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_scoped_query_searches_exactly_the_configured_collections(kb):
    registry = kb.install(
        _Knowledges([_Knowledge('geo-b'), _Knowledge('geo-a'), _Knowledge('other')]),
    )

    await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __collection_allowlist__=('geo-a', 'geo-b'),
    )

    # Configured order, not `updated_at DESC`, and `other` is not in it.
    assert kb.queried == [['geo-a', 'geo-b']]
    assert registry.searched_everything == 0


@pytest.mark.asyncio
async def test_the_scoped_order_is_stable_across_calls(kb):
    """The property the fall-through could not have. `updated_at DESC` moves
    whenever any collection is touched by anyone; a configured tuple does not."""
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b'), _Knowledge('geo-c')]))

    for _ in range(3):
        await query_knowledge_files(
            'q',
            __request__=_request(),
            __user__=USER,
            __collection_allowlist__=('geo-c', 'geo-a', 'geo-b'),
        )

    assert kb.queried == [['geo-c', 'geo-a', 'geo-b']] * 3


@pytest.mark.asyncio
async def test_a_scoped_grep_searches_exactly_the_configured_collections(kb):
    registry = kb.install(
        _Knowledges(
            [_Knowledge('geo-a'), _Knowledge('geo-b'), _Knowledge('other')],
            files={
                'geo-a': [_File('f-a', 'кровля пласта')],
                'geo-b': [_File('f-b', 'кровля пласта')],
                'other': [_File('f-other', 'кровля пласта')],
            },
        ),
        files=_Files([_File('f-a'), _File('f-b'), _File('f-other')]),
    )

    # `grep_knowledge_files` returns lines, not JSON, when it matches anything.
    result = await grep_knowledge_files(
        'кровля',
        __request__=_request(),
        __user__=USER,
        __collection_allowlist__=('geo-a', 'geo-b'),
    )

    assert registry.searched_everything == 0
    assert {line.split()[0] for line in result.splitlines()} == {'f-a', 'f-b'}


# -- failing by name ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize('search', [query_knowledge_files, grep_knowledge_files])
async def test_a_configured_collection_that_does_not_exist_is_named(kb, search):
    """The exact failure this round exists to fix. A mistyped id used to be
    skipped, so it produced the reply an empty corpus produces -- and those are
    opposite diagnoses: one is a character to fix, the other is a corpus to
    fill."""
    registry = kb.install(_Knowledges([_Knowledge('geo-a')]))

    result = json.loads(
        await search(
            'q',
            __request__=_request(),
            __user__=USER,
            __collection_allowlist__=('geo-a', 'geo-typo'),
        )
    )

    assert result['id'] == 'geo-typo'
    assert result['scope_fault'] == 'collection'
    assert KB_COLLECTION_ALLOWLIST_ENV in result['error']
    # Never a quieter corpus instead of an error.
    assert registry.searched_everything == 0
    assert kb.queried == []


@pytest.mark.asyncio
async def test_a_configured_collection_the_user_cannot_read_is_named(kb):
    """The other half of the same silence, and the one nobody could answer from
    outside: the fall-through searched what the *requesting user* can read, so
    a missing grant on the geology collections looked exactly like a corpus
    with nothing in it."""
    kb.install(
        _Knowledges([_Knowledge('geo-a'), _Knowledge('geo-locked', user_id='someone-else')]),
        grants=_AccessGrants(),
    )

    result = json.loads(
        await query_knowledge_files(
            'q',
            __request__=_request(),
            __user__=USER,
            __collection_allowlist__=('geo-a', 'geo-locked'),
        )
    )

    assert result['id'] == 'geo-locked'
    assert 'read grant' in result['error']


@pytest.mark.asyncio
async def test_an_attached_collection_that_does_not_resolve_is_named(kb):
    """`__model_knowledge__` had the same missing `else`, and it is the arm the
    recommended Workspace fix relies on -- so a mistyped attachment there would
    have looked like the scoping change had simply not worked."""
    kb.install(_Knowledges([]))

    result = json.loads(
        await query_knowledge_files(
            'q',
            __request__=_request(),
            __user__=USER,
            __model_knowledge__=[{'type': 'collection', 'id': 'attached-typo'}],
        )
    )

    assert result['id'] == 'attached-typo'
    assert kb.queried == []


@pytest.mark.asyncio
async def test_a_model_supplied_id_outside_the_allowlist_is_refused_by_name(kb):
    """`knowledge_ids` is the model's own argument. Honouring one outside the
    configured scope would make the boundary a suggestion, which is what the
    fall-through already was."""
    registry = kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('extrusion')]))

    result = json.loads(
        await query_knowledge_files(
            'q',
            knowledge_ids=['extrusion'],
            __request__=_request(),
            __user__=USER,
            __collection_allowlist__=('geo-a',),
        )
    )

    assert result['id'] == 'extrusion'
    assert KB_COLLECTION_ALLOWLIST_ENV in result['error']
    assert registry.searched_everything == 0
    assert kb.queried == []


@pytest.mark.asyncio
async def test_an_attached_collection_outside_the_allowlist_is_refused_by_name(kb):
    """The model's own `meta.knowledge` is server-side and admin-set, which
    makes it trustworthy about *narrowing* and not about escaping. A contour
    that configured an allowlist and attached something else has two answers to
    one question, and the error names which id disagrees rather than picking."""
    registry = kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('extrusion')]))

    result = json.loads(
        await query_knowledge_files(
            'q',
            __request__=_request(),
            __user__=USER,
            __model_knowledge__=[{'type': 'collection', 'id': 'extrusion'}],
            __collection_allowlist__=('geo-a',),
        )
    )

    assert result['id'] == 'extrusion'
    assert KB_COLLECTION_ALLOWLIST_ENV in result['error']
    assert registry.searched_everything == 0


@pytest.mark.asyncio
async def test_an_attached_collection_inside_the_allowlist_narrows_it(kb):
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'q',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[{'type': 'collection', 'id': 'geo-b'}],
        __collection_allowlist__=('geo-a', 'geo-b'),
    )

    assert kb.queried == [['geo-b']]


@pytest.mark.asyncio
async def test_a_model_supplied_id_inside_the_allowlist_narrows_it(kb):
    """Narrowing inside the boundary is the one thing `knowledge_ids` is good
    for, and dropping it silently would be the same class of defect this file
    is about."""
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'q',
        knowledge_ids=['geo-b'],
        __request__=_request(),
        __user__=USER,
        __collection_allowlist__=('geo-a', 'geo-b'),
    )

    assert kb.queried == [['geo-b']]


# -- what an unconfigured contour keeps -------------------------------------


@pytest.mark.asyncio
async def test_an_unconfigured_query_still_searches_everything(kb):
    """The deliberate half of the trade, and the opposite of `PRODUCER_KIND_MAP`.
    That valve refuses to run unconfigured because it configures one GeoTeaser
    run; this configures every caller of two shared tools, so unset has to mean
    unchanged."""
    registry = kb.install(_Knowledges([_Knowledge('anything')]))

    await query_knowledge_files('q', __request__=_request(), __user__=USER)

    assert registry.searched_everything == 1
    assert kb.queried == [['anything']]


@pytest.mark.asyncio
async def test_an_unconfigured_grep_still_searches_everything(kb):
    registry = kb.install(
        _Knowledges([_Knowledge('anything')], files={'anything': [_File('f-1', 'кровля')]}),
        files=_Files([_File('f-1', 'кровля')]),
    )

    result = await grep_knowledge_files('кровля', __request__=_request(), __user__=USER)

    assert registry.searched_everything == 1
    assert result.startswith('f-1 ')


@pytest.mark.asyncio
async def test_an_unconfigured_query_still_honours_a_model_supplied_id(kb):
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('other')]))

    await query_knowledge_files(
        'q',
        knowledge_ids=['other'],
        __request__=_request(),
        __user__=USER,
    )

    assert kb.queried == [['other']]


# -- the per-run scope, from what a person attached ---------------------------


def test_an_attached_collection_reaches_the_scope():
    """The defect this closes, in one assertion.

    `Проект ГРР Лекын-Тальбейское 2025.pdf` sits in a collection the requester
    attached to the message. Open WebUI already put that collection into
    `__files__` with `type: 'collection'`; the adapter read the deployment
    allowlist and threw the attachment away, so the specialist searched the
    fifty most recently touched knowledge bases instead of the object's own.
    """
    from open_webui.utils.kb_collection_scope import (
        attached_collection_ids,
        resolve_kb_scope,
    )

    attached = [
        {'type': 'file', 'id': 'file-1', 'name': 'map.png'},
        {'type': 'collection', 'id': '2a0b4bcd-aa58-452e-a01d-e90cd16a3229'},
        {'type': 'note', 'id': 'note-1'},
    ]

    assert attached_collection_ids(attached) == ('2a0b4bcd-aa58-452e-a01d-e90cd16a3229',)

    scope = resolve_kb_scope(attached)
    assert scope['kb_scope_status'] == 'configured'
    assert scope['kb_configured_collections'] == ['2a0b4bcd-aa58-452e-a01d-e90cd16a3229']


def test_attachments_are_searched_before_the_reference_shelf(monkeypatch):
    """Order is search order, so the object's own dossier goes first.

    The union is also deduplicated: an id that is both attached and allowlisted
    appears once, keeping its attached position.
    """
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a,2a0b4bcd,shelf-b')
    scope = resolve_kb_scope([
        {'type': 'collection', 'id': '2a0b4bcd'},
        {'type': 'collection', 'id': 'object-own'},
    ])

    assert scope['kb_configured_collections'] == ['2a0b4bcd', 'object-own', 'shelf-a', 'shelf-b']


def test_a_run_with_nothing_attached_keeps_the_allowlist_behaviour(monkeypatch):
    """No attachment must not narrow a configured contour, and must not widen
    an unconfigured one into claiming a scope it does not have."""
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a')
    assert resolve_kb_scope(None)['kb_configured_collections'] == ['shelf-a']
    assert resolve_kb_scope([])['kb_scope_status'] == 'configured'

    monkeypatch.delenv('KB_COLLECTION_ALLOWLIST', raising=False)
    bare = resolve_kb_scope([{'type': 'file', 'id': 'f'}])
    assert bare['kb_scope_status'] == 'unconfigured'
    assert bare['kb_configured_collections'] == []


def test_a_malformed_attachment_entry_cannot_break_a_run():
    """`__files__` is handed over verbatim by design, so its shapes vary."""
    from open_webui.utils.kb_collection_scope import attached_collection_ids

    assert attached_collection_ids([
        'not-a-mapping',
        {'type': 'collection'},
        {'type': 'collection', 'id': ''},
        {'type': 'collection', 'id': '  spaced  '},
        {'type': 'COLLECTION', 'id': 'upper'},
    ]) == ('spaced', 'upper')
