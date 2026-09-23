"""Tests for the corpus the KB builtins search: the server-side scope, folder
knowledge, the attached-collection scope, the unscoped fall-through, and the
split between collections and visual sources."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from open_webui.tools.builtin import grep_knowledge_files, query_knowledge_files
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
    """Fake knowledge registry that counts `search_knowledge_bases` calls in
    `searched_everything`."""

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


def _request(internal=False):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(EMBEDDING_FUNCTION=lambda *a, **k: [0.0])),
        state=SimpleNamespace(internal=internal),
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


@pytest.mark.asyncio
async def test_the_server_side_scope_reaches_the_tool_and_never_the_model():
    """`__model_knowledge__` reaches the bound tool through `extra_params` and
    is absent from the model's tool spec."""
    attached = [{'type': 'collection', 'id': 'geo-a'}]
    bound = await get_async_tool_function_and_apply_extra_params(
        query_knowledge_files,
        {'__model_knowledge__': attached, '__not_a_parameter__': 'x'},
    )

    assert bound.__extra_params__ == {'__model_knowledge__': attached}

    spec = clean_openai_tool_schema(
        convert_pydantic_model_to_openai_function_spec(convert_function_to_pydantic_model(query_knowledge_files))
    )

    assert set(spec['parameters']['properties']) == {'query', 'knowledge_ids', 'count'}


@pytest.mark.asyncio
async def test_an_ordinary_chat_keeps_its_folder_knowledge(monkeypatch):
    """An ordinary chat's folder knowledge is attached to
    `query_knowledge_files`."""
    tools = await _builtin_tools(
        monkeypatch,
        folder_knowledge=[{'type': 'collection', 'id': 'folder-kb'}],
        internal=False,
    )

    attached = tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__']
    assert [(item['type'], item['id']) for item in attached] == [('collection', 'folder-kb')]


@pytest.mark.asyncio
async def test_a_chat_folder_widens_an_orchestrated_call_too(monkeypatch):
    """An orchestrated call also receives the chat folder's knowledge, tagged
    with source `folder`."""
    folder = [{'type': 'collection', 'id': 'folder-kb'}]
    tools = await _builtin_tools(monkeypatch, folder_knowledge=folder, internal=True)

    attached = tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__']
    assert [(item['type'], item['id'], item['source']) for item in attached] == [
        ('collection', 'folder-kb', 'folder')
    ]


async def _builtin_tools(monkeypatch, *, folder_knowledge, internal=False):
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
        request=_request(internal=internal),
        extra_params={'__user__': USER, '__metadata__': {'folder_knowledge': folder_knowledge}},
        features={},
        model={},
    )


@pytest.mark.asyncio
async def test_a_scoped_query_searches_exactly_the_attached_collections(kb):
    registry = kb.install(
        _Knowledges([_Knowledge('geo-b'), _Knowledge('geo-a'), _Knowledge('other')]),
    )

    await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[
            {'type': 'collection', 'id': 'geo-a'},
            {'type': 'collection', 'id': 'geo-b'},
        ],
    )

    assert kb.queried == [['geo-a', 'geo-b']]
    assert registry.searched_everything == 0


@pytest.mark.asyncio
async def test_the_scoped_order_is_stable_across_calls(kb):
    """A scoped query searches the attached collections in attach order on
    every call."""
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b'), _Knowledge('geo-c')]))

    for _ in range(3):
        await query_knowledge_files(
            'q',
            __request__=_request(),
            __user__=USER,
            __model_knowledge__=[
                {'type': 'collection', 'id': kid} for kid in ('geo-c', 'geo-a', 'geo-b')
            ],
        )

    assert kb.queried == [['geo-c', 'geo-a', 'geo-b']] * 3


