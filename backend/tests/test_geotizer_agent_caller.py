"""The seam that builds `agent_call`, which had no test at all.

598 tests passed while `_build_agent_caller` had zero references in any of them.
`test_geotizer_orchestration.py` is 2,600 lines and mentions `agent_call` 24
times -- always by injecting one, never by building one -- so the function that
reaches into the contour for a Workspace Tool was covered by nothing. That is
the shape of the failure: a green suite is not coverage, and the seam it did not
touch was the only thing that could stop a run before its first batch.

What it used to do: load `mainagent_tool_yulong` (the HTTP sub-chat delegator
Multitask Orchestration replaced) and `sub_agent` (not in this path at all) by
id, mutate the second's `DEFAULT_MODEL`, switch fourteen of its `ENABLE_*_TOOLS`
valves off one at a time, and monkey-patch `_extract_chat_history_message` onto
the first. Neither tool appears in the workspace artefact attestation.

It now calls `multitask_orchestration.run_agent_task`, the entry point the
orchestrator publishes for other tools. These three cases are the ones the
review asked for: present, absent, and returning a failure envelope.
"""

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
    """The Workspace Tool as it actually behaves, valves included.

    `load_tool_module_by_id` returns `module.Tools()` -- a fresh instance holding
    the *class defaults*. Everything an operator set in Workspace → Tools lives
    in the database and is read back by `Tools.get_tool_valves_by_id` or not at
    all. So a stand-in that has no `Valves` cannot tell a hydrated build from an
    unhydrated one, which is exactly why the seven tests above all passed
    through the regression.

    `run_agent_task` here resolves the model the way v3.5.0 does -- agent kind to
    valve to the `model` field of the outbound completion -- and records what it
    would have sent. The real `generate_chat_completion` call is inside the
    Workspace Tool, in `webui.db`, which this repository does not hold; this is
    the closest observable point to it. See the note in
    `test_configured_valve_reaches_the_model_call`.
    """

    class Valves:
        # Empty, as the shipped v3.5.0 defaults are. An empty model id is what
        # reaches the API as `404: Model '' was not found`.
        def __init__(self, GIS_MODEL='', KB_MODEL='', WEB_MODEL='', SKILLED_MODEL=''):
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
        # What v3.5.0 hands to `generate_chat_completion`.
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
    call = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(kind='kb', producer='KB-GEO', role='contributor', task_id='r1', payload={}),
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
    """`run_agent_task` silently falls back to `contributor` for an unknown
    mode, so a wrong mapping would give a tool-using model an owner decision
    and nothing would say so."""
    orchestrator = _Orchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call = await tool_module._build_agent_caller(_runtime())

    await call(
        AgentTask(kind=kind, producer='ASSEMBLE', role=role, task_id='t', payload={}),
        'p',
        'object',
        None,
    )

    assert orchestrator.calls[0]['mode'] == expected


@pytest.mark.asyncio
async def test_an_absent_orchestrator_names_the_tool_instead_of_raising_keyerror(
    tool_module, monkeypatch
):
    """The case that made this a P0: if the tool is not installed on a contour,
    the loader raises and every run fails before its first batch. It must fail
    with something an operator can act on."""

    async def loader(tool_id):
        raise KeyError(tool_id)

    _install(monkeypatch, tool_module, loader)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        await tool_module._build_agent_caller(_runtime())

    message = str(excinfo.value)
    assert 'missing_runtime_context' in message
    assert tool_module.ORCHESTRATOR_TOOL_ID in message
    # The cause is named, because `fill_geotizer` formats `str(exc)` and never
    # walks `__cause__`. What must not happen is a raw `KeyError` reaching the
    # model as the whole of the diagnosis.
    assert 'could not be loaded' in message
    assert not message.startswith('KeyError')


@pytest.mark.asyncio
async def test_an_orchestrator_without_run_agent_task_is_named_before_the_run_starts(
    tool_module, monkeypatch
):
    """`prompt-verification.md` §12.7 describes this seam as the load *and* a
    `getattr(module, "run_agent_task")` "with an explicit error if the attribute
    is missing"; §13.8 names the failure an operator should see. Guarding only
    the load left an older orchestrator to fail on the first owner batch with a
    bare `AttributeError`, after the run had already done work.
    """

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
    """`fill_geotizer` formats `str(exc)` into the terminal envelope and never
    walks `__cause__`, so a chained exception alone reaches nobody. An installed
    tool that fails to import must not be reported as an absent one."""

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
    """`run_agent_task` reports a refusal as a JSON envelope rather than by
    raising. The caller must hand it back so the workflow can classify it."""
    envelope = '{"status": "specialist_failed", "reason": "model_not_found", "retryable": false}'
    orchestrator = _Orchestrator(answer=envelope)

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader)
    call = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(kind='gis', producer='GIS-DC', role='contributor', task_id='r', payload={}),
        'p',
        'object',
        None,
    )

    assert result == envelope


