"""Every model id this repository names as a default must actually exist.

`GEOMAS-DEF-001`. Four of five shipped valve defaults named models present in no
contour. The failure was invisible in the worst way: `run_agent_task` guards only
emptiness, so a *wrong* id passes; `MODELS.get(model_id, {"id": model_id})`
turns it into a bare dict without a log; `generate_chat_completion` then raises;
and `run_agent_loop` catches every exception and returns `retryable: true`. A
permanent configuration fault is presented to the model as a transient one, and
both the Skill and the orchestration prompt retry once into the same wall.

The valve defaults proper live in the `Multitask Orchestration` Workspace Tool,
which is stored in `webui.db` and not in Git -- this suite cannot reach them.
What it can reach is this repository's own copies of the same ids, which named
`skilledagent-sakana` and the three `…yulong` models until they were corrected.
That is what is held here.

`GMM/prompt-verification.md` 14.1 asks for exactly this test, and asks for a
second half that only a live instance can run: that every id resolves in
`request.app.state.MODELS` at tool load. That half is stated below as a strict
xfail rather than quietly dropped.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The confirmed inventory, from the fourth verification pass. Not a guess and
# not extensible here: a new model id is a contour change, and it belongs in
# `prompt-verification.md` before it belongs in this set.
MODEL_INVENTORY = frozenset(
    {
        'orchestration-agent',
        'web-agent',
        'kb-agent',
        'gisagent',
        'skilledagent-final',
    }
)

# Every module-level name in this repository that holds a model id, and where.
MODEL_ID_DEFAULTS = {
    'backend/open_webui/tools/geotizer.py': ('SKILLED_MODEL_ID',),
    'backend/open_webui/utils/geotizer_service_account.py': ('DEFAULT_AGENT_MODEL_IDS',),
}

# The ids that were wrong, kept as literals so the test fails if one comes back
# by a merge rather than by a decision.
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
    """Not just corrected where they were found -- absent as a value. A default
    that is right in one module and wrong in another is the same outage.

    Scanned over string literals rather than over the file text, so a comment
    may still name what was wrong. The first version of this test scanned text
    and failed on the comment recording the fix, which would have forced the
    change to go in undocumented."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / 'backend/open_webui').rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        with warnings.catch_warnings():
            # `tools/knowledge_fs.py` writes regex patterns in non-raw strings
            # and emits seven escape-sequence warnings when parsed. Not this
            # test's finding to report on every run -- attention register A-47.
            warnings.simplefilter('ignore', DeprecationWarning)
            tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for retired in RETIRED_MODEL_IDS:
                if retired in node.value:
                    offenders.append(f'{path.relative_to(REPO_ROOT)}:{node.lineno}: {retired}')
    assert offenders == []


def test_the_producer_names_are_untouched():
    """The other half of the same rule. `GISagent_yulong` is a string the GIS
    batch plan owns; correcting the model ids must not have swept it up."""
    tasks = (REPO_ROOT / 'backend/open_webui/services/core/tasks.py').read_text(encoding='utf-8')

    for producer in ('GISagent_yulong', 'KBagent_yulong', 'WEBagent_yulong'):
        assert producer in tasks, producer


def test_the_skilled_model_is_the_one_that_resolves():
    constants = _module_constants('backend/open_webui/tools/geotizer.py')

    assert constants['SKILLED_MODEL_ID'] == 'skilledagent-final'


def test_the_service_account_grants_access_to_models_that_exist():
    """The grant is what makes the specialists reachable at all: a service group
    with access to three non-existent ids has access to nothing."""
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
