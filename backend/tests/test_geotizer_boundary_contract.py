"""Tests that the model's tool creates no service entity, `rag_runtime` stays in Open WebUI, and run artefacts stay
reachable through the durable download API.
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


ENTITY_REGISTRIES = ('Knowledges', 'Models', 'Groups', 'Users', 'Tools', 'AccessGrants')


def test_the_model_tool_creates_no_service_entity():
    """`open_webui/tools/geotizer.py` calls no create, insert, add, update or delete method on an entity registry."""
    calls = attribute_calls(TOOL)

    creating = sorted(
        call
        for call in calls
        if call.split('.')[0] in ENTITY_REGISTRIES
        and any(verb in call.split('.')[1] for verb in ('insert', 'create', 'add', 'update', 'delete'))
    )

    assert creating == []


def test_the_privileged_service_is_where_entities_are_created():
    """The service-account module creates groups and handles API keys."""
    source = SERVICE_ACCOUNT.read_text(encoding='utf-8')

    assert 'insert_new_group' in source or 'Groups.' in source
    assert 'api_key' in source


def test_the_privileged_service_is_not_reachable_from_the_model_tool():
    assert 'open_webui.utils.geotizer_service_account' not in imported_modules(TOOL)


def test_no_credential_is_written_into_a_workspace_tool_s_valves():
    """The service-account module writes no `api_key` into a tool's valves and still writes the service user's key."""
    source = SERVICE_ACCOUNT.read_text(encoding='utf-8')
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                assert target.slice.value != 'api_key', f'line {node.lineno}'

    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert 'mainagent_tool_yulong' not in literals
    assert 'update_tool_valves_by_id' not in source
    assert 'update_user_api_key_by_id' in source


def test_the_router_grants_nothing_and_creates_nothing():
    """The GeoTeaser router grants no access and creates no entity, and `services/geotizer/provisioning.py` does not
    exist.
    """
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
    """`open_webui/tools/geotizer.py` declares none of the retired policy constants."""
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
    """Every upper-case constant declared in `open_webui/tools/geotizer.py` is read."""
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
    """`open_webui/tools/geotizer.py` stays within its line ceiling."""
    lines = len(TOOL.read_text(encoding='utf-8').splitlines())

    assert lines <= 924, f'the adapter is {lines} lines; S1.6 brought it to ~520'


def test_nothing_in_the_pure_core_is_defined_and_never_used():
    """Every function, class and upper-case constant under `open_webui/services`, except `__all__` entries, is
    referenced by some consumer.
    """
    consumers = [
        SERVICES,
        BACKEND / 'open_webui/tools',
        BACKEND / 'open_webui/utils',
        BACKEND / 'tests',
        BACKEND.parent / 'scripts',
    ]
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
    """No module under `open_webui/services` imports an `open_webui` module."""
    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        assert not [m for m in imported_modules(module) if m.startswith('open_webui')], module


def test_rag_runtime_stayed_out_of_the_pure_core():
    """`utils/geotizer_rag_runtime.py` exists and nothing named `rag_runtime` is under `open_webui/services`."""
    assert RAG_RUNTIME.is_file()
    assert not list(SERVICES.rglob('*rag_runtime*'))


def test_rag_runtime_reads_the_core_and_not_the_other_way_round():
    """`rag_runtime` imports the retrieval core, and no core module imports `rag_runtime`."""
    assert 'open_webui.services.project_evidence.retrieval' in imported_modules(RAG_RUNTIME)

    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        imported = imported_modules(module)
        assert not [name for name in imported if 'rag_runtime' in name], module


def _router_artifacts() -> tuple[str, ...]:
    tree = ast.parse(ROUTER.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == 'ARTIFACTS'
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Dict), 'ARTIFACTS is no longer a dict literal'
        return tuple(
            key.value for key in node.value.keys if isinstance(key, ast.Constant)
        )
    raise AssertionError('ARTIFACTS not found in the router')


ARTIFACTS = _router_artifacts()


def test_the_artifact_map_holds_every_artefact_a_run_produces():
    """The router's `ARTIFACTS` map holds exactly the artefacts a run produces."""
    assert set(ARTIFACTS) == {
        'geotizer.xlsx',
        'geotizer.docx',
        'summary.md',
        'source_report.md',
        'source_report.pdf',
        'state.json',
        'run_log.json',
    }


