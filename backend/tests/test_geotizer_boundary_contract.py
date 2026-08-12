"""CORE-BOUNDARY-01 actions 5 and 7, pinned rather than rebuilt.

Both are already satisfied by the code. Neither is guarded by anything, and
both are the kind of property that a reasonable-looking change quietly
reverses -- a convenience helper that creates a group, a download link that
becomes a chat attachment. So they are asserted here.

Action 5: `rag_runtime` and lifecycle management stay in Open WebUI, and
service entities are created by a privileged service rather than by the model's
tool.

Action 7: the durable download API stays; `chat:message:files` is a convenient
way to attach a file, not the only way to reach one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / 'backend'
TOOL = BACKEND / 'open_webui/tools/geotizer.py'
ROUTER = BACKEND / 'open_webui/routers/geotizer.py'
SERVICE_ACCOUNT = BACKEND / 'open_webui/utils/geotizer_service_account.py'
RAG_RUNTIME = BACKEND / 'open_webui/utils/geotizer_rag_runtime.py'
SERVICES = BACKEND / 'open_webui/services'


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'))


def imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def attribute_calls(path: Path) -> set[str]:
    """`Knowledges.insert_new_knowledge` and friends, as written."""
    calls: set[str] = set()
    for node in ast.walk(tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            calls.add(f'{func.value.id}.{func.attr}')
    return calls


# -- action 5: the model's tool creates nothing -----------------------------

# The registries a service entity would have to be created through.
ENTITY_REGISTRIES = ('Knowledges', 'Models', 'Groups', 'Users', 'Tools', 'AccessGrants')


def test_the_model_tool_creates_no_service_entity():
    """A tool the model can call must not be able to mint a group, a key or a
    knowledge base. The privileged service does that, under its own auth."""
    calls = attribute_calls(TOOL)

    creating = sorted(
        call
        for call in calls
        if call.split('.')[0] in ENTITY_REGISTRIES
        and any(verb in call.split('.')[1] for verb in ('insert', 'create', 'add', 'update', 'delete'))
    )

    assert creating == []


def test_the_privileged_service_is_where_entities_are_created():
    """Stated positively, so this pair does not both pass by the capability
    disappearing entirely."""
    source = SERVICE_ACCOUNT.read_text(encoding='utf-8')

    assert 'insert_new_group' in source or 'Groups.' in source
    assert 'api_key' in source


def test_the_privileged_service_is_not_reachable_from_the_model_tool():
    assert 'open_webui.utils.geotizer_service_account' not in imported_modules(TOOL)


def test_no_credential_is_written_into_a_workspace_tool_s_valves():
    """CORE-BOUNDARY-01, action 5: the write of `valves['api_key']` into
    `mainagent_tool_yulong` is deleted rather than ported.

    Two reasons, and the second outlives the first. The tool and the valve no
    longer exist, and specialists run as the requesting user -- so the write had
    nowhere to land. And what it landed was a live key in a DB-stored tool's
    valves, readable by anyone who can open the tool. The key belongs on the
    service user, where the ACL applies."""
    source = SERVICE_ACCOUNT.read_text(encoding='utf-8')
    tree = ast.parse(source)

    # No assignment into a subscript named `api_key`, however the mapping is
    # spelled -- `valves['api_key'] = …` is the shape, not the variable name.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                assert target.slice.value != 'api_key', f'line {node.lineno}'

    # Literals, not file text: the comment above the deletion names the tool it
    # deleted, and a text scan would have made that comment unwritable.
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert 'mainagent_tool_yulong' not in literals
    assert 'update_tool_valves_by_id' not in source
    # The key itself still exists and still reaches the service user.
    assert 'update_user_api_key_by_id' in source


def test_the_pure_core_cannot_create_anything_either():
    """It has no import of open_webui at all, so this is already true -- but
    stated where someone looking for the rule will find it."""
    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        assert not [m for m in imported_modules(module) if m.startswith('open_webui')], module


# -- action 5: rag_runtime stays in Open WebUI ------------------------------


def test_rag_runtime_stayed_out_of_the_pure_core():
    """The assignment keeps retrieval execution and lifecycle in Open WebUI.
    It is not an oversight that this module was left in utils/."""
    assert RAG_RUNTIME.is_file()
    assert not list(SERVICES.rglob('*rag_runtime*'))


def test_rag_runtime_reads_the_core_and_not_the_other_way_round():
    """Open WebUI may depend on the core; the core may not depend on it.

    The dependency is what is forbidden, not the name. `evaluation/rag_ab.py`
    copies the dispatcher's record schema and says in a comment where the string
    came from -- which is how a copy is meant to be documented, and which a
    substring check over the file text would have made impossible to write.
    """
    assert 'open_webui.services.project_evidence.retrieval' in imported_modules(RAG_RUNTIME)

    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        imported = imported_modules(module)
        assert not [name for name in imported if 'rag_runtime' in name], module


# -- action 7: the download API is durable ----------------------------------

ARTIFACTS = ('geotizer.xlsx', 'source_report.md', 'source_report.pdf', 'state.json')


def test_every_artifact_has_a_stable_url():
    """A run's outputs are reachable by URL, by anyone the ACL allows, for as
    long as the run exists -- not only by whoever was in the chat."""
    source = ROUTER.read_text(encoding='utf-8')

    for artifact in ARTIFACTS:
        assert f"@router.get('/files/{{run_id}}/{artifact}')" in source, artifact


@pytest.mark.parametrize('artifact', ARTIFACTS)
def test_each_download_is_authenticated(artifact):
    """Durable is not public. Every route resolves a verified user before it
    proxies anything."""
    source = ROUTER.read_text(encoding='utf-8')
    start = source.index(f"/files/{{run_id}}/{artifact}'")
    handler = source[start : start + 600]

    assert 'get_verified_user' in handler


def test_the_download_path_is_what_the_tool_hands_back():
    """The tool returns the durable path, so the caller has something to keep.
    A chat attachment is in addition to this, never instead of it."""
    assert '/geotizer/files/' in TOOL.read_text(encoding='utf-8')


def test_chat_message_files_is_an_input_not_the_download_channel():
    """`__files__` is what the user attached on the way in. If the only way to
    reach a result were a chat message, the result would not survive the
    conversation."""
    source = TOOL.read_text(encoding='utf-8')

    assert '__files__' in source
    assert 'chat:message:files' not in source


def test_the_router_serves_no_artifact_it_does_not_declare():
    """The allowlist is what stops a run_id/artifact pair being used to reach
    something else on the tool server."""
    source = ROUTER.read_text(encoding='utf-8')
    declared = {
        node.value for node in ast.walk(tree(ROUTER)) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert set(ARTIFACTS) <= declared
    assert 'ARTIFACTS' in source