def test_the_retired_delegator_ids_are_gone_from_the_adapter():
    """`mainagent_tool_yulong` and `sub_agent` are superseded, and neither
    appears in the workspace artefact attestation.

    Checked over the AST rather than the file text: the docstrings in this file
    and in `_build_agent_caller` name both tools deliberately, to say what was
    removed and why. A text scan would fail on its own explanation -- which this
    repository has already been caught by twice.
    """
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


# -- the valve regression --------------------------------------------------


@pytest.mark.asyncio
async def test_configured_valve_reaches_the_model_call(tool_module, monkeypatch):
    """Loading a module is not the same as configuring it.

    The seven tests above all pass while stored valves are ignored, because none
    of them asserts that a configured value leaves the process. This one fails on
    the unhydrated build and passes on the fixed one, which is the only property
    that distinguishes them.

    Asserted on the outbound model id, not on `orchestrator.valves`. Asserting
    the attribute tests the assignment; asserting what the specialist call
    carries tests the behaviour, and it is the behaviour that broke -- a
    production contour dropped GeoTeaser completeness to 5.1% (18/351) with 119
    `404 Model ''` failures, every filled field coming from GIS-service
    deterministic computation and none from any LLM specialist.

    Named limit: the real outbound `form_data` is built inside
    `multitask_orchestration` in `webui.db`, which this repository does not hold,
    so the furthest observable point from here is what the tool would send.
    `_ConfigurableOrchestrator` resolves agent kind to valve to `model` the way
    v3.5.0 does. A boundary that cannot be observed any closer than this is part
    of why the regression shipped, and it is worth saying so rather than
    implying the assertion reaches the HTTP call.
    """
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader, stored_valves={'GIS_MODEL': 'sentinel-model'})
    call = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(kind='gis', producer='GIS-DC', role='contributor', task_id='r1', payload={}),
        'do the thing',
        'Лекын-Тальбейская площадь',
        None,
    )

    assert orchestrator.sent[0]['model'] == 'sentinel-model'
    # And the failure this regression produced is absent: an empty model id is
    # what the API answers 404 to, and what the workflow then reads as "the
    # specialist found nothing".
    assert 'specialist_failed' not in result
    assert "Model ''" not in result


@pytest.mark.asyncio
async def test_an_unconfigured_valve_still_surfaces_as_a_failure(tool_module, monkeypatch):
    """The other half, and the reason not to add a default-model fallback.

    Hydration must not invent a model id when the operator has configured none.
    A permanent configuration fault has to surface as one -- substituting a
    default would turn `404: Model '' was not found` into a run against the
    wrong model, which is the same 5.1% card with no error to trace it by.
    """
    orchestrator = _ConfigurableOrchestrator()

    async def loader(_tool_id):
        return orchestrator, None

    _install(monkeypatch, tool_module, loader, stored_valves={})
    call = await tool_module._build_agent_caller(_runtime())

    result = await call(
        AgentTask(kind='gis', producer='GIS-DC', role='contributor', task_id='r1', payload={}),
        'p',
        'object',
        None,
    )

    assert orchestrator.sent[0]['model'] == ''
    assert 'specialist_failed' in result


@pytest.mark.asyncio
async def test_every_specialist_kind_gets_its_configured_model(tool_module, monkeypatch):
    """One valve reaching the call proves the hydration ran; it does not prove
    the mapping is right. All four kinds failed on the contour."""
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
    call = await tool_module._build_agent_caller(_runtime())

    for kind in ('gis', 'kb', 'web'):
        await call(
            AgentTask(kind=kind, producer='X', role='contributor', task_id='t', payload={}),
            'p',
            'object',
            None,
        )
    await call(
        AgentTask(kind='skilled', producer='ASSEMBLE', role='owner', task_id='t', payload={}),
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
    """A structural guard beside the behavioural ones.

    The regression was a deletion: the repoint replaced the two-delegator block
    and carried the load without the hydration, while `Current_Geomas` does it at
    :1323 and :1342 and `_build_vision_evidence_caller` does it thirty lines
    above. Nothing failed. This is cheap and it fails on the deletion itself.
    """
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
