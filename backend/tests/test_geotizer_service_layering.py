"""No module in the pure core may import one that sits above it.

CORE-BOUNDARY-01. `test_geotizer_import_boundary.py` guards the outer edge --
nothing under `services/` reaches into `open_webui`. This guards the inside:
`project_evidence` must not import `artifacts/geotizer`, or the evidence core
becomes GeoTeaser-shaped again and the split has bought nothing.

The same defect was found in the plan before the code moved.
`GMM/operations/gt-conv-01/definition-classification.json` records a layer per
target module and twelve definitions that had to be re-targeted because the
monolith's section banners placed them above their callers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = REPO_ROOT / 'backend/open_webui/services'
PACKAGE = 'open_webui.services'

# Lower may not import higher. `artifacts/geotizer/validation.py` is physically
# nested under the artefact but sits at the bottom on purpose: it holds the
# hand-written copies of the GIS submission rules, which the artefact reads and
# which CORE-BOUNDARY-01 action 4 deletes once GIS owns them.
LAYERS = {
    'open_webui.services.geotizer.errors': 0,
    'open_webui.services.geotizer.semantics': 1,
    'open_webui.services.core.text': 1,
    'open_webui.services.core.tasks': 1,
    'open_webui.services.core.vocabulary': 1,
    'open_webui.services.core.idempotency': 1,
    'open_webui.services.artifacts.geotizer.validation': 1,
    'open_webui.services.project_evidence.resource_coherence': 2,
    'open_webui.services.project_evidence.retrieval': 2,
    'open_webui.services.project_evidence.proposals': 3,
    'open_webui.services.artifacts.geotizer.owner_envelope': 4,
    'open_webui.services.artifacts.geotizer.observability': 5,
    'open_webui.services.artifacts.geotizer.project': 5,
    # The CPR artefact. Its own errors are a leaf; the rest stack on top of the
    # evidence core, in the order a run uses them: plan, then measure, then
    # write, then audit what was written.
    'open_webui.services.artifacts.cpr.errors': 1,
    'open_webui.services.artifacts.cpr.catalog': 4,
    'open_webui.services.artifacts.cpr.requirements': 5,
    'open_webui.services.artifacts.cpr.coverage': 6,
    'open_webui.services.artifacts.cpr.project': 6,
    'open_webui.services.artifacts.cpr.narrative': 6,
    'open_webui.services.artifacts.cpr.audit': 7,
    'open_webui.services.artifacts.cpr.render': 8,
    # Reads both artefacts, so it sits above both.
    'open_webui.services.artifacts.consistency': 9,
    # Reads both artefacts and judges a retrieval change by them, so it sits
    # above everything. Nothing may ever import the evaluator: a measurement
    # that the thing it measures depends on is not a measurement.
    'open_webui.services.evaluation.rag_ab': 10,
}


def module_name(path: Path) -> str:
    relative = path.relative_to(SERVICES).with_suffix('')
    return f'{PACKAGE}.' + relative.as_posix().replace('/', '.')


def modules() -> list[Path]:
    return [p for p in sorted(SERVICES.rglob('*.py')) if '__pycache__' not in p.parts]


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
    """A module added without a layer would otherwise import anything it liked."""
    assert {module_name(p) for p in modules()} == set(LAYERS)


@pytest.mark.parametrize('path', modules(), ids=module_name)
def test_no_module_imports_from_a_higher_layer(path):
    source = module_name(path)
    for target in imported_modules(path):
        assert target in LAYERS, f'{source} imports unmapped {target}'
        assert LAYERS[target] <= LAYERS[source], f'{source} -> {target}'


def test_the_evidence_core_never_imports_an_artifact():
    """Stated separately from the numbers: this is the point of the split, and
    a future edit to LAYERS should not be able to make it pass by accident."""
    for path in modules():
        source = module_name(path)
        if not source.startswith(f'{PACKAGE}.project_evidence'):
            continue
        for target in imported_modules(path):
            assert not target.startswith(f'{PACKAGE}.artifacts'), f'{source} -> {target}'


def test_nothing_imports_the_evaluation_layer():
    """RAG-EVAL-01 measures the pipeline from outside it. A module that the
    pipeline imported could shape what it reports."""
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
    """The pure core does not name its host package. Keeping the imports
    relative is what makes lifting the tree out of `open_webui` a move rather
    than a rewrite -- and it is also why the outer boundary check, which greps
    for `open_webui`, stays meaningful inside the tree."""
    for path in modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(PACKAGE), (
                    f'{module_name(path)}:{node.lineno} imports {node.module} absolutely; use a relative import'
                )