def test_every_artifact_has_a_stable_url():
    """Every artefact has a `/files/{run_id}/<name>` route."""
    source = ROUTER.read_text(encoding='utf-8')

    for artifact in ARTIFACTS:
        assert f"@router.get('/files/{{run_id}}/{artifact}')" in source, artifact


@pytest.mark.parametrize('artifact', ARTIFACTS)
def test_each_download_is_authenticated(artifact):
    """Every download route depends on `get_verified_user`."""
    source = ROUTER.read_text(encoding='utf-8')
    start = source.index(f"/files/{{run_id}}/{artifact}'")
    handler = source[start : start + 600]

    assert 'get_verified_user' in handler


def test_the_download_path_is_what_the_tool_hands_back():
    """The terminal envelope carries the durable `/geotizer/files/` path and the tool uses `_terminal_outcome`."""
    terminal = (SERVICES / 'artifacts/geotizer/terminal.py').read_text(encoding='utf-8')

    assert '/geotizer/files/' in terminal
    assert '_terminal_outcome' in TOOL.read_text(encoding='utf-8')


def test_the_artifacts_are_also_attached_to_the_message():
    """`attachment_files` returns `file` records pointing at the durable download paths."""
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
        assert record['type'] == 'file'
        assert record['name'].startswith('Лекын-Тальбейская — ')
        assert record['content_type']


