"""Tests that every model id this repository declares as a default is in the confirmed model inventory, and that retired
ids are absent.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_INVENTORY = frozenset(
    {
        'orchestration-agent',
        'web-agent',
        'kb-agent',
        'gisagent',
        'skilledagent-final',
    }
)

MODEL_ID_DEFAULTS = {
    'backend/open_webui/utils/geotizer_service_account.py': ('DEFAULT_AGENT_MODEL_IDS',),
}

RETIRED_MODEL_IDS = ('skilledagent-sakana', 'gisagentyulong', 'skilledagentyulong', 'webagentyulong')


def _module_constants(relative: str) -> dict[str, object]:
    tree = ast.parse((REPO_ROOT / relative).read_text(encoding='utf-8'))
    found: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue
    return found


def _declared_model_ids() -> dict[str, str]:
    """Every declared model id, keyed by `path:NAME` so a failure names itself."""
    declared: dict[str, str] = {}
    for relative, names in MODEL_ID_DEFAULTS.items():
        constants = _module_constants(relative)
        for name in names:
            assert name in constants, f'{relative} no longer declares {name}'
            value = constants[name]
            values = (value,) if isinstance(value, str) else tuple(value)
            for index, model_id in enumerate(values):
                declared[f'{relative}:{name}[{index}]'] = model_id
    return declared


def test_every_declared_model_id_is_in_the_confirmed_inventory():
    for where, model_id in _declared_model_ids().items():
        assert model_id in MODEL_INVENTORY, f'{where} names {model_id!r}'


def test_the_four_wrong_ids_are_gone_from_the_repository():
    """No string literal under `backend/open_webui` contains a retired model id."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / 'backend/open_webui').rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for retired in RETIRED_MODEL_IDS:
                if retired in node.value:
                    offenders.append(f'{path.relative_to(REPO_ROOT)}:{node.lineno}: {retired}')
    assert offenders == []


def test_the_producer_names_are_no_longer_compiled_into_the_task_module():
    """`core/tasks.py` holds no producer-name literal and binds none of the removed producer-kind names."""
    source = (REPO_ROOT / 'backend/open_webui/services/core/tasks.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    bound = {node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.ClassDef)} | {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        if isinstance(target, ast.Name)
    }

    for producer in ('gis', 'kb', 'web', 'skilled'):
        assert producer not in literals, producer
    assert {'PRODUCER_AGENT_KIND', '_PRODUCER_KIND_HINTS', 'infer_agent_kind'}.isdisjoint(bound)


def test_the_adapter_names_no_model_of_its_own():
    """`tools/geotizer.py` binds no module constant to a known or retired model id."""
    constants = _module_constants('backend/open_webui/tools/geotizer.py')

    named = {
        name: value
        for name, value in constants.items()
        if isinstance(value, str) and value in MODEL_INVENTORY | set(RETIRED_MODEL_IDS)
    }
    assert named == {}, named


def test_the_service_account_grants_access_to_models_that_exist():
    """`DEFAULT_AGENT_MODEL_IDS` is `gisagent`, `kb-agent` and `web-agent`, all in the inventory."""
    constants = _module_constants('backend/open_webui/utils/geotizer_service_account.py')

    assert constants['DEFAULT_AGENT_MODEL_IDS'] == ('gisagent', 'kb-agent', 'web-agent')
    assert set(constants['DEFAULT_AGENT_MODEL_IDS']) <= MODEL_INVENTORY


@pytest.mark.xfail(
    strict=True,
    reason='the second half of the test prompt-verification.md 14.1 asks for: '
    'every id must resolve in request.app.state.MODELS at tool load. That needs '
    'a running instance with the contour models registered, which this suite has '
    'not got. Attention register A-01.',
)
def test_every_declared_model_id_resolves_at_tool_load():
    from open_webui.main import app

    registered = set(getattr(app.state, 'MODELS', {}) or {})

    assert registered, 'no models are registered in this process'
    for where, model_id in _declared_model_ids().items():
        assert model_id in registered, where
