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
import re
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


def test_the_router_grants_nothing_and_creates_nothing():
    """S1.4 asks for `grant_access` and its helpers to move out of the router
    into `services/geotizer/provisioning.py`, with admin auth on whatever calls
    it. Two things had already settled that differently, and both are right:

    there is no `grant_access` in this router -- it is a download proxy, and the
    only granting in the repository is `AccessGrants.grant_access` called from
    the privileged provisioning service, which is not model-callable and is
    reached by a CLI command rather than an endpoint;

    and `provisioning.py` cannot live under `services/` at all, because
    provisioning needs `open_webui.models.*` and the purity boundary from S0.6
    forbids that import. Putting it there would make the boundary check
    unsatisfiable.

    So the step is met in substance and unimplementable as written. This test is
    the substance: the router creates nothing and grants nothing."""
    calls = attribute_calls(ROUTER)

    assert not [call for call in calls if 'grant' in call.lower()]
    assert not [
        call
        for call in calls
        if call.split('.')[0] in ENTITY_REGISTRIES
        and any(verb in call.split('.')[1] for verb in ('insert', 'create', 'add', 'update', 'delete'))
    ]
    assert not (SERVICES / 'geotizer/provisioning.py').exists()


def test_the_adapter_holds_no_policy_of_its_own():
    """S1.6, on the source rather than on the generated artefact. The build test
    checks what the Workspace Tool contains; this checks what the module it
    delegates to contains, because a retry limit or a batch ceiling sitting here
    is policy in the adapter whether or not it reaches the artefact.

    Five of these were left behind by the move -- their live copies are in
    `workflow.py` -- and a sixth had been dead since before it."""
    tree = ast.parse(TOOL.read_text(encoding='utf-8'))
    constants = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.isupper()
    }

    assert not constants & {
        'MAX_OWNER_ATTEMPTS',
        'MAX_BATCHES',
        'MAX_OWNER_FIELDS_PER_CALL',
        'VISION_TOOL_IDS',
        'GRR_SCHEDULE_FIELD_KEYS',
        'ENABLE_GEOMAS_RAG_V2',
    }


def test_no_constant_in_the_adapter_is_unused():
    """A dead constant is how policy comes back: it reads as configuration
    somebody still honours."""
    source = TOOL.read_text(encoding='utf-8')
    tree = ast.parse(source)
    declared = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.isupper()
    }
    loaded = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}

    assert declared <= loaded, sorted(declared - loaded)


def test_the_adapter_stays_within_its_budget():
    """S1.6 asked for a thin adapter and got one: 2077 lines down to ~520.

    A ceiling, not an exact count. The exact number has been written into three
    documents and been wrong in all of them within a day each time -- most
    recently by two lines, from a refactor in the same session that quoted it.
    An exact figure in prose is a fact nobody recomputes; a ceiling here is one
    CI recomputes on every push, and it fails when the adapter starts growing
    logic back rather than when someone adds an import.
    """
    lines = len(TOOL.read_text(encoding='utf-8').splitlines())

    assert lines <= 600, f'the adapter is {lines} lines; S1.6 brought it to ~520'


