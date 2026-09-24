"""Tests for `_build_agent_caller` in `tools/geotizer.py`: the orchestrator
present, absent or returning a failure envelope, valve hydration, the status
settings, the round-usage drain and the GIS scope in `__metadata__`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.core.tasks import AgentTask  # noqa: E402
from open_webui.services.geotizer.errors import GeotizerOrchestrationError  # noqa: E402


def _runtime():
    return {
        '__request__': object(),
        '__user__': {'id': 'u1'},
        '__event_emitter__': None,
        '__event_call__': None,
        '__metadata__': {},
        '__chat_id__': 'chat-1',
        '__message_id__': 'msg-1',
    }


class _Orchestrator:
    """Stands in for the Workspace Tool, recording how it was called."""

    def __init__(self, answer='{"ok": true}'):
        self.answer = answer
        self.calls: list[dict] = []

    async def run_agent_task(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


@pytest.fixture
def tool_module():
    from open_webui.tools import geotizer

    return geotizer


def _install(monkeypatch, tool_module, loader, stored_valves=None):
    import open_webui.models.tools as models_tools
    import open_webui.utils.plugin as plugin

    monkeypatch.setattr(plugin, 'load_tool_module_by_id', loader, raising=False)

    async def _stored(tool_id):
        return dict(stored_valves or {})

    monkeypatch.setattr(models_tools.Tools, 'get_tool_valves_by_id', staticmethod(_stored), raising=False)
    return tool_module


class _ConfigurableOrchestrator:
    """Stand-in for the Workspace Tool with `Valves`, resolving each agent kind
    to its model valve and recording the `model` it would send."""

    class Valves:
        def __init__(
            self, GIS_MODEL='', KB_MODEL='', WEB_MODEL='', SKILLED_MODEL='', **undeclared
        ):
            self.GIS_MODEL = GIS_MODEL
            self.KB_MODEL = KB_MODEL
            self.WEB_MODEL = WEB_MODEL
            self.SKILLED_MODEL = SKILLED_MODEL

    _MODEL_VALVE = {'gis': 'GIS_MODEL', 'kb': 'KB_MODEL', 'web': 'WEB_MODEL', 'skilled': 'SKILLED_MODEL'}

    def __init__(self):
        self.valves = self.Valves()
        self.sent: list[dict] = []

    async def run_agent_task(self, *, agent, prompt, mode, **kwargs):
        model = getattr(self.valves, self._MODEL_VALVE[agent], '')
        self.sent.append({'model': model, 'agent': agent, 'mode': mode})
        if not model:
            return json.dumps(
                {
                    'status': 'specialist_failed',
                    'reason': f"HTTPException: 404: Model '{model}' was not found",
                    'retryable': True,
                }
            )
        return '{"ok": true}'


@pytest.mark.asyncio
async def test_a_contributor_task_reaches_the_orchestrator_in_contributor_mode(
    tool_module, monkeypatch
):
    orchestrator = _Orchestrator()

    async def loader(tool_id):
        assert tool_id == tool_module.ORCHESTRATOR_TOOL_ID
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(agent='kb', producer='KB-GEO', role='contributor', task_id='r1', payload={}),
        'do the thing',
        'Лекын-Тальбейская площадь',
        None,
    )

    assert result == '{"ok": true}'
    sent = orchestrator.calls[0]
    assert sent['agent'] == 'kb'
    assert sent['mode'] == 'contributor'
    assert sent['prompt'] == 'do the thing'
    assert 'Лекын-Тальбейская площадь' in sent['original_user_request']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('role', 'kind', 'expected'),
    [
        ('contributor', 'kb', 'contributor'),
        ('owner', 'kb', 'owner_completion'),
        ('owner', 'skilled', 'tool_free'),
    ],
)
async def test_every_execution_mode_maps_to_one_the_orchestrator_accepts(
    tool_module, monkeypatch, role, kind, expected
):
    """Each task role and agent kind maps to an execution mode the orchestrator
    accepts."""
    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    await call(
        AgentTask(agent=kind, producer='ASSEMBLE', role=role, task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    assert orchestrator.calls[0]['mode'] == expected


@pytest.mark.asyncio
async def test_an_absent_orchestrator_names_the_tool_instead_of_raising_keyerror(
    tool_module, monkeypatch
):
    """An orchestrator that fails to load raises `GeotizerOrchestrationError`
    naming the tool and the cause, not a raw `KeyError`."""

    async def loader(tool_id):
        raise KeyError(tool_id)

    _install(monkeypatch, tool_module, loader)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        await tool_module._build_agent_caller(_runtime())

    message = str(excinfo.value)
    assert 'missing_runtime_context' in message
    assert tool_module.ORCHESTRATOR_TOOL_ID in message
    assert 'could not be loaded' in message
    assert not message.startswith('KeyError')


@pytest.mark.asyncio
async def test_an_orchestrator_without_run_agent_task_is_named_before_the_run_starts(
    tool_module, monkeypatch
):
    """An orchestrator without `run_agent_task` raises
    `GeotizerOrchestrationError` before the run starts, without an
    `AttributeError`."""

    class _Older:
        """Loads fine. Publishes the v2 entry point and not the v3 one."""

        async def ask_kb(self, **kwargs):
            return ''

    async def loader(_tool_id):
        return _Older(), None

    _install(monkeypatch, tool_module, loader)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        await tool_module._build_agent_caller(_runtime())

    message = str(excinfo.value)
    assert 'does not expose run_agent_task' in message
    assert tool_module.ORCHESTRATOR_TOOL_ID in message
    assert 'AttributeError' not in message


@pytest.mark.asyncio
async def test_a_load_failure_carries_its_cause_into_the_message(tool_module, monkeypatch):
    """A load failure's exception type and message appear in the raised error."""

    async def loader(_tool_id):
        raise ImportError("No module named 'httpx'")

    _install(monkeypatch, tool_module, loader)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        await tool_module._build_agent_caller(_runtime())

    assert "No module named 'httpx'" in str(excinfo.value)
    assert 'ImportError' in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_specialist_failure_envelope_is_returned_not_swallowed(
    tool_module, monkeypatch
):
    """A failure envelope from `run_agent_task` is returned to the caller
    unchanged."""
    envelope = '{"status": "specialist_failed", "reason": "model_not_found", "retryable": false}'
    orchestrator = _Orchestrator(answer=envelope)

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(agent='gis', producer='GIS-DC', role='contributor', task_id='r', payload={}),
        'p',
        'object',
        None,
    )

    assert result == envelope


