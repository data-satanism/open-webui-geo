"""Tests for the built GeoTeaser Workspace Tool artefact, its loading through `load_tool_module_by_id`, and its
installer.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import build_geotizer_tool as builder  # noqa: E402
import install_geotizer_tool as installer  # noqa: E402

FORBIDDEN_IN_THE_ADAPTER = (
    'source policy',
    'validate_owner_envelope',
    'owner_submission',
    'audit_projection',
    'build_retrieval_plans',
    'MAX_OWNER_ATTEMPTS',
)


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp('dist')
    manifest = builder.build(output, commit='0' * 40, allow_missing_spec=True)
    return output, manifest


@pytest.fixture(scope='module')
def artifact(built):
    output, manifest = built
    return (output / manifest['artifact']).read_text(encoding='utf-8')


def test_the_manifest_records_version_digest_and_source_commit(built, artifact):
    _, manifest = built

    assert manifest['version'] == builder.TOOL_VERSION
    assert manifest['sha256'] == hashlib.sha256(artifact.encode('utf-8')).hexdigest()
    assert manifest['bytes'] == len(artifact.encode('utf-8'))
    assert manifest['source_commit'] == '0' * 40
    assert manifest['entrypoint'] == 'fill_geoteaser'


def test_the_build_is_reproducible_from_the_same_commit(built):
    output, manifest = built

    again = builder.build(output, commit='0' * 40, allow_missing_spec=True)

    assert again['sha256'] == manifest['sha256']


def test_the_adapter_holds_no_logic_it_is_forbidden_to_hold(artifact):
    """The built artefact contains none of the source, owner or audit logic names in `FORBIDDEN_IN_THE_ADAPTER`."""
    for forbidden in FORBIDDEN_IN_THE_ADAPTER:
        assert forbidden not in artifact, forbidden


def test_the_adapter_is_one_class_with_one_public_method(artifact):
    tree = ast.parse(artifact)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]

    assert [c.name for c in classes] == ['Tools']
    methods = [
        n.name
        for n in classes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('_')
    ]
    assert methods == ['fill_geoteaser']


def test_the_adapter_turns_automatic_citations_off(artifact):
    """The artefact sets `self.citation = False`."""
    assert 'self.citation = False' in artifact


def test_the_adapter_says_where_it_came_from_and_not_to_edit_it(artifact):
    assert 'scripts/build_geotizer_tool.py' in artifact
    assert 'Do not edit in the Workspace' in artifact


def test_the_entrypoint_is_the_name_the_skills_call(artifact):
    """The artefact defines `fill_geoteaser` and imports `fill_geotizer` from `open_webui.tools.geotizer`."""
    assert 'async def fill_geoteaser(' in artifact
    assert 'from open_webui.tools.geotizer import fill_geotizer' in artifact


def _generated_schema(artifact):
    """The function spec `builder.tool_spec` generates from the built artefact; skips the test when the spec generator
    is unavailable.
    """
    try:
        spec = builder.tool_spec(artifact)
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')
    function = spec[0]['function'] if 'function' in spec[0] else spec[0]
    return function


def test_the_model_is_shown_licence_id(artifact):
    """The generated schema shows `licence_id` and `licence_layer_id`."""
    properties = _generated_schema(artifact)['parameters']['properties']

    assert 'licence_id' in properties
    assert 'licence_layer_id' in properties


def test_the_guess_guard_survives_its_own_wrapping(artifact):
    """The generated `licence_id` description keeps the whole wrapped guard against guessing a licence number."""
    described = _generated_schema(artifact)['parameters']['properties']['licence_id']['description']

    assert 'never construct or guess one' in described
    assert 'wrong polygon' in described


def test_object_name_is_optional_on_the_tool_the_model_calls(artifact):
    """The generated schema has no required parameters."""
    parameters = _generated_schema(artifact)['parameters']

    assert not (parameters.get('required') or [])


def test_the_tool_and_the_builtin_take_the_same_parameters(artifact):
    """The generated schema's parameters equal `fill_geotizer`'s non-dunder parameters."""
    import inspect

    from open_webui.tools.geotizer import fill_geotizer

    shown = set(_generated_schema(artifact)['parameters']['properties'])
    accepted = {
        name
        for name in inspect.signature(fill_geotizer).parameters
        if not name.startswith('__')
    }

    assert shown == accepted, {
        'only the model sees': sorted(shown - accepted),
        'only the built-in accepts': sorted(accepted - shown),
    }


@pytest.mark.asyncio
async def test_both_licence_arguments_reach_the_service(artifact, _stubbed_workflow):
    """`licence_id`, `licence_layer_id` and `project_id` passed to the loaded tool reach `run_geotizer_workflow`, with
    an empty `object_name`.
    """
    from open_webui.utils.plugin import load_tool_module_by_id

    seen: dict = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        raise RuntimeError('captured')

    _stubbed_workflow.run_geotizer_workflow = _capture
    tools, _ = await load_tool_module_by_id('geoteaser_forward', content=artifact)

    with contextlib.suppress(Exception):
        await tools.fill_geoteaser(
            project_id='lekyn',
            licence_id='МАГ04805БЭ',
            licence_layer_id='Licenses_2024_2025',
            **_runtime_context(),
        )

    assert seen, 'the workflow was never reached'

    assert seen['licence_id'] == 'МАГ04805БЭ'
    assert seen['licence_layer_id'] == 'Licenses_2024_2025'
    assert seen['project_id'] == 'lekyn'
    assert seen['object_name'] == '', 'a licence-only call carries no name, and that is the point'


@pytest.mark.asyncio
async def test_the_run_is_told_which_build_made_it(artifact, _stubbed_workflow):
    """The loaded tool passes `build_revision()` to `run_geotizer_workflow`."""
    from open_webui.build_revision import build_revision
    from open_webui.utils.plugin import load_tool_module_by_id

    seen: dict = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        raise RuntimeError('captured')

    _stubbed_workflow.run_geotizer_workflow = _capture
    tools, _ = await load_tool_module_by_id('geoteaser_forward', content=artifact)

    with contextlib.suppress(Exception):
        await tools.fill_geoteaser(
            project_id='lekyn',
            object_name='Нявленга',
            **_runtime_context(),
        )

    assert seen, 'the workflow was never reached'
    assert 'build_revision' in seen, 'the adapter dropped it'
    assert seen['build_revision'] == build_revision()
    assert set(seen['build_revision']) >= {'revision', 'dirty', 'source'}


@pytest.mark.asyncio
async def test_the_built_artifact_loads_the_way_open_webui_loads_it(artifact):
    """The artefact loads through `load_tool_module_by_id` with its frontmatter and citations off."""
    from open_webui.utils.plugin import load_tool_module_by_id

    tools, frontmatter = await load_tool_module_by_id('geoteaser_test', content=artifact)

    assert frontmatter['title'] == 'GeoTeaser'
    assert frontmatter['version'] == builder.TOOL_VERSION
    assert frontmatter['required_open_webui_version'] == '0.10.0'
    assert callable(tools.fill_geoteaser)
    assert tools.citation is False


@pytest.mark.asyncio
async def test_the_loaded_tool_reaches_the_service(artifact):
    """A loaded-tool call without runtime context returns `missing_runtime_context`."""
    from open_webui.utils.plugin import load_tool_module_by_id

    tools, _ = await load_tool_module_by_id('geoteaser_test_call', content=artifact)

    result = await tools.fill_geoteaser(object_name='Лекын-Тальбейская')

    assert 'missing_runtime_context' in result


@pytest.fixture
def _stubbed_workflow(monkeypatch):
    """Replace the callers `fill_geotizer` looks up in its module globals with no-op stubs."""
    from open_webui.tools import geotizer

    async def _noop_caller(*args, **kwargs):  # noqa: ARG001
        return None

    async def _noop_agent_caller(*args, **kwargs):  # noqa: ARG001
        return None, {}, None

    monkeypatch.setattr(geotizer, '_user_model', _noop_caller)
    monkeypatch.setattr(geotizer, '_resolve_geotizer_callable', _noop_caller)
    monkeypatch.setattr(geotizer, '_build_agent_caller', _noop_agent_caller)
    monkeypatch.setattr(geotizer, '_build_rag_dispatcher', lambda *a, **k: None)  # noqa: ARG005
    monkeypatch.setattr(geotizer, '_build_vision_evidence_caller', _noop_caller)
    return geotizer


def _runtime_context():
    return {'__request__': object(), '__user__': {'id': 'u1'}}


@pytest.mark.asyncio
async def test_the_shim_hands_back_the_terminal_result_unchanged(artifact, _stubbed_workflow):
    """On success the shim returns exactly the built-in's result string."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return {
            'object_name': 'Лекын-Тальбейская площадь',
            'run_id': 'run-42',
            'counts': {'filled': 300, 'not_found': 40, 'requires_expert_review': 11},
            'fill_quality': {'strict_fill_percent': 85.4, 'target_met': True},
            'xlsx': {'sha256': 'a' * 64, 'download_path': '/geotizer/files/run-42/geotizer.xlsx'},
            'audit': {'passed': True, 'failed': [], 'warnings': []},
            'status': 'completed',
        }

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_shim_ok', content=artifact)

    through_the_shim = await tools.fill_geoteaser(object_name='Лекын', **_runtime_context())
    from_the_builtin = await _stubbed_workflow.fill_geotizer(
        object_name='Лекын', **_runtime_context()
    )

    assert through_the_shim == from_the_builtin
    assert 'GeoTeaser' in through_the_shim
    assert 'run-42' in through_the_shim