def test_nothing_in_the_pure_core_is_defined_and_never_used():
    """The adapter has had this check since S1.6; the core did not, and two
    things had died in it -- a constant and a private function, both left behind
    by refactors that stopped using them.

    Same reasoning as the adapter's version, one layer down: a dead definition
    reads as something somebody still honours. The consumer set here is every
    place that may import the core, so a name absent from all of them is used by
    nobody. `__all__` entries are exempt: they are the published surface, and a
    module may legitimately export what only a future caller needs.
    """
    consumers = [
        SERVICES,
        BACKEND / 'open_webui/tools',
        BACKEND / 'open_webui/utils',
        BACKEND / 'tests',
        BACKEND.parent / 'scripts',
    ]
    # Asserted, not filtered. A consumer root that silently does not exist
    # narrows the search and turns this into a check that passes because it
    # looked nowhere -- which is exactly how the import-boundary check came to
    # miss a module for months (A-42).
    for root in consumers:
        assert root.is_dir(), root
    blob = '\n'.join(
        path.read_text(encoding='utf-8')
        for root in consumers
        for path in root.rglob('*.py')
        if '__pycache__' not in path.parts
    )

    dead: list[str] = []
    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        tree = ast.parse(module.read_text(encoding='utf-8'))
        exported: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets
            ):
                exported = {
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                }
        names: list[tuple[str, int]] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.append((node.name, node.lineno))
            elif isinstance(node, ast.Assign):
                names.extend(
                    (target.id, node.lineno)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                    and target.id.isupper()
                    and target.id != '__all__'
                )
        for name, lineno in names:
            if name.startswith('__') or name in exported:
                continue
            if len(re.findall(rf'\b{re.escape(name)}\b', blob)) <= 1:
                dead.append(f'{module.relative_to(SERVICES)}:{lineno} {name}')

    assert dead == [], dead


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
    A chat attachment is in addition to this, never instead of it.

    S1.6 moved the terminal envelope into the core, so the path is minted there
    now. The rule did not change and neither did the value; only the file it is
    written in did, which is what this test follows rather than fails on."""
    terminal = (SERVICES / 'artifacts/geotizer/terminal.py').read_text(encoding='utf-8')

    assert '/geotizer/files/' in terminal
    assert '_terminal_outcome' in TOOL.read_text(encoding='utf-8')


def test_the_artifacts_are_also_attached_to_the_message():
    """Action 7's other half: `chat:message:files` is added as a convenient way
    to attach a file. The records point at the same durable paths the result
    text links to, so deleting the chat takes the convenience and leaves the
    access route."""
    from open_webui.services.artifacts.geotizer.terminal import attachment_files

    files = attachment_files(
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        {
            'pdf': '/api/v1/geotizer/files/run-1/source_report.pdf',
            'markdown': '/api/v1/geotizer/files/run-1/source_report.md',
            'state': '/api/v1/geotizer/files/run-1/state.json',
        },
        object_name='Лекын-Тальбейская',
    )

    assert [f['url'] for f in files] == [
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        '/api/v1/geotizer/files/run-1/source_report.pdf',
        '/api/v1/geotizer/files/run-1/source_report.md',
        '/api/v1/geotizer/files/run-1/state.json',
    ]
    for record in files:
        # `ResponseMessage.svelte` filters on `type` and renders `url`/`name`
        # through `FileItem`; anything outside `image`/`file` is dropped.
        assert record['type'] == 'file'
        assert record['name'].startswith('Лекын-Тальбейская — ')
        assert record['content_type']


def test_an_unproxied_path_is_never_attached():
    """A raw `/geotizer/files/...` is the GIS service's own path. Attaching one
    would hand the user a link their browser session cannot follow."""
    from open_webui.services.artifacts.geotizer.terminal import attachment_files

    assert attachment_files('/geotizer/files/run-1/geotizer.xlsx', None, object_name='X') == []


def test_the_attachment_never_replaces_the_download_link():
    """If the emitter raises, the run still returns its result. The links are
    the access route; the attachment is convenience."""
    source = TOOL.read_text(encoding='utf-8')
    start = source.index("'chat:message:files'")
    around = source[start - 600 : start + 400]

    assert 'except Exception' in around
    assert 'return result' in source[start:]


def test_chat_message_files_is_not_the_download_channel():
    """`__files__` is what the user attached on the way in, and
    `chat:message:files` is now emitted on the way out. Neither is the download
    channel: if the only way to reach a result were a chat message, the result
    would not survive the conversation.

    This test used to assert the event was absent from the tool, which was the
    right rule read one step too literally -- action 7 asks for the attachment
    to be *added*, and only forbids it replacing the durable API."""
    source = TOOL.read_text(encoding='utf-8')

    assert '__files__' in source
    assert 'chat:message:files' in source
    # Every attached record points back at the durable path, so the attachment
    # cannot become the only route by accident.
    assert 'attachment_files' in source
    assert '/api/v1' in (SERVICES / 'artifacts/geotizer/terminal.py').read_text(encoding='utf-8')


def test_the_router_serves_no_artifact_it_does_not_declare():
    """The allowlist is what stops a run_id/artifact pair being used to reach
    something else on the tool server."""
    source = ROUTER.read_text(encoding='utf-8')
    declared = {
        node.value for node in ast.walk(tree(ROUTER)) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert set(ARTIFACTS) <= declared
    assert 'ARTIFACTS' in source


# -- the supersede endpoint is admin-only, and not model-reachable -----------


def test_superseding_a_run_requires_an_admin():
    """`get_admin_user`, not `get_verified_user`.

    Retiring a run changes what every later run over the same object carries --
    GIS records the exclusion in the provenance of the runs that did not receive
    it -- so it is an operator act. The download proxies beside it are
    deliberately `get_verified_user`: reading an artefact you were given a link
    to is not the same privilege as changing what future runs produce.
    """
    import ast

    source = (REPO_ROOT / 'backend/open_webui/routers/geotizer.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    guards = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for argument in node.args.args + node.args.kwonlyargs:
            pass
        for default in node.args.defaults:
            if (
                isinstance(default, ast.Call)
                and getattr(default.func, 'id', '') == 'Depends'
                and default.args
            ):
                guards[node.name] = getattr(default.args[0], 'id', '')

    assert guards.get('supersede_geotizer_run') == 'get_admin_user'
    assert guards.get('download_geotizer') == 'get_verified_user'


def test_the_actor_recorded_for_a_supersede_is_the_session_not_the_body():
    """A caller-supplied actor is a caller-supplied claim, and this is the field
    an audit reads."""
    source = (REPO_ROOT / 'backend/open_webui/routers/geotizer.py').read_text(encoding='utf-8')
    body = source[source.index('async def supersede_geotizer_run') :]
    body = body[: body.index('\nasync def ')]

    assert "'actor':" in body
    assert 'user' in body.split("'actor':")[1].split('\n')[0]
    # The form model carries only the reason -- there is no actor to supply.
    assert 'class SupersedeRunForm' in source
    assert 'actor' not in source[source.index('class SupersedeRunForm') : source.index('@router.post')]


# -- one model-facing entry point -------------------------------------------

UTILS_TOOLS = BACKEND / 'open_webui/utils/tools.py'

# Workspace Tools this repository records as deleted. A live reference to one is
# either dead code or a resurrection nobody would notice.
RETIRED_TOOL_IDS = ('mainagent_tool_yulong', 'sub_agent')


def _builtin_functions_appended() -> set[str]:
    """Every name this module puts into `builtin_functions`.

    Read from the AST rather than by importing: `get_tools` pulls in the
    retrieval stack, and the property under test is what the source says the
    model may be shown.
    """
    names: set[str] = set()
    for node in ast.walk(tree(UTILS_TOOLS)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Name) and target.id == 'builtin_functions'):
            continue
        if node.func.attr == 'append':
            names.update(a.id for a in node.args if isinstance(a, ast.Name))
        elif node.func.attr == 'extend':
            for argument in node.args:
                if isinstance(argument, ast.List):
                    names.update(e.id for e in argument.elts if isinstance(e, ast.Name))
    return names


def test_the_builtin_is_not_a_second_tool_the_model_can_call():
    """§3. `fill_geoteaser` on the Workspace Tool is the entry point; the
    built-in `fill_geotizer` is what that Tool calls.

    Exposing both puts two tools that fill the same card in front of the same
    agent, and the skill's one-call rule cannot disambiguate them -- it names
    one method. The gate that used to stand here read
    `'mainagent_tool_yulong' in toolIds`, a Workspace Tool deleted two commits
    into this work, so the exposure was unreachable rather than intended; the
    reason to remove it is that recreating a tool by that name would silently
    bring it back.
    """
    assert 'fill_geotizer' not in _builtin_functions_appended()


def test_no_retired_workspace_tool_id_decides_what_a_model_is_shown():
    """A deleted tool's name still steering live behaviour is the shape of the
    bug, whatever it happens to gate today."""
    literals = {
        node.value
        for node in ast.walk(tree(UTILS_TOOLS))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    for retired in RETIRED_TOOL_IDS:
        assert retired not in literals, f'{retired} is still a live string in utils/tools.py'


def test_the_shim_calls_the_builtin_directly_rather_than_through_the_registry():
    """Which is why hiding the built-in costs nothing: the Workspace Tool
    imports it as a function, and never asks `get_tools` for it."""
    builder = (REPO_ROOT / 'scripts/build_geotizer_tool.py').read_text(encoding='utf-8')

    assert 'from open_webui.tools.geotizer import fill_geotizer' in builder
    assert 'get_tools' not in builder
