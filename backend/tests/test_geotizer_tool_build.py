"""S1.7 and S1.8: the built adapter, and loading it the way Open WebUI does.

Every other test in this suite imports modules. This one must not: it loads the
**built artefact** through `load_tool_module_by_id`, which is how the instance
loads what is stored in `webui.db`. That is the step that makes a two-build model
honest. A tool that passes unit tests and fails to load is a tool that does not
work, and nothing else here would catch it.

What is asserted:

  the artefact is generated, not written, so the adapter cannot quietly grow
  logic it is forbidden to hold;

  it loads, exposes exactly one model-callable method, and that method is
  `fill_geoteaser` -- the name the Skills and the prompts call;

  the generated schema comes from the docstring, so a prose edit is a contract
  change and shows up here;

  and the installer refuses to overwrite a Workspace copy it did not build.
"""

from __future__ import annotations

import ast
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


# -- S1.7: the build ---------------------------------------------------------


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
    """CORE-BOUNDARY-01's completion criterion, on the artefact rather than on
    the source: the DB tool contains no source, owner or audit logic."""
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
    """It emits custom `source` events; leaving citations on replaces them."""
    assert 'self.citation = False' in artifact


def test_the_adapter_says_where_it_came_from_and_not_to_edit_it(artifact):
    assert 'scripts/build_geotizer_tool.py' in artifact
    assert 'Do not edit in the Workspace' in artifact


def test_the_entrypoint_is_the_name_the_skills_call(artifact):
    """`fill_geoteaser` on the tool, `fill_geotizer` in this repository. Both
    names are real and neither may be renamed to match the other: the first
    belongs to the Skills and the prompts (register A-23)."""
    assert 'async def fill_geoteaser(' in artifact
    assert 'from open_webui.tools.geotizer import fill_geotizer' in artifact


# -- S1.8: the loader --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_built_artifact_loads_the_way_open_webui_loads_it(artifact):
    """Not an import -- `load_tool_module_by_id` with explicit content, which is
    the path a Workspace Tool actually takes out of the database."""
    from open_webui.utils.plugin import load_tool_module_by_id

    tools, frontmatter = await load_tool_module_by_id('geoteaser_test', content=artifact)

    assert frontmatter['title'] == 'GeoTeaser'
    assert frontmatter['version'] == builder.TOOL_VERSION
    assert frontmatter['required_open_webui_version'] == '0.10.0'
    assert callable(tools.fill_geoteaser)
    assert tools.citation is False


@pytest.mark.asyncio
async def test_the_loaded_tool_reaches_the_service(artifact):
    """One end-to-end call. It fails on the missing runtime context, which is
    the service answering -- an adapter that never reached it would raise
    instead, and a stub would answer something else."""
    from open_webui.utils.plugin import load_tool_module_by_id

    tools, _ = await load_tool_module_by_id('geoteaser_test_call', content=artifact)

    result = await tools.fill_geoteaser(object_name='Лекын-Тальбейская')

    assert 'missing_runtime_context' in result


# -- the shim forwards; it does not re-render --------------------------------
#
# The review asked for these two by name before the shim replaces the 5,111-line
# DB monolith: "the terminal result on success, and `_error_result` on failure".
# Both are stated the same way -- call the built-in and the loaded artefact with
# identical arguments and compare the strings -- because "forwards rather than
# re-renders" is exactly the claim that the two strings are the same string. A
# test that only asserted the shim's output *looks* like a GeoTeaser result
# would pass on a second renderer that had drifted.


