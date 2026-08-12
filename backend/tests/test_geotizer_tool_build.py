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
