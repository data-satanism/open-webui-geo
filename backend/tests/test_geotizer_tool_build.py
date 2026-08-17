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

    async def _noop_agent_caller(*args, **kwargs):  # noqa: ARG001
        # `_build_agent_caller` hands back the caller *and* the parsed
        # PRODUCER_KIND_MAP valve. Returning a bare `None` here raises the same
        # unpacking TypeError inside both the shim and the built-in, so the
        # comparison this fixture exists to make would pass on two identical
        # failures and prove nothing.
        return None, {}

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

    assert '- Режим: carry_forward — перенесено 339 из 343 заполненных ячеек\n' in card
    assert '  из запуска e4368779\n' in card
    # The gap between the two numbers is the only thing on the card that says
    # what this run found on its own, so both have to be legible, not just present.
    assert card.index('339') < card.index('343', card.index('Режим'))


@pytest.mark.asyncio
async def test_a_clean_card_still_says_it_is_clean(artifact, _stubbed_workflow):
    """The mode line is unconditional, and this is the case that makes it so.

    It would read better to print the line only when something was carried --
    and that is exactly the version that let a user believe a fresh `run_id`
    produced a fresh card. A reader cannot tell a real 40% from a padded 60%
    unless every card states which it is, so the quiet case says it too.
    """
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


# The three sentences that carry the operation. Pinned as text because the
# docstring is not documentation here -- it is the whole of what the model is
# told, and the reason a user's "start over" had nowhere to go was that none of
# this was said anywhere the model could read it.
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
    """Docstring prose with the wrapping taken out.

    The two copies are indented one level apart, so they wrap in different
    places while saying the same thing. Comparing the words rather than the
    lines is the difference between a test about the contract and a test about
    the formatter.
    """
    return ' '.join(text.split())


@pytest.mark.parametrize('sentence', THE_CONTRACT_SENTENCES)
def test_the_shim_and_the_builtin_say_the_same_thing_about_run_mode(artifact, sentence):
    """§3.2. Two docstrings, one contract.

    The shim's is what Open WebUI turns into the tool schema, so it is the only
    one the model ever sees; the built-in's is what a reader of this repository
    sees. Letting them drift means the sentence that governs behaviour is the
    one nobody reviews.
    """
    from open_webui.tools.geotizer import fill_geotizer

    assert sentence in _one_line(artifact)
    assert sentence in _one_line(fill_geotizer.__doc__ or '')


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


@pytest.mark.parametrize('sentence', THE_CONTRACT_SENTENCES)
def test_the_whole_parameter_description_reaches_the_generated_schema(artifact, sentence):
    """The docstring is only a contract if the model is shown all of it.

    `parse_docstring` matched `:param name: description` line by line and kept
    nothing after the first, so every wrapped parameter arrived truncated --
    `run_mode` reached the model as "clean or carry_forward. clean is the
    default and is what", cut mid-clause, with the rule that follows never
    shown. Asserting on the built spec rather than on the source is the point:
    the source was always right.
    """
    try:
        spec = builder.tool_spec(artifact)
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')

    function = spec[0]['function'] if 'function' in spec[0] else spec[0]
    descriptions = ' '.join(
        p.get('description', '') for p in function['parameters']['properties'].values()
    )

    assert _one_line(sentence.removeprefix(':param run_mode: ')) in _one_line(descriptions)


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


# -- S1.7: replacing, not just installing -------------------------------------


def test_a_first_install_creates_and_a_replacement_updates(built, monkeypatch):
    """`/tools/create` raises ID_TAKEN for an id that exists, so the create path
    installs a first copy and nothing else. Every real case is a replacement of
    `geoteaser`, which exists -- the install would have died on a 400 that says
    nothing about what went wrong."""
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
    """Not an omission -- `ToolForm` has no `valves` field, so `update_tool_by_id`
    never writes that column and the stored values survive the replacement.
    Sending one would be sending something the form would reject."""
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
    """The valve record can hold a credential. Key names and value *types* are
    enough for an operator to know what is riding on the tool; the values are
    theirs to save, outside Git."""
    described = installer.describe_valves({'API_KEY': 'sk-live-not-a-real-key', 'MAX_BATCHES': 12})

    assert 'sk-live-not-a-real-key' not in described
    assert '12' not in described
    assert 'API_KEY: str' in described and 'MAX_BATCHES: int' in described


def test_an_absent_valve_record_is_said_plainly_rather_than_guessed():
    assert installer.describe_valves(None) == 'no valves are stored for this tool'
    assert installer.describe_valves({}) == 'the valve record is present and empty'


# -- the card must measure its provenance, not assert it ----------------------


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
    """P0, and the one failure worse than a wrong number.

    A GIS image built before GT-GIS-01 drops `run_mode` on the way in -- no 422,
    no log line -- carries forward unconditionally, and returns a state with no
    provenance keys at all. The carried count is then zero because nothing was
    recorded, not because nothing was carried, and the card said "значения
    предыдущих запусков не переносились" over a card that had just reused them.
    A wrong completeness figure can be recomputed; a card that lies about its
    own provenance cannot be told apart from one that does not.
    """
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
    """The other side. `run_mode` present is the marker that GIS spoke, and a
    clean run legitimately has no `carry_forward` block at all -- the pass is
    skipped, not run and found empty."""
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
    """`unknown` is what a pre-GT-GIS-01 state loads as once the image is new
    enough to reconstruct one. Zero carried fields is then a real measurement,
    and the run still never declared a mode -- so the card may report the count
    and may not report the intent."""
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
    """The request said `clean`; the state says 71 came from another run. The
    state wins, because a mode the caller asked for is not a fact about the
    card."""
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
    """P1. `finalize` replays a completed run, so a `run_id` that names a
    finished run returns that card unchanged and is indistinguishable from a
    re-fill that found the same facts. Saying only "already finalized" would
    tell the reader what happened and not what to do."""
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
    """A run that reaches `finalized` the normal way is finalized too. Only a
    caller who supplied a `run_id` for a run that was already done needs telling."""
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
    """The silence was the defect. A user asked for a fresh card, got the
    previous run's id, coverage and link, and concluded the object could not be
    filled twice -- they were describing the behaviour accurately, because
    nothing on the card distinguished it from a run that had just happened.

    A reader looking at 59.8% needs to know they are looking at yesterday's.
    """
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
    """A state written before `finalized_at` existed has no stamp. The sentence
    still has to be sayable -- inventing "сегодня" would be the assertion this
    whole class of fix is against."""
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
    """Derived from the registry having resolved to a prior run, so a run that
    did happen must not claim it did not."""
    from open_webui.utils.plugin import load_tool_module_by_id

    async def _finished(**kwargs):  # noqa: ARG001
        return _payload(run_mode='clean')

    _stubbed_workflow.run_geotizer_workflow = _finished
    tools, _ = await load_tool_module_by_id('geoteaser_first_run', content=artifact)

    card = await tools.fill_geoteaser(**_runtime_context(), object_name='Лекын')

    assert 'уже выполнялся' not in card