def test_the_retired_delegator_ids_are_gone_from_the_adapter():
    """The adapter's code outside docstrings names neither
    `mainagent_tool_yulong` nor `sub_agent` nor their valves."""
    import ast

    tree = ast.parse((REPO_ROOT / 'backend/open_webui/tools/geotizer.py').read_text(encoding='utf-8'))
    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    for retired in ('mainagent_tool_yulong', 'sub_agent'):
        assert retired not in literals, retired
    assert '_extract_chat_history_message' not in attributes
    assert 'DEFAULT_MODEL' not in attributes
    assert {'DELEGATOR_TOOL_ID', 'SUB_AGENT_TOOL_ID'}.isdisjoint(names | literals)


@pytest.mark.asyncio
async def test_configured_valve_reaches_the_model_call(tool_module, monkeypatch):
    """A stored `GIS_MODEL` valve reaches the model the orchestrator would
    send."""
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader, stored_valves={'GIS_MODEL': 'sentinel-model'})
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(agent='gis', producer='GIS-DC', role='contributor', task_id='r1', payload={}),
        'do the thing',
        'Лекын-Тальбейская площадь',
        None,
    )

    assert orchestrator.sent[0]['model'] == 'sentinel-model'
    assert 'specialist_failed' not in result
    assert "Model ''" not in result


@pytest.mark.asyncio
async def test_an_unconfigured_valve_still_surfaces_as_a_failure(tool_module, monkeypatch):
    """With no stored model the call sends an empty model and returns the
    failure envelope, with no default substituted."""
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader, stored_valves={})
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(agent='gis', producer='GIS-DC', role='contributor', task_id='r1', payload={}),
        'p',
        'object',
        None,
    )

    assert orchestrator.sent[0]['model'] == ''
    assert 'specialist_failed' in result