@pytest.mark.asyncio
async def test_the_card_says_how_much_of_it_came_from_another_run(artifact, _stubbed_workflow):
    """A carry-forward card states the carried count, the filled count and the parent run."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _carried(**kwargs):  # noqa: ARG001
        return {
            'object_name': 'Лекын',
            'run_id': 'run-new',
            'counts': {'filled': 343, 'not_found': 8, 'requires_expert_review': 0},
            'fill_quality': {'strict_fill_percent': 97.7, 'target_met': True},
            'xlsx': {'sha256': 'a' * 64, 'download_path': '/geotizer/files/run-new/geotizer.xlsx'},
            'audit': {'passed': True, 'failed': [], 'warnings': []},
            'run_mode': 'carry_forward',
            'carry_forward_mode': 'direct_only',
            'carry_forward': {
                'policy_version': 'geotizer_carry_forward.v2',
                'mode': 'direct_only',
                'parent_run_ids': ['e4368779'],
                'carried_field_count': 339,
                'carried_field_keys': [],
                'refused_transitive_field_count': 0,
            },
        }

    _stubbed_workflow.run_geotizer_workflow = _carried
    tools, _ = await load_tool_module_by_id('geoteaser_carry', content=artifact)

    card = await tools.fill_geoteaser(object_name='Лекын', **_runtime_context())

    assert '- Режим: carry_forward — перенесено 339 из 343 заполненных ячейки\n' in card
    assert '  из запуска e4368779\n' in card
    assert card.index('339') < card.index('343', card.index('Режим'))


@pytest.mark.asyncio
async def test_a_clean_card_still_says_it_is_clean(artifact, _stubbed_workflow):
    """A clean run's card carries the clean mode line."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _clean(**kwargs):  # noqa: ARG001
        return {
            'object_name': 'Лекын',
            'run_id': 'run-new',
            'counts': {'filled': 42},
            'fill_quality': {'strict_fill_percent': 12.0, 'target_met': False},
            'xlsx': {'sha256': 'a' * 64, 'download_path': '/geotizer/files/run-new/geotizer.xlsx'},
            'audit': {'passed': True, 'failed': [], 'warnings': []},
            'run_mode': 'clean',
            'carry_forward_mode': 'disabled',
            'carry_forward': {'mode': 'disabled', 'parent_run_ids': [], 'carried_field_count': 0},
        }

    _stubbed_workflow.run_geotizer_workflow = _clean
    tools, _ = await load_tool_module_by_id('geoteaser_clean', content=artifact)

    card = await tools.fill_geoteaser(object_name='Лекын', **_runtime_context())

    assert 'перенесено' not in card
    assert '- Режим: clean (значения предыдущих запусков не переносились)\n' in card