@pytest.mark.asyncio
async def test_a_scoped_grep_searches_exactly_the_attached_collections(kb):
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

    result = await grep_knowledge_files(
        'кровля',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[
            {'type': 'collection', 'id': 'geo-a'},
            {'type': 'collection', 'id': 'geo-b'},
        ],
    )

    assert registry.searched_everything == 0
    assert {line.split()[0] for line in result.splitlines()} == {'f-a', 'f-b'}


@pytest.mark.asyncio
async def test_a_model_supplied_id_narrows_the_attached_scope(kb):
    """A model-supplied `knowledge_ids` narrows the search to that id."""
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'q',
        knowledge_ids=['geo-b'],
        __request__=_request(),
        __user__=USER,
    )

    assert kb.queried == [['geo-b']]


@pytest.mark.asyncio
async def test_an_unscoped_query_still_searches_everything(kb):
    """An unscoped query searches every knowledge base the registry returns."""
    registry = kb.install(_Knowledges([_Knowledge('anything')]))

    await query_knowledge_files('q', __request__=_request(), __user__=USER)

    assert registry.searched_everything == 1
    assert kb.queried == [['anything']]


@pytest.mark.asyncio
async def test_an_unscoped_grep_still_searches_everything(kb):
    registry = kb.install(
        _Knowledges([_Knowledge('anything')], files={'anything': [_File('f-1', 'кровля')]}),
        files=_Files([_File('f-1', 'кровля')]),
    )

    result = await grep_knowledge_files('кровля', __request__=_request(), __user__=USER)

    assert registry.searched_everything == 1
    assert result.startswith('f-1 ')


@pytest.mark.asyncio
async def test_an_unscoped_query_still_honours_a_model_supplied_id(kb):
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('other')]))

    await query_knowledge_files(
        'q',
        knowledge_ids=['other'],
        __request__=_request(),
        __user__=USER,
    )

    assert kb.queried == [['other']]


def test_an_attached_collection_reaches_the_scope():
    """An attached collection in `__files__` becomes the configured KB scope."""
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


def test_the_attach_order_is_the_search_order_and_repeats_collapse(monkeypatch):
    """`resolve_kb_scope` keeps attach order, collapses repeats, and ignores
    `KB_COLLECTION_ALLOWLIST`."""
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a,shelf-b')
    scope = resolve_kb_scope([
        {'type': 'collection', 'id': '2a0b4bcd'},
        {'type': 'collection', 'id': 'object-own'},
        {'type': 'collection', 'id': '2a0b4bcd'},
    ])

    assert scope['kb_configured_collections'] == ['2a0b4bcd', 'object-own']


def test_a_run_with_nothing_attached_claims_no_scope(monkeypatch):
    """With no attached collection `resolve_kb_scope` reports `unconfigured`
    and no collections, whatever the environment holds."""
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a')
    assert resolve_kb_scope(None)['kb_scope_status'] == 'unconfigured'
    assert resolve_kb_scope([])['kb_configured_collections'] == []

    monkeypatch.delenv('KB_COLLECTION_ALLOWLIST', raising=False)
    bare = resolve_kb_scope([{'type': 'file', 'id': 'f'}])
    assert bare['kb_scope_status'] == 'unconfigured'
    assert bare['kb_configured_collections'] == []


def test_a_malformed_attachment_entry_cannot_break_a_run():
    """`attached_collection_ids` skips malformed entries, strips ids, and
    matches the type case-insensitively."""
    from open_webui.utils.kb_collection_scope import attached_collection_ids

    assert attached_collection_ids([
        'not-a-mapping',
        {'type': 'collection'},
        {'type': 'collection', 'id': ''},
        {'type': 'collection', 'id': '  spaced  '},
        {'type': 'COLLECTION', 'id': 'upper'},
    ]) == ('spaced', 'upper')


