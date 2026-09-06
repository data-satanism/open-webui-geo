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
with nothing attached, every one of these behaviours stays exactly as it is.
These two tools belong to every model on the contour, not to GeoTeaser.

**There was a fourth remedy here and it is gone.** `KB_COLLECTION_ALLOWLIST`
was a deployment-wide permitted set, read from the environment and injected
server-side, that both searches were held to. It could only subtract from what
Open WebUI's own access control had already decided per user -- role, then
ownership, then grants -- and it contradicted the rule this scope exists to
express: collections are attached by the user in chat, per run, and must not
be hardcoded, remembered between runs, or promoted to a permanent permitted
set. An attachment is a statement about this run, not a grant.

What it made possible stays. Naming an id that could not be used, instead of
`continue`-ing past it, was the alarm; the allowlist was the fence. Removing
both would have left neither, so the alarm is now unconditional and lives in
`test_kb_scope_skipping.py`. So does the recording -- `searched_collections`,
`result_collection_ids`, the per-file collection map -- which is what makes an
unscoped search visible in the artefact now that nothing stops one.
"""

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


def _request(internal=False):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(EMBEDDING_FUNCTION=lambda *a, **k: [0.0])),
        # A real `Request` always has `state`; this stand-in did not, and
        # `get_tools` began reading `request.state.internal` to strip the
        # mutating memory tools from a subagent's surface. The fake was a
        # request in the shape the function happened to use, so the first
        # attribute it gained broke three tests that are about neither.
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


# -- what reaches the tool, and what the model can see ------------------------


@pytest.mark.asyncio
async def test_the_server_side_scope_reaches_the_tool_and_never_the_model():
    """`extra_params` is filtered to declared signature parameters, and
    Pydantic drops leading-underscore names from the generated spec. So the
    bound value is server-side in both directions: the tool receives it, and
    the model is never told the argument exists.

    Asserted on `__model_knowledge__`, which is what still arrives this way.
    `__collection_allowlist__` was the other one and is gone; the mechanism is
    not, and it is upstream's, shared by every underscore-prefixed argument
    these builtins take."""
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
    """A person chatting with a folder of their own documents was never what
    the scope work was about, and this is the assertion that said so.

    It used to carry the qualifier «even when configured», because
    `kb_collection_allowlist()` read the environment and `get_builtin_tools`
    serves every chat turn: setting the variable for the pipeline turned folder
    knowledge off for every user, in every chat, with every model on the
    deployment. The qualifier is gone with the variable, and the behaviour it
    protected is now the only behaviour."""
    tools = await _builtin_tools(
        monkeypatch,
        folder_knowledge=[{'type': 'collection', 'id': 'folder-kb'}],
        internal=False,
    )

    attached = tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__']
    assert [(item['type'], item['id']) for item in attached] == [('collection', 'folder-kb')]


@pytest.mark.asyncio
async def test_a_chat_folder_widens_an_orchestrated_call_too(monkeypatch):
    """The exclusion that used to stand here applied to orchestrated calls and
    only while an allowlist was configured -- «an allowlist a chat folder can
    widen is not an allowlist». With no allowlist to widen there is nothing for
    it to protect, so `geotizer_kb_scope` returned its argument unchanged on
    every contour and came out as dead code rather than as a decision to let
    folders back in. Every contour that never set the variable already behaved
    exactly like this."""
    folder = [{'type': 'collection', 'id': 'folder-kb'}]
    tools = await _builtin_tools(monkeypatch, folder_knowledge=folder, internal=True)

    attached = tools['query_knowledge_files']['callable'].__extra_params__['__model_knowledge__']
    # On identity and origin rather than on the exact dict: `get_attached_knowledge`
    # tags each item with the `source` it came from, and that tag is what the
    # guard above keys on. Pinning the literal would make the tag look like a
    # regression the next time it is read.
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


# -- the scoped path ---------------------------------------------------------
#
# The scope is the attachment now. Every one of these used to pass a
# `__collection_allowlist__` tuple as well and assert the same corpus; the
# tuple is gone and the corpus is unchanged, because the attached ids were
# always the ones actually searched.


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

    # Attach order, not `updated_at DESC`, and `other` is not in it.
    assert kb.queried == [['geo-a', 'geo-b']]
    assert registry.searched_everything == 0


@pytest.mark.asyncio
async def test_the_scoped_order_is_stable_across_calls(kb):
    """The property the fall-through could not have. `updated_at DESC` moves
    whenever any collection is touched by anyone; the attached list does not."""
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

    # `grep_knowledge_files` returns lines, not JSON, when it matches anything.
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
    """Narrowing is the one thing `knowledge_ids` is good for, and dropping it
    silently would be the same class of defect this file is about.

    It cannot widen past access control: `knowledge_ids` is resolved through
    the same ownership-and-grant check every other path uses, which is where
    the boundary was all along -- the allowlist was a second one on top, and
    the second one was the one that could be wrong."""
    kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'q',
        knowledge_ids=['geo-b'],
        __request__=_request(),
        __user__=USER,
    )

    assert kb.queried == [['geo-b']]


# -- what an unscoped call keeps ---------------------------------------------
#
# Seven refusals used to stand above this line: an id outside the allowlist, an
# allowlisted id that did not resolve, one the user had no grant on. All three
# were the fence, and the fence is gone. What replaced them is not silence --
# every unusable id is named in the log and the search carries on without it,
# pinned in `test_kb_scope_skipping.py`, which also verifies the naming by
# removing it.


@pytest.mark.asyncio
async def test_an_unscoped_query_still_searches_everything(kb):
    """The behaviour these two shared builtins have always had when nothing
    scopes them, and the reason the recording matters more now than the fence
    did: this is reachable, it was always reachable, and the artefact is where
    it becomes visible."""
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


# -- the per-run scope, from what a person attached ---------------------------


def test_an_attached_collection_reaches_the_scope():
    """The defect this closes, in one assertion.

    `Проект ГРР Лекын-Тальбейское 2025.pdf` sits in a collection the requester
    attached to the message. Open WebUI already put that collection into
    `__files__` with `type: 'collection'`; the adapter read the deployment
    allowlist and threw the attachment away, so the specialist searched the
    fifty most recently touched knowledge bases instead of the object's own.

    The attachment is now the whole of the answer. It was the union of the
    attachment and the allowlist, which is why the ordering test below used to
    be about a «reference shelf» going second.
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