@pytest.mark.asyncio
async def test_the_shim_hands_back_the_error_envelope_unchanged(artifact, _stubbed_workflow):
    """On failure the shim returns exactly the built-in's JSON error envelope, with `resumable` set."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _refuses(**kwargs):  # noqa: ARG001
        raise RuntimeError('GIS сервис недоступен')

    _stubbed_workflow.run_geotizer_workflow = _refuses
    tools, _ = await load_tool_module_by_id('geoteaser_shim_err', content=artifact)

    through_the_shim = await tools.fill_geoteaser(
        object_name='Лекын', run_id='run-7', **_runtime_context()
    )
    from_the_builtin = await _stubbed_workflow.fill_geotizer(
        object_name='Лекын', run_id='run-7', **_runtime_context()
    )

    assert through_the_shim == from_the_builtin
    envelope = json.loads(through_the_shim)
    assert envelope['status'] == 'geotizer_failed'
    assert envelope['code'] == 'RuntimeError'
    assert envelope['run_id'] == 'run-7'
    assert envelope['resumable'] is True


THE_CONTRACT_SENTENCES = (
    'Never invent one, and never send one to start over — a new run_id does '
    'not produce a clean run. Use run_mode for that.',
    ':param run_mode: clean or carry_forward. clean is the default and is what '
    '"fill it again", "start over" or "заново" means: the card is built only '
    'from evidence found in this run.',
    'carry_forward additionally reuses values from previous finalized runs of '
    'the same object, which raises the completeness figure without adding evidence.',
    'Send carry_forward only when the user explicitly asks to keep the previous values.',
)


def _one_line(text: str) -> str:
    """Docstring prose with the wrapping taken out."""
    return ' '.join(text.split())


@pytest.mark.parametrize('sentence', THE_CONTRACT_SENTENCES)
def test_the_shim_and_the_builtin_say_the_same_thing_about_run_mode(artifact, sentence):
    """Each contract sentence appears in both the artefact and `fill_geotizer.__doc__`."""
    from open_webui.tools.geotizer import fill_geotizer

    assert sentence in _one_line(artifact)
    assert sentence in _one_line(fill_geotizer.__doc__ or '')


def test_the_generated_schema_comes_from_the_docstring(artifact):
    """The generated spec is one `fill_geoteaser` function with no required parameters; skipped where the spec generator
    is unavailable.
    """
    try:
        spec = builder.tool_spec(artifact)
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')

    assert len(spec) == 1
    function = spec[0]['function'] if 'function' in spec[0] else spec[0]
    assert function['name'] == 'fill_geoteaser'
    assert 'GeoTeaser' in function['description']
    assert 'object_name' in function['parameters']['properties']
    assert not (function['parameters'].get('required') or [])


@pytest.mark.parametrize('sentence', THE_CONTRACT_SENTENCES)
def test_the_whole_parameter_description_reaches_the_generated_schema(artifact, sentence):
    """Each contract sentence reaches the generated parameter descriptions whole."""
    try:
        spec = builder.tool_spec(artifact)
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')

    function = spec[0]['function'] if 'function' in spec[0] else spec[0]
    descriptions = ' '.join(
        p.get('description', '') for p in function['parameters']['properties'].values()
    )

    assert _one_line(sentence.removeprefix(':param run_mode: ')) in _one_line(descriptions)


def test_an_absent_tool_is_installed(built):
    _, manifest = built

    assert installer.classify(None, manifest) == (installer.ABSENT, None)


def test_the_same_digest_is_already_installed(built, artifact):
    _, manifest = built

    state, found = installer.classify(artifact, manifest)

    assert state == installer.CURRENT
    assert found == manifest['sha256']


def test_an_unrecognised_workspace_copy_is_refused(built):
    """The installer classifies a Workspace copy with an unknown digest as `UNRECOGNISED`."""
    _, manifest = built

    state, found = installer.classify('# someone edited this in the Workspace\n', manifest)

    assert state == installer.UNRECOGNISED
    assert found and found != manifest['sha256']


def test_a_digest_from_an_earlier_build_is_an_upgrade(built, monkeypatch):
    _, manifest = built
    earlier = '# an older build\n'
    monkeypatch.setitem(installer.KNOWN_BUILD_DIGESTS, installer.digest(earlier), '2.9.0')

    state, _ = installer.classify(earlier, manifest)

    assert state == installer.KNOWN_BUILD


def test_the_installer_never_takes_a_credential_on_the_command_line():
    """The installer takes the credential through `--token-file` and has no `--token` or `--api-key` option."""
    source = (REPO_ROOT / 'scripts/install_geotizer_tool.py').read_text(encoding='utf-8')
    tree = ast.parse(source)

    options = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'add_argument'
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert '--token-file' in options
    assert '--token' not in options
    assert '--api-key' not in options


def test_the_manifest_carries_no_secret(built):
    _, manifest = built

    assert 'token' not in json.dumps(manifest).lower()
    assert 'api_key' not in json.dumps(manifest).lower()


def _loopback(handler_factory):
    """A throwaway HTTP server on 127.0.0.1, returned with its port."""
    import http.server
    import threading

    server = http.server.HTTPServer(('127.0.0.1', 0), handler_factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_port


def test_the_admin_credential_is_not_handed_to_a_redirect_target():
    """`fetch_installed` refuses a redirect and sends nothing to its target."""
    import http.server
    import urllib.error

    received: list[tuple[str, str | None]] = []

    class Attacker(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            received.append((self.path, self.headers.get('Authorization')))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"content": "pwned"}')

        def log_message(self, *args):  # noqa: ARG002
            pass

    attacker, attacker_port = _loopback(Attacker)

    class Victim(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{attacker_port}/stolen')
            self.end_headers()

        def log_message(self, *args):  # noqa: ARG002
            pass

    victim, victim_port = _loopback(Victim)

    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            installer.fetch_installed(
                f'http://127.0.0.1:{victim_port}', 'ADMIN-KEY-NOT-A-REAL-SECRET', 'geoteaser'
            )
        assert 'refusing to follow' in str(excinfo.value)
    finally:
        victim.shutdown()
        attacker.shutdown()

    assert received == [], f'the credential reached the redirect target: {received}'


def test_every_request_carries_a_timeout():
    """Every installer request carries `REQUEST_TIMEOUT_SECONDS` and none goes through `urllib.request.urlopen`."""
    assert installer.REQUEST_TIMEOUT_SECONDS > 0
    source = (REPO_ROOT / 'scripts/install_geotizer_tool.py').read_text(encoding='utf-8')
    assert 'timeout=REQUEST_TIMEOUT_SECONDS' in source
    assert 'urllib.request.urlopen(' not in source


def test_a_first_install_creates_and_a_replacement_updates(built, monkeypatch):
    """`install` posts to `/tools/create` and `replace` posts to `/tools/id/<tool_id>/update`."""
    _, manifest = built
    seen: list[tuple[str, str]] = []

    def _record(url, token, method='GET', payload=None):  # noqa: ARG001
        seen.append((method, url))
        return {}

    monkeypatch.setattr(installer, '_request', _record)

    installer.install('http://x', 't', manifest, '# c')
    installer.replace('http://x', 't', manifest, '# c')

    assert seen[0] == ('POST', 'http://x/api/v1/tools/create')
    assert seen[1] == ('POST', f'http://x/api/v1/tools/id/{manifest["tool_id"]}/update')


def test_the_update_payload_carries_no_valves_field():
    """`ToolForm` has no `valves` field and the installer payload carries only `id`, `name`, `content` and `meta`."""
    form = ast.parse(
        (REPO_ROOT / 'backend/open_webui/models/tools.py').read_text(encoding='utf-8')
    )
    fields = {
        node.target.id
        for definition in ast.walk(form)
        if isinstance(definition, ast.ClassDef) and definition.name == 'ToolForm'
        for node in definition.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert fields and 'valves' not in fields
    payload = installer._payload({'tool_id': 'geoteaser', 'name': 'GeoTeaser', 'version': '3.0.0',
                                  'sha256': 'x', 'source_repository': 'r', 'source_commit': 'c'}, '# c')
    assert set(payload) == {'id', 'name', 'content', 'meta'}


def test_no_valve_value_is_ever_printed():
    """`describe_valves` prints valve key names and value types, never values."""
    described = installer.describe_valves({'API_KEY': 'sk-live-not-a-real-key', 'MAX_BATCHES': 12})

    assert 'sk-live-not-a-real-key' not in described
    assert '12' not in described
    assert 'API_KEY: str' in described and 'MAX_BATCHES: int' in described


def test_an_absent_valve_record_is_said_plainly_rather_than_guessed():
    assert installer.describe_valves(None) == 'no valves are stored for this tool'
    assert installer.describe_valves({}) == 'the valve record is present and empty'


def _payload(**overrides):
    base = {
        'object_name': 'Лекын-Тальбейская площадь',
        'run_id': 'run-1',
        'counts': {'filled': 210, 'not_found': 141, 'requires_expert_review': 0},
        'fill_quality': {'strict_fill_percent': 59.8, 'target_met': False},
        'xlsx': {'sha256': 'a' * 64, 'download_path': '/geotizer/files/run-1/geotizer.xlsx'},
        'audit': {'passed': True, 'failed': [], 'warnings': []},
        'status': 'completed',
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_a_run_that_declared_no_mode_does_not_get_a_clean_card(
    artifact, _stubbed_workflow
):
    """A result with no `run_mode` gets the «не записан» mode line, not the clean one."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload()

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_no_mode', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert 'не переносились' not in card
    assert '- Режим: не записан' in card
    assert 'сборка GIS старше GT-GIS-01' in card