def test_the_word_card_attaches_beside_the_workbook_when_the_service_renders_one():
    """The docx attachment follows the xlsx and precedes the evidence files."""
    from open_webui.services.artifacts.geotizer.terminal import attachment_files

    files = attachment_files(
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        {
            'docx': '/api/v1/geotizer/files/run-1/geotizer.docx',
            'pdf': '/api/v1/geotizer/files/run-1/source_report.pdf',
            'markdown': '/api/v1/geotizer/files/run-1/source_report.md',
            'state': '/api/v1/geotizer/files/run-1/state.json',
        },
        object_name='Лекын-Тальбейская',
    )

    assert [f['url'] for f in files] == [
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        '/api/v1/geotizer/files/run-1/geotizer.docx',
        '/api/v1/geotizer/files/run-1/source_report.pdf',
        '/api/v1/geotizer/files/run-1/source_report.md',
        '/api/v1/geotizer/files/run-1/state.json',
    ]
    assert files[1]['content_type'] == (
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


def test_a_gis_service_that_renders_no_word_card_still_returns_every_other_link():
    """`_proxy_source_report_paths` returns the other report paths when `docx` is absent."""
    from open_webui.services.artifacts.geotizer.terminal import _proxy_source_report_paths

    without_docx = _proxy_source_report_paths(
        {
            'source_report': {
                'markdown': {'download_path': '/geotizer/files/run-1/source_report.md'},
                'pdf': {'download_path': '/geotizer/files/run-1/source_report.pdf'},
                'state': {'download_path': '/geotizer/files/run-1/state.json'},
            }
        }
    )

    assert set(without_docx) == {'markdown', 'pdf', 'state'}


def test_a_malformed_word_card_path_is_still_an_error():
    """`_proxy_source_report_paths` raises `GeotizerOrchestrationError` for a malformed `docx` path."""
    from open_webui.services.artifacts.geotizer.terminal import _proxy_source_report_paths
    from open_webui.services.geotizer.errors import GeotizerOrchestrationError

    with pytest.raises(GeotizerOrchestrationError):
        _proxy_source_report_paths(
            {
                'source_report': {
                    'markdown': {'download_path': '/geotizer/files/run-1/source_report.md'},
                    'pdf': {'download_path': '/geotizer/files/run-1/source_report.pdf'},
                    'state': {'download_path': '/geotizer/files/run-1/state.json'},
                    'docx': {'download_path': '/somewhere/else/geotizer.docx'},
                }
            }
        )


def test_every_served_artifact_can_be_attached():
    """`ARTIFACTS` and `ATTACHMENT_CONTENT_TYPES` name the same files with the same content types."""
    from open_webui.routers.geotizer import ARTIFACTS
    from open_webui.services.artifacts.geotizer.terminal import ATTACHMENT_CONTENT_TYPES

    assert set(ARTIFACTS) == set(ATTACHMENT_CONTENT_TYPES)
    for filename, (content_type, _prefix) in ARTIFACTS.items():
        assert ATTACHMENT_CONTENT_TYPES[filename] == content_type, filename


def test_an_unproxied_path_is_never_attached():
    """`attachment_files` attaches nothing for a raw `/geotizer/files/` path."""
    from open_webui.services.artifacts.geotizer.terminal import attachment_files

    assert attachment_files('/geotizer/files/run-1/geotizer.xlsx', None, object_name='X') == []


def test_the_attachment_never_replaces_the_download_link():
    """The `chat:message:files` emission is guarded by `except Exception` and the tool still returns its result."""
    source = TOOL.read_text(encoding='utf-8')
    start = source.index("'chat:message:files'")
    around = source[start - 600 : start + 400]

    assert 'except Exception' in around
    assert 'return result' in source[start:]


def test_chat_message_files_is_not_the_download_channel():
    """The tool emits `chat:message:files` from `attachment_files` records that point at `/api/v1` paths."""
    source = TOOL.read_text(encoding='utf-8')

    assert '__files__' in source
    assert 'chat:message:files' in source
    assert 'attachment_files' in source
    assert '/api/v1' in (SERVICES / 'artifacts/geotizer/terminal.py').read_text(encoding='utf-8')


def test_the_router_serves_no_artifact_it_does_not_declare():
    """Every artefact name the router serves is declared as a literal in the router."""
    source = ROUTER.read_text(encoding='utf-8')
    declared = {
        node.value for node in ast.walk(tree(ROUTER)) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert set(ARTIFACTS) <= declared
    assert 'ARTIFACTS' in source


def test_superseding_a_run_requires_an_admin():
    """`supersede_geotizer_run` depends on `get_admin_user` and `download_geotizer` on `get_verified_user`."""
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
    """The supersede actor comes from the session user and `SupersedeRunForm` carries no actor."""
    source = (REPO_ROOT / 'backend/open_webui/routers/geotizer.py').read_text(encoding='utf-8')
    body = source[source.index('async def supersede_geotizer_run') :]
    body = body[: body.index('\nasync def ')]

    assert "'actor':" in body
    assert 'user' in body.split("'actor':")[1].split('\n')[0]
    assert 'class SupersedeRunForm' in source
    assert 'actor' not in source[source.index('class SupersedeRunForm') : source.index('@router.post')]


UTILS_TOOLS = BACKEND / 'open_webui/utils/tools.py'

RETIRED_TOOL_IDS = ('mainagent_tool_yulong', 'sub_agent')


def _builtin_functions_appended() -> set[str]:
    """Every name `open_webui/utils/tools.py` appends or extends into `builtin_functions`, read from the AST."""
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
    """`fill_geotizer` is not added to `builtin_functions`."""
    assert 'fill_geotizer' not in _builtin_functions_appended()


def test_no_retired_workspace_tool_id_decides_what_a_model_is_shown():
    """No retired Workspace Tool id is a string literal in `open_webui/utils/tools.py`."""
    literals = {
        node.value
        for node in ast.walk(tree(UTILS_TOOLS))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    for retired in RETIRED_TOOL_IDS:
        assert retired not in literals, f'{retired} is still a live string in utils/tools.py'


def test_the_shim_calls_the_builtin_directly_rather_than_through_the_registry():
    """The build script imports `fill_geotizer` directly and never uses `get_tools`."""
    builder = (REPO_ROOT / 'scripts/build_geotizer_tool.py').read_text(encoding='utf-8')

    assert 'from open_webui.tools.geotizer import fill_geotizer' in builder
    assert 'get_tools' not in builder


def test_an_upstream_error_reaches_the_reader_as_a_sentence():
    """`_upstream_detail` unwraps a JSON `detail` one level, passes other bodies through as text, and bounds both to
    `UPSTREAM_ERROR_CHARS`.
    """
    from open_webui.routers.geotizer import UPSTREAM_ERROR_CHARS, _upstream_detail

    assert _upstream_detail(b'{"detail": "GeoTeaser XLSX not found."}') == (
        'GeoTeaser XLSX not found.'
    )
    assert _upstream_detail(b'<html>502 Bad Gateway</html>') == '<html>502 Bad Gateway</html>'
    assert _upstream_detail(b'{"error": "nope"}') == '{"error": "nope"}'
    assert _upstream_detail(b'{"detail": {"code": 7}}') == {'code': 7}
    assert len(_upstream_detail(b'x' * 5000)) == UPSTREAM_ERROR_CHARS
    long_detail = b'{"detail": "' + b'y' * 5000 + b'"}'
    assert len(_upstream_detail(long_detail)) == UPSTREAM_ERROR_CHARS
    assert _upstream_detail(b'\xff\xfe') != ''
