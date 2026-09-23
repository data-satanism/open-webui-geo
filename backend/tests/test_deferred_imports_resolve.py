"""Every in-function import in the fork-owned GeoTeaser modules resolves."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

OWNED = (
    'open_webui/tools/geotizer.py',
    'open_webui/utils/geotizer_orchestration.py',
    'open_webui/utils/geotizer_rag_runtime.py',
    'open_webui/utils/geotizer_run_registry.py',
    'open_webui/utils/geotizer_service_account.py',
    'open_webui/utils/kb_collection_scope.py',
    'open_webui/utils/api_key_scope.py',
)


def _deferred_imports(path: Path) -> list[tuple[str, tuple[str, ...], int]]:
    """(module, names, lineno) for every import nested inside a function."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found: list[tuple[str, tuple[str, ...], int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and inner.module and inner.level == 0:
                found.append((inner.module, tuple(alias.name for alias in inner.names), inner.lineno))
            elif isinstance(inner, ast.Import):
                for alias in inner.names:
                    found.append((alias.name, (), inner.lineno))
    return found


def _owned_modules() -> list[Path]:
    return [BACKEND / name for name in OWNED if (BACKEND / name).exists()]


def test_the_scan_finds_something_to_check():
    """The scan finds at least one owned module and at least ten deferred imports across them."""
    total = sum(len(_deferred_imports(path)) for path in _owned_modules())

    assert _owned_modules(), 'no owned module was found to scan'
    assert total >= 10, f'expected the owned surface to defer imports; found {total}'


@pytest.mark.parametrize('module_path', _owned_modules(), ids=lambda p: p.name)
def test_every_deferred_import_resolves(module_path):
    """The name has to exist where the call site says it does."""
    unresolved: list[str] = []
    for module_name, names, lineno in _deferred_imports(module_path):
        if not module_name.startswith('open_webui'):
            continue
        try:
            module = importlib.import_module(module_name)
        except ImportError as error:  # noqa: PERF203
            unresolved.append(f'{module_path.name}:{lineno} cannot import {module_name!r} ({error})')
            continue
        for name in names:
            if not hasattr(module, name):
                unresolved.append(f'{module_path.name}:{lineno} {module_name!r} has no {name!r}')

    assert not unresolved, 'deferred imports that would fail at call time:\n  ' + '\n  '.join(unresolved)