@pytest.mark.asyncio
async def test_a_run_that_declared_clean_still_gets_the_clean_card(
    artifact, _stubbed_workflow
):
    """A result with `run_mode` `clean` and no `carry_forward` block gets the clean mode line."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='clean', carry_forward_mode='disabled', carry_forward=None)

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_clean_mode', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert '- Режим: clean (значения предыдущих запусков не переносились)' in card


@pytest.mark.asyncio
async def test_a_migrated_run_that_carried_nothing_is_still_not_clean(
    artifact, _stubbed_workflow
):
    """A result with `run_mode` `unknown` gets the «не записан» mode line."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='unknown', carry_forward={'carried_field_keys': []})

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_unknown_mode', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert '- Режим: не записан' in card
    assert 'не переносились' not in card


@pytest.mark.asyncio
async def test_the_carried_count_is_read_from_state_not_from_the_request(
    artifact, _stubbed_workflow
):
    """The carried count on the card comes from the result state, not from the requested `run_mode`."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(
            run_mode='carry_forward',
            carry_forward={
                'carried_field_keys': [f'k{n}' for n in range(71)],
                'parent_run_ids': ['b6d15646-af78-488a-aff7-ed7a4bdd76e8'],
            },
        )

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_carried', content=artifact)

    card = await tools.fill_geoteaser(
        **_runtime_context(), object_name='Лекын', run_mode='clean'
    )

    assert 'перенесено 71 из 210 заполненных ячеек' in card
    assert 'b6d15646-af78-488a-aff7-ed7a4bdd76e8' in card


@pytest.mark.asyncio
async def test_resuming_a_finished_run_says_so_and_names_the_alternatives(
    artifact, _stubbed_workflow
):
    """A resumed already-finalized run's card opens by saying so and names the alternatives."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(
            run_mode='clean', resumed_run_was_already_finalized=True, run_id='run-9'
        )

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_replayed', content=artifact)

    card = await tools.fill_geoteaser(
        **_runtime_context(), object_name='Лекын', run_id='run-9'
    )

    assert card.startswith('Прогон run-9 уже завершён')
    assert 'не передавайте run_id' in card
    assert 'run_mode="carry_forward"' in card