@pytest.fixture
def _stubbed_workflow(monkeypatch):
    """Everything `fill_geotizer` reaches for, replaced at module scope.

    Module globals, not the imported name: the artefact binds `fill_geotizer`
    itself at import (`from ... import fill_geotizer`), so patching that name
    would miss the shim entirely and the test would compare the built-in against
    itself. What `fill_geotizer` looks up at call time is its own module's
    globals, which both callers share.
    """
    from open_webui.tools import geotizer

    async def _noop_caller(*args, **kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(geotizer, '_user_model', _noop_caller)
    monkeypatch.setattr(geotizer, '_resolve_geotizer_callable', _noop_caller)
    monkeypatch.setattr(geotizer, '_build_agent_caller', _noop_caller)
    monkeypatch.setattr(geotizer, '_build_rag_dispatcher', lambda *a, **k: None)  # noqa: ARG005
    monkeypatch.setattr(geotizer, '_build_vision_evidence_caller', _noop_caller)
    return geotizer


def _runtime_context():
    return {'__request__': object(), '__user__': {'id': 'u1'}}


@pytest.mark.asyncio
async def test_the_shim_hands_back_the_terminal_result_unchanged(artifact, _stubbed_workflow):
    """Success. The built-in composes the Russian completeness summary and the
    download links; the shim must return that string and add nothing."""
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
    # Stated positively, so the pair cannot both pass on two empty strings.
    assert 'GeoTeaser' in through_the_shim
    assert 'run-42' in through_the_shim


@pytest.mark.asyncio
async def test_the_card_says_how_much_of_it_came_from_another_run(artifact, _stubbed_workflow):
    """GT-GIS-01. Run `e4368779` reported 343/351 filled and 339 of those were
    carried from a previous card. A completeness figure that does not say so
    reads as "this run found 343 facts" and means "this run found four"."""
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

    assert '343' in card
    assert '339' in card, 'the carried count is not on the card'
    assert '4' in card, 'the count this run actually found is not on the card'
    assert 'e4368779' in card, 'the donor run is not named'
    assert 'carry_forward' in card


@pytest.mark.asyncio
async def test_a_clean_card_does_not_grow_a_carry_forward_line(artifact, _stubbed_workflow):
    """The common case stays quiet. A line saying "carried: 0" on every clean
    card is noise that trains a reader to skip the line that matters."""
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
    assert 'Режим прогона: clean' in card


@pytest.mark.asyncio
async def test_the_shim_hands_back_the_error_envelope_unchanged(artifact, _stubbed_workflow):
    """Failure. `_error_result` is a JSON envelope the parent model parses --
    `status`, `code`, `run_id`, `resumable`. If the shim let the exception out
    instead, Open WebUI would surface a traceback and `resumable` would be lost
    with it, so a run that could be resumed would look like one that could not.
    """
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


def test_the_generated_schema_comes_from_the_docstring(artifact):
    """The docstring is the contract the model is shown. Generating the spec
    needs the retrieval stack, so where `backend/requirements.txt` is not
    installed this reports as skipped rather than passing on nothing."""
    try:
        spec = builder.tool_spec(artifact)
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')

    assert len(spec) == 1
    function = spec[0]['function'] if 'function' in spec[0] else spec[0]
    assert function['name'] == 'fill_geoteaser'
    assert 'GeoTeaser' in function['description']
    assert 'object_name' in function['parameters']['properties']
    assert function['parameters']['required'] == ['object_name']


# -- S1.7: the installer refuses ---------------------------------------------


def test_an_absent_tool_is_installed(built):
    _, manifest = built

    assert installer.classify(None, manifest) == (installer.ABSENT, None)


def test_the_same_digest_is_already_installed(built, artifact):
    _, manifest = built

    state, found = installer.classify(artifact, manifest)

    assert state == installer.CURRENT
    assert found == manifest['sha256']


def test_an_unrecognised_workspace_copy_is_refused(built):
    """The rule the installer exists for. An unexpected digest means someone
    changed production, and overwriting it destroys the only copy."""
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
    """Arguments are visible in the process table and land in shell history."""
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


# -- the installer holds an admin credential, so where it sends it matters ---


def _loopback(handler_factory):
    """A throwaway HTTP server on 127.0.0.1, returned with its port."""
    import http.server
    import threading

    server = http.server.HTTPServer(('127.0.0.1', 0), handler_factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_port


def test_the_admin_credential_is_not_handed_to_a_redirect_target():
    """`urlopen` follows 3xx and copies the request headers onto the follow-up.

    A redirect from the operator-supplied `--url` therefore used to send a live
    `Authorization: Bearer <admin key>` to whatever host the `Location` named.
    Two loopback servers here: the second records anything it receives, and must
    receive nothing.
    """
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
    """A hung install must fail rather than wait forever holding the credential."""
    assert installer.REQUEST_TIMEOUT_SECONDS > 0
    source = (REPO_ROOT / 'scripts/install_geotizer_tool.py').read_text(encoding='utf-8')
    assert 'timeout=REQUEST_TIMEOUT_SECONDS' in source
    # The default opener follows redirects; the installer may not use it.
    assert 'urllib.request.urlopen(' not in source