def test_a_collection_is_not_a_visual_source():
    """`visual_source_files` excludes collections, and
    `attached_collection_ids` takes only collections."""
    from open_webui.utils.kb_collection_scope import (
        attached_collection_ids,
        visual_source_files,
    )

    mixed = [
        {'type': 'file', 'id': 'file-1', 'name': 'map.png'},
        {'type': 'collection', 'id': '2a0b4bcd-aa58-452e-a01d-e90cd16a3229'},
        {'type': 'note', 'id': 'note-1'},
        {'id': 'no-type-at-all'},
    ]

    assert [f['id'] for f in visual_source_files(mixed)] == ['file-1', 'note-1', 'no-type-at-all']
    assert attached_collection_ids(mixed) == ('2a0b4bcd-aa58-452e-a01d-e90cd16a3229',)

    assert visual_source_files([{'type': 'collection', 'id': 'c'}]) == []


@pytest.mark.asyncio
async def test_a_collection_alone_does_not_demand_the_vision_tool(monkeypatch):
    """A `__files__` holding only a collection builds no vision caller."""
    from open_webui.tools import geotizer as tool

    async def _no_tools():
        return []

    monkeypatch.setattr('open_webui.models.tools.Tools.get_tools', _no_tools)

    caller = await tool._build_vision_evidence_caller(
        {'__files__': [{'type': 'collection', 'id': '2a0b4bcd'}]},
        collection_url='',
    )

    assert caller is None


@pytest.mark.asyncio
async def test_an_attached_image_still_demands_the_vision_tool(monkeypatch):
    """An attached file demands the vision tool and raises when it is not
    installed."""
    from open_webui.services.geotizer.errors import GeotizerOrchestrationError
    from open_webui.tools import geotizer as tool

    async def _no_tools():
        return []

    monkeypatch.setattr('open_webui.models.tools.Tools.get_tools', _no_tools)

    with pytest.raises(GeotizerOrchestrationError) as raised:
        await tool._build_vision_evidence_caller(
            {'__files__': [
                {'type': 'file', 'id': 'file-1', 'name': 'map.png'},
                {'type': 'collection', 'id': '2a0b4bcd'},
            ]},
            collection_url='',
        )

    assert str(raised.value) == (
        'GeoTeaser received visual sources, but the GeoMAS Geological Vision tool is not installed.'
    )


def test_the_resolved_scope_reaches_the_specialist_that_must_honour_it():
    """The contributor prompt carries the resolved collection ids and the
    instruction to search only them."""
    from open_webui.services.artifacts.geotizer.prompts import _contributor_prompt
    from open_webui.services.core.tasks import AgentTask

    task = AgentTask(agent='kb', producer='kb', role='contributor', task_id='kb-1', payload={})
    prompt = _contributor_prompt(
        object_name='Лекын-Тальбейская площадь',
        run_id='run-1',
        task=task,
        next_batch={'batch_id': 'KB-GEO', 'rows': []},
        knowledge_search_plan={},
        kb_collections=('2a0b4bcd-aa58-452e-a01d-e90cd16a3229', '59698dd0'),
    )

    assert '2a0b4bcd-aa58-452e-a01d-e90cd16a3229' in prompt
    assert '59698dd0' in prompt
    assert 'knowledge_collection_ids' in prompt
    assert 'Search knowledge_collection_ids and nothing else' in prompt


def test_a_run_with_no_resolved_scope_says_nothing_about_collections():
    """An unscoped run's contributor prompt does not mention
    `knowledge_collection_ids`."""
    from open_webui.services.artifacts.geotizer.prompts import _contributor_prompt
    from open_webui.services.core.tasks import AgentTask

    task = AgentTask(agent='kb', producer='kb', role='contributor', task_id='kb-1', payload={})
    prompt = _contributor_prompt(
        object_name='Лекын-Тальбейская площадь',
        run_id='run-1',
        task=task,
        next_batch={'batch_id': 'KB-GEO', 'rows': []},
        knowledge_search_plan={},
        kb_collections=(),
    )

    assert 'knowledge_collection_ids' not in prompt