@pytest.mark.asyncio
async def test_an_ordinary_run_does_not_carry_the_replay_note(artifact, _stubbed_workflow):
    """A run that was not a replay carries no replay note."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='clean')

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_ordinary', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert 'уже завершён' not in card


@pytest.mark.asyncio
async def test_a_card_served_from_the_registry_says_so_above_the_numbers(
    artifact, _stubbed_workflow
):
    """A card reused from the registry opens with a reuse sentence naming the run and its finalization date."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(
            run_mode='clean',
            reused_run_from_registry='run-1',
            finalized_at='2026-08-15T09:00:00+00:00',
        )

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_reused', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert card.startswith('Этот прогон уже выполнялся')
    assert 'карточка прогона run-1 от 2026-08-15T09:00:00+00:00' in card
    assert 'Новый прогон не запускался' in card
    assert card.index('уже выполнялся') < card.index('Заполнено')


@pytest.mark.asyncio
async def test_a_reused_card_without_a_finalization_date_omits_the_date(
    artifact, _stubbed_workflow
):
    """A reused card with no `finalized_at` omits the date from the reuse sentence."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='clean', reused_run_from_registry='run-1')

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_reused_undated', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert 'карточка прогона run-1. ' in card
    assert ' от ' not in card.split('\n')[0]


@pytest.mark.asyncio
async def test_a_first_run_carries_no_reuse_sentence(artifact, _stubbed_workflow):
    """A run not reused from the registry carries no reuse sentence."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='clean')

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_first_run', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert 'уже выполнялся' not in card
