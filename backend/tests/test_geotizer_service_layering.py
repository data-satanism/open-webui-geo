"""No module in the pure core imports one that sits in a higher layer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = REPO_ROOT / 'backend/open_webui/services'
PACKAGE = 'open_webui.services'

LAYERS = {
    'open_webui.services.geotizer.errors': 0,
    'open_webui.services.geotizer.semantics': 1,
    'open_webui.services.core.text': 1,
    'open_webui.services.core.tasks': 1,
    'open_webui.services.core.vocabulary': 1,
    'open_webui.services.core.idempotency': 1,
    'open_webui.services.core.deadline': 1,
    'open_webui.services.artifacts.geotizer.validation': 1,
    'open_webui.services.project_evidence.claims': 1,
    'open_webui.services.project_evidence.agreement': 1,
    'open_webui.services.project_evidence.dossier': 1,
    'open_webui.services.project_evidence.resource_coherence': 2,
    'open_webui.services.project_evidence.retrieval': 2,
    'open_webui.services.project_evidence.proposals': 3,
    'open_webui.services.artifacts.geotizer.vision': 2,
    'open_webui.services.artifacts.geotizer.prompts': 3,
    'open_webui.services.artifacts.geotizer.owner_envelope': 4,
    'open_webui.services.artifacts.geotizer.terminal': 5,
    'open_webui.services.artifacts.geotizer.observability': 5,
    'open_webui.services.artifacts.geotizer.workflow': 6,
    'open_webui.services.artifacts.geotizer.run_scope': 1,
    'open_webui.services.artifacts.geotizer.area_workflow': 7,
    'open_webui.services.artifacts.geotizer.area_request': 8,
    'open_webui.services.artifacts.geotizer.project': 5,
    'open_webui.services.artifacts.cpr.errors': 1,
    'open_webui.services.artifacts.cpr.catalog': 4,
    'open_webui.services.artifacts.cpr.requirements': 5,
    'open_webui.services.artifacts.cpr.coverage': 6,
    'open_webui.services.artifacts.cpr.project': 6,
    'open_webui.services.artifacts.cpr.narrative': 6,
    'open_webui.services.artifacts.cpr.audit': 7,
    'open_webui.services.artifacts.cpr.render': 8,
    'open_webui.services.artifacts.consistency': 9,
    'open_webui.services.evaluation.rag_ab': 10,
}


def module_name(path: Path) -> str:
    relative = path.relative_to(SERVICES).with_suffix('')
    return f'{PACKAGE}.' + relative.as_posix().replace('/', '.')


def modules() -> list[Path]:
    """Every module in the pure core; fails an assertion when the tree is missing or empty."""
    assert SERVICES.is_dir(), SERVICES
    found = [p for p in sorted(SERVICES.rglob('*.py')) if '__pycache__' not in p.parts]
    assert found, f'no modules under {SERVICES}; these tests would pass by looking at nothing'
    return found


def imported_modules(path: Path) -> list[str]:
    """Every sibling module this one imports, absolute or relative."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    own = module_name(path).split('.')
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0:
            if node.module and node.module.startswith(PACKAGE):
                found.append(node.module)
            continue
        base = own[: len(own) - node.level]
        found.append('.'.join(base + ([node.module] if node.module else [])))
    return found


def test_every_module_has_a_layer():
    """Every module in the pure core has an entry in `LAYERS`, and every entry has a module."""
    assert {module_name(p) for p in modules()} == set(LAYERS)


@pytest.mark.parametrize('path', modules(), ids=module_name)
def test_no_module_imports_from_a_higher_layer(path):
    source = module_name(path)
    for target in imported_modules(path):
        assert target in LAYERS, f'{source} imports unmapped {target}'
        assert LAYERS[target] <= LAYERS[source], f'{source} -> {target}'


def test_the_evidence_core_never_imports_an_artifact():
    """No `project_evidence` module imports an `artifacts` module."""
    for path in modules():
        source = module_name(path)
        if not source.startswith(f'{PACKAGE}.project_evidence'):
            continue
        for target in imported_modules(path):
            assert not target.startswith(f'{PACKAGE}.artifacts'), f'{source} -> {target}'


def test_nothing_imports_the_evaluation_layer():
    """No module outside `evaluation` imports an `evaluation` module."""
    for path in modules():
        source = module_name(path)
        if source.startswith(f'{PACKAGE}.evaluation'):
            continue
        for target in imported_modules(path):
            assert not target.startswith(f'{PACKAGE}.evaluation'), f'{source} -> {target}'


def test_the_core_never_imports_an_artifact_or_the_evidence_layer():
    for path in modules():
        source = module_name(path)
        if not source.startswith(f'{PACKAGE}.core'):
            continue
        for target in imported_modules(path):
            assert not target.startswith(f'{PACKAGE}.artifacts'), f'{source} -> {target}'
            assert not target.startswith(f'{PACKAGE}.project_evidence'), f'{source} -> {target}'


def test_sibling_imports_are_relative():
    """Every import between pure-core modules is relative."""
    for path in modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(PACKAGE), (
                    f'{module_name(path)}:{node.lineno} imports {node.module} absolutely; use a relative import'
                )


def test_neither_artefact_imports_the_other():
    """No CPR module imports a GeoTeaser module, and no GeoTeaser module imports a CPR module."""
    artefacts = {'cpr': f'{PACKAGE}.artifacts.cpr.', 'geotizer': f'{PACKAGE}.artifacts.geotizer.'}
    crossings = []
    for path in modules():
        source = module_name(path)
        owner = next((name for name, prefix in artefacts.items() if source.startswith(prefix)), None)
        if owner is None:
            continue
        for target in imported_modules(path):
            other = next(
                (name for name, prefix in artefacts.items() if target.startswith(prefix)), None
            )
            if other is not None and other != owner:
                crossings.append(f'{source} -> {target}')

    assert crossings == [], crossings
