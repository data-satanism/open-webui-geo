"""The seam that builds `agent_call`, which had no test at all.

585 tests passed while `_build_agent_caller` had zero references in any of them.
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


def _install(monkeypatch, tool_module, loader):
    import open_webui.utils.plugin as plugin

    monkeypatch.setattr(plugin, 'load_tool_module_by_id', loader, raising=False)
    return tool_module


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
    assert expected in {'contributor', 'owner_completion', 'tool_free'}


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
    assert 'KeyError' not in message


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