@pytest.mark.asyncio
async def test_every_specialist_kind_gets_its_configured_model(tool_module, monkeypatch):
    """Each specialist kind is sent its own configured model."""
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(
        monkeypatch,
        tool_module,
        loader,
        stored_valves={
            'GIS_MODEL': 'gisagent',
            'KB_MODEL': 'kb-agent',
            'WEB_MODEL': 'web-agent',
            'SKILLED_MODEL': 'skilledagent-final',
        },
    )
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    for kind in ('gis', 'kb', 'web'):
        await call(
            AgentTask(agent=kind, producer='X', role='contributor', task_id='t', payload={}),
            'p',
            'object',
            None,
        )
    await call(
        AgentTask(agent='skilled', producer='ASSEMBLE', role='owner', task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    assert [s['model'] for s in orchestrator.sent] == [
        'gisagent',
        'kb-agent',
        'web-agent',
        'skilledagent-final',
    ]


def test_the_hydration_is_not_optional_in_the_adapter():
    """`_build_agent_caller` calls `get_tool_valves_by_id`."""
    import ast

    source = (REPO_ROOT / 'backend/open_webui/tools/geotizer.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == '_build_agent_caller'
    )
    called = {
        node.func.attr
        for node in ast.walk(builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert 'get_tool_valves_by_id' in called, (
        '_build_agent_caller loads the orchestrator without reading its stored '
        'valves; every value set in Workspace stays in the database'
    )


@pytest.mark.asyncio
async def test_the_status_valves_come_off_the_same_row_as_the_models(
    tool_module, monkeypatch
):
    """`STATUS_LANGUAGE` and `STATUS_VERBOSITY` are read from the
    orchestrator's stored valve row."""
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(
        monkeypatch,
        tool_module,
        loader,
        stored_valves={
            'GIS_MODEL': 'gisagent',
            'STATUS_LANGUAGE': 'en',
            'STATUS_VERBOSITY': 'technical',
        },
    )

    _call, status, _drain = await tool_module._build_agent_caller(_runtime())

    assert status.language == 'en'
    assert status.technical is True


@pytest.mark.asyncio
async def test_an_orchestrator_with_no_valves_class_still_yields_the_status_row(
    tool_module, monkeypatch
):
    """The status settings are read from the stored row even when the
    orchestrator has no `Valves` class."""

    class _NoValves:
        async def run_agent_task(self, **kwargs):
            return '{"ok": true}'

    _install(
        monkeypatch,
        tool_module,
        lambda _tool_id: _returns(_NoValves()),
        stored_valves={'STATUS_LANGUAGE': 'en', 'STATUS_VERBOSITY': 'technical'},
    )

    _call, status, _drain = await tool_module._build_agent_caller(_runtime())

    assert status.language == 'en'
    assert status.technical is True


@pytest.mark.asyncio
async def test_the_stored_row_is_fetched_once_for_both_readers(tool_module, monkeypatch):
    """The stored valve row is fetched once for both the valves and the status
    settings."""
    fetched: list[str] = []

    import open_webui.models.tools as models_tools
    import open_webui.utils.plugin as plugin

    async def loader(_tool_id):
        return _ConfigurableOrchestrator(), None

    monkeypatch.setattr(plugin, 'load_tool_module_by_id', loader, raising=False)

    async def _stored(tool_id):
        fetched.append(tool_id)
        return {'STATUS_LANGUAGE': 'en'}

    monkeypatch.setattr(
        models_tools.Tools, 'get_tool_valves_by_id', staticmethod(_stored), raising=False
    )

    await tool_module._build_agent_caller(_runtime())

    assert fetched == [tool_module.ORCHESTRATOR_TOOL_ID]


@pytest.mark.asyncio
async def test_an_unconfigured_contour_narrates_in_the_tool_shipped_defaults(
    tool_module, monkeypatch
):
    """A row without status keys yields language `ru` and non-technical
    verbosity."""
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader, stored_valves={})

    _call, status, _drain = await tool_module._build_agent_caller(_runtime())

    assert status.language == 'ru'
    assert status.technical is False


async def _returns(value):
    return value, None


@pytest.mark.asyncio
async def test_the_round_usage_drain_is_taken_off_the_loaded_orchestrator(
    tool_module, monkeypatch
):
    """An orchestrator exposing `open_round_usage` and `drain_round_usage`
    yields a round-usage scope that drains its records."""
    orchestrator = _Orchestrator()
    orchestrator.open_round_usage = lambda: None
    orchestrator.drain_round_usage = lambda: [{'agent': 'kb', 'outcome': 'answered'}]

    async def loader(tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    _call, _status, scope = await tool_module._build_agent_caller(_runtime())

    assert scope is not None
    scope.open()
    assert scope.drain() == [{'agent': 'kb', 'outcome': 'answered'}]


@pytest.mark.asyncio
async def test_a_build_without_the_drain_yields_none_rather_than_raising(
    tool_module, monkeypatch
):
    """An orchestrator without `drain_round_usage` yields no round-usage scope."""
    orchestrator = _Orchestrator()
    assert not hasattr(orchestrator, 'drain_round_usage')

    async def loader(tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    _call, _status, drain = await tool_module._build_agent_caller(_runtime())

    assert drain is None


def test_the_adapter_hands_the_drain_to_the_workflow():
    """The adapter passes `round_usage_drain` to the workflow."""
    source = tool_module_source()

    assert 'round_usage_drain=round_usage_drain,' in source, (
        'the adapter no longer forwards the drain to run_geotizer_workflow; '
        'every round would be reported unmeasured and no test in services/ '
        'would notice'
    )


def tool_module_source() -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / 'open_webui' / 'tools' / 'geotizer.py'
    ).read_text(encoding='utf-8')


@pytest.mark.asyncio
async def test_a_build_with_a_drain_but_no_open_is_refused(tool_module, monkeypatch):
    """An orchestrator with `drain_round_usage` but no `open_round_usage`
    yields no round-usage scope."""
    orchestrator = _Orchestrator()
    orchestrator.drain_round_usage = lambda: [{'agent': 'kb', 'outcome': 'answered'}]

    async def loader(tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    _call, _status, scope = await tool_module._build_agent_caller(_runtime())

    assert scope is None


@pytest.mark.asyncio
async def test_a_drain_returning_none_yields_an_empty_list_not_none(
    tool_module, monkeypatch
):
    """A drain returning None is read as an empty list."""
    orchestrator = _Orchestrator()
    orchestrator.open_round_usage = lambda: None
    orchestrator.drain_round_usage = lambda: None

    async def loader(tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    _call, _status, scope = await tool_module._build_agent_caller(_runtime())

    assert scope.drain() == []


@pytest.mark.asyncio
async def test_the_specialist_call_carries_the_run_s_project(tool_module, monkeypatch):
    from open_webui.services.artifacts.geotizer.run_scope import (
        SCOPE_METADATA_KEY,
        set_gis_scope,
    )

    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())
    set_gis_scope(project_id='tengkeli', run_id='run-7')

    await call(
        AgentTask(agent='gis', producer='GIS-GEO', role='contributor', task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    assert orchestrator.calls[0]['__metadata__'][SCOPE_METADATA_KEY] == {
        'project_id': 'tengkeli',
        'run_id': 'run-7',
    }


@pytest.mark.asyncio
async def test_the_scope_is_read_per_call_and_not_once_per_area(
    tool_module, monkeypatch
):
    """The GIS scope is read at each call, not when the caller is built."""
    from open_webui.services.artifacts.geotizer.run_scope import (
        SCOPE_METADATA_KEY,
        set_gis_scope,
    )

    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())

    task = AgentTask(agent='gis', producer='GIS-GEO', role='contributor', task_id='t', payload={})
    set_gis_scope(project_id='first', run_id='r1')
    await call(task, 'p', 'object', None)
    set_gis_scope(project_id='second', run_id='r2')
    await call(task, 'p', 'object', None)

    assert [entry['__metadata__'][SCOPE_METADATA_KEY]['project_id'] for entry in orchestrator.calls] == [
        'first',
        'second',
    ]


@pytest.mark.asyncio
async def test_what_the_platform_put_in_metadata_survives(tool_module, monkeypatch):
    """The scope key is added to a copy of `__metadata__` that keeps the
    platform's keys."""
    from open_webui.services.artifacts.geotizer.run_scope import (
        SCOPE_METADATA_KEY,
        set_gis_scope,
    )

    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    runtime = _runtime()
    runtime['__metadata__'] = {'files': [{'type': 'collection', 'id': 'kb-1'}]}
    call, _status, _drain = await tool_module._build_agent_caller(runtime)
    set_gis_scope(project_id='tengkeli', run_id='run-7')

    await call(
        AgentTask(agent='kb', producer='KB-GEO', role='contributor', task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    sent = orchestrator.calls[0]['__metadata__']
    assert sent['files'] == [{'type': 'collection', 'id': 'kb-1'}]
    assert SCOPE_METADATA_KEY in sent
    assert SCOPE_METADATA_KEY not in runtime['__metadata__']


@pytest.mark.asyncio
async def test_a_call_outside_any_fill_carries_no_scope_key(tool_module, monkeypatch):
    """A call with no GIS scope set carries no scope key in `__metadata__`."""
    from open_webui.services.artifacts.geotizer.run_scope import (
        _GIS_SCOPE,
        SCOPE_METADATA_KEY,
    )

    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call, _status, _drain = await tool_module._build_agent_caller(_runtime())
    _GIS_SCOPE.set(None)

    await call(
        AgentTask(agent='gis', producer='GIS-GEO', role='contributor', task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    assert SCOPE_METADATA_KEY not in orchestrator.calls[0]['__metadata__']