def test_the_attach_order_is_the_search_order_and_repeats_collapse(monkeypatch):
    """Order is search order, so the object's own dossier goes in the position
    the person put it, and a collection attached twice is searched once.

    The environment is asserted to be irrelevant, not merely left unset. A
    reader who remembers the union would otherwise have to take on faith that
    setting the old variable no longer does anything."""
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a,shelf-b')
    scope = resolve_kb_scope([
        {'type': 'collection', 'id': '2a0b4bcd'},
        {'type': 'collection', 'id': 'object-own'},
        {'type': 'collection', 'id': '2a0b4bcd'},
    ])

    assert scope['kb_configured_collections'] == ['2a0b4bcd', 'object-own']


def test_a_run_with_nothing_attached_claims_no_scope(monkeypatch):
    """No attachment must not widen a run into claiming a scope it does not
    have -- and, since the allowlist went, there is nothing else it could
    claim. `unconfigured` is asserted rather than left absent because this side
    genuinely knows."""
    from open_webui.utils.kb_collection_scope import resolve_kb_scope

    monkeypatch.setenv('KB_COLLECTION_ALLOWLIST', 'shelf-a')
    assert resolve_kb_scope(None)['kb_scope_status'] == 'unconfigured'
    assert resolve_kb_scope([])['kb_configured_collections'] == []

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


# -- one list, two consumers --------------------------------------------------


def test_a_collection_is_not_a_visual_source():
    """The blocker the scope work created, and it was dormant before it.

    `__files__` mixes attached files with attached knowledge bases. The vision
    path took the whole list, so attaching a collection for retrieval made the
    run demand the Geological Vision tool and abort before its first batch.
    Nobody hit it because nobody had reason to attach a collection until the
    scope resolution gave them one.
    """
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

    # Each consumer takes its own kind, and between them nothing is invented.
    assert [f['id'] for f in visual_source_files(mixed)] == ['file-1', 'note-1', 'no-type-at-all']
    assert attached_collection_ids(mixed) == ('2a0b4bcd-aa58-452e-a01d-e90cd16a3229',)

    # A run whose only attachment is a collection supplies no visual source.
    assert visual_source_files([{'type': 'collection', 'id': 'c'}]) == []


@pytest.mark.asyncio
async def test_a_collection_alone_does_not_demand_the_vision_tool(monkeypatch):
    """Attaching a knowledge base must leave the vision path asleep."""
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
    """The other half, and the reason the filter is on `type` and not on
    emptiness: written broadly enough it would disable vision altogether."""
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
    """The last link, and the one that was missing.

    The adapter resolves the collections a person attached and the run records
    them, but `run_agent_task` takes agent, prompt and mode and no scope
    argument -- so the task text is the only channel to the specialist. The KB
    specialist prompt says it will use ids the task supplies and nothing else;
    nothing was supplying them, so it went on choosing its own corpus and the
    object's own collection stayed out of reach.

    This is an instruction, and since the allowlist went it is the only one:
    there is no longer a server-side bound holding the specialist to what it
    was told. That is why the recording is not optional. `searched_collections`
    and `result_collection_ids` on the run are what make a specialist that
    searched something else visible afterwards -- on the artefact, which is the
    only place a disagreement between the instruction and the search can now
    be seen.
    """
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
    """An unscoped run must not be handed an empty list as if it were a scope.

    Telling a specialist to search nothing and nothing else is worse than not
    telling it anything: it would turn an unconfigured contour into a run that
    can find no evidence at all.
    """
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
