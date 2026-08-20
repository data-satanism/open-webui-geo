"""The shared GeoTeaser exception types have exactly one declaration site.

CORE-BOUNDARY-01 action 1. Before the move, `GeotizerOrchestrationError` lived
in the orchestration module and `GeotizerGisError` in the Workspace-facing
tool, so the tool had to import orchestration in order to raise a GIS failure
and an `except GeotizerOrchestrationError` in one module could not be relied on
to catch the other's.
"""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path

import pytest

from open_webui.services.geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / 'backend'
SHARED = 'backend/open_webui/services/geotizer/errors.py'


def declaration_sites(class_name: str) -> list[str]:
    sites: list[str] = []
    for module in sorted(BACKEND.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        with warnings.catch_warnings():
            # `tools/knowledge_fs.py` writes regex escapes in plain strings and
            # parsing it raises DeprecationWarning seven times. That is a real
            # latent defect and it predates this work, but it is not what this
            # test is about, and letting it surface here would read as if this
            # test were the broken thing.
            warnings.simplefilter('ignore', DeprecationWarning)
            tree = ast.parse(module.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                sites.append(module.relative_to(REPO_ROOT).as_posix())
    return sites


@pytest.mark.parametrize('class_name', ['GeotizerOrchestrationError', 'GeotizerGisError'])
def test_each_type_is_declared_once_and_in_the_core(class_name):
    assert declaration_sites(class_name) == [SHARED]


def test_the_core_module_imports_nothing_from_open_webui():
    tree = ast.parse((REPO_ROOT / SHARED).read_text(encoding='utf-8'))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not [m for m in modules if m.split('.')[0] == 'open_webui']


def test_a_gis_failure_is_caught_as_an_orchestration_failure():
    assert issubclass(GeotizerGisError, GeotizerOrchestrationError)


def test_a_gis_failure_keeps_its_details_structured():
    """The parent LLM must not be handed a reworded failure, so the details
    survive both as an attribute and as the exception's own JSON text."""
    details = {'code': 'gis_unavailable', 'retryable': False, 'endpoint': 'submit_batch'}

    error = GeotizerGisError(details)

    assert error.details == details
    assert json.loads(str(error)) == details


def test_the_details_are_copied_rather_than_aliased():
    details = {'code': 'gis_unavailable'}
    error = GeotizerGisError(details)

    details['code'] = 'mutated_after_the_fact'

    assert error.details == {'code': 'gis_unavailable'}


def test_non_ascii_details_survive_intact():
    error = GeotizerGisError({'reason': 'участок не найден'})

    assert json.loads(str(error))['reason'] == 'участок не найден'
