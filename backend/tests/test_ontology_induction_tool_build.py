"""The generated ontology induction Workspace Tool shim: its content, its signature and its schema."""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import build_ontology_induction_tool as builder  # noqa: E402

COERCIONS = {'str', 'int', 'float', 'bool'}


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp('dist')
    manifest = builder.build(output, commit='0' * 40, allow_missing_spec=True)
    return manifest, (output / manifest['artifact']).read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def method(built):
    tree = ast.parse(built[1])
    [tools] = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    return next(node for node in tools.body if isinstance(node, ast.AsyncFunctionDef))


def test_the_manifest_records_the_digest_and_the_source_commit(built):
    manifest, artifact = built

    assert manifest['sha256'] == hashlib.sha256(artifact.encode('utf-8')).hexdigest()
    assert manifest['bytes'] == len(artifact.encode('utf-8'))
    assert manifest['source_commit'] == '0' * 40
    assert manifest['entrypoint'] == 'induce_ontology_vocabulary'


def test_the_shim_declares_no_requirements(built):
    assert 'requirements:' not in built[1]


def test_the_shim_holds_nothing_but_valves_coercion_and_the_call(built, method):
    tree = ast.parse(built[1])
    assert [type(node).__name__ for node in tree.body] == ['Expr', 'ImportFrom', 'ImportFrom', 'ImportFrom', 'ClassDef']
    [tools] = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [type(node).__name__ for node in tools.body] == ['ClassDef', 'FunctionDef', 'AsyncFunctionDef']
    docstring, returned = method.body
    assert isinstance(docstring, ast.Expr) and isinstance(returned, ast.Return)
    call = returned.value.value
    assert call.func.id == 'induce_ontology_vocabulary'
    for keyword in call.keywords:
        if keyword.arg.startswith('__'):
            assert isinstance(keyword.value, ast.Name) and keyword.value.id == keyword.arg
        else:
            assert isinstance(keyword.value, ast.Call) and keyword.value.func.id in COERCIONS


def test_the_shim_passes_files_straight_through(method):
    passed = {keyword.arg: keyword.value for keyword in method.body[1].value.value.keywords}

    assert isinstance(passed['__files__'], ast.Name) and passed['__files__'].id == '__files__'


def test_the_method_takes_the_builtins_model_facing_parameters_and_its_docstring(method):
    from open_webui.tools.ontology_induction import induce_ontology_vocabulary

    parameters = inspect.signature(induce_ontology_vocabulary).parameters.values()
    positional = [p.name for p in parameters if p.kind is p.POSITIONAL_OR_KEYWORD]
    shown = [arg.arg for arg in method.args.args if arg.arg != 'self' and not arg.arg.startswith('__')]
    assert shown == positional

    builtin_doc = inspect.getdoc(induce_ontology_vocabulary)
    shim_doc = ast.get_docstring(method)
    assert shim_doc.split('\n:param')[0].strip() == builtin_doc.split('\n:param')[0].strip()
    assert re.findall(r':param (\w+):', shim_doc) == positional


def test_every_keyword_only_parameter_is_a_valve_with_the_builtins_default(built):
    from open_webui.tools.ontology_induction import induce_ontology_vocabulary

    expected = {
        p.name.upper(): p.default
        for p in inspect.signature(induce_ontology_vocabulary).parameters.values()
        if p.kind is p.KEYWORD_ONLY and not p.name.startswith('__')
    }

    assert built[0]['valves'] == expected
    assert expected == {
        'MODEL_ID': '',
        'CHUNKS_PER_DOCUMENT': 3,
        'MIN_CHUNK_CHARS': 200,
        'MAX_DOCUMENTS': 0,
        'MODEL_TIMEOUT_SECONDS': 180,
        'MAX_EVIDENCE_PER_ITEM': 5,
        'INDUCTION_PROMPT': '',
    }


def test_the_model_is_shown_only_resume_file_id(built):
    try:
        spec = builder.tool_spec(built[1])
    except builder.SpecUnavailable as exc:
        pytest.skip(f'the tool spec generator is unavailable here: {exc}')

    [function] = spec
    assert function['name'] == 'induce_ontology_vocabulary'
    assert set(function['parameters']['properties']) == {'resume_file_id'}
    assert 'never invent one' in function['parameters']['properties']['resume_file_id']['description']
