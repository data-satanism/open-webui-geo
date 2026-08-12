"""The import-boundary gate must catch a violation, not just pass vacuously.

GT-CONV-01 step 4. A gate that has never rejected anything is not evidence of
anything, so these tests build small trees in tmp_path and prove it rejects
what it must.

The gate walks the whole `services/` tree rather than a list of subdirectories.
The list was escapable and had already been escaped once: `artifacts/consistency.py`
sits directly under `artifacts/` and matched none of the original five roots, so
nothing checked it. `test_every_module_in_the_tree_is_checked` is what stops that
recurring.

The four effect-shell definitions stay outside this tree by design:
resolve_gis_call, build_agent_call, build_vision_call and Tools. Everything
else in the production Tool — 127 of 131 top-level definitions — already has
zero open_webui dependency and lifts in unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / 'scripts' / 'check_geotizer_import_boundary.py'


def load_checker():
    spec = importlib.util.spec_from_file_location('_import_boundary', CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


boundary = load_checker()


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')


PURE = """
from dataclasses import dataclass


@dataclass(frozen=True)
class Claim:
    value: str
"""


def test_the_repository_currently_passes():
    violations, checked = boundary.check_import_boundary(REPO_ROOT)

    assert violations == []
    assert checked > 0


def test_every_module_in_the_tree_is_checked():
    """Not "every root that exists" -- every module. Counting roots is what let
    a module outside all of them go unread; counting modules cannot."""
    _, checked = boundary.check_import_boundary(REPO_ROOT)
    present = [path for path in (REPO_ROOT / boundary.PURE_TREE).rglob('*.py') if '__pycache__' not in path.parts]

    assert checked == len(present)


def test_a_module_in_a_brand_new_subdirectory_is_checked(tmp_path):
    """The gap this replaced a root list to close: a directory nobody thought
    of when the gate was written is inside the boundary from its first file."""
    write(
        tmp_path,
        'backend/open_webui/services/somewhere_new/thing.py',
        'from open_webui.env import SRC_LOG_LEVELS\n',
    )

    violations, checked = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 1
    assert checked == 1


def test_the_core_already_holds_the_moved_modules():
    """CORE-BOUNDARY-01 step 1. These three carried no `open_webui` import even
    before the move, which is why they went first."""
    for relative in (
        'backend/open_webui/services/geotizer/errors.py',
        'backend/open_webui/services/geotizer/semantics.py',
        'backend/open_webui/services/project_evidence/retrieval.py',
        'backend/open_webui/services/project_evidence/resource_coherence.py',
    ):
        assert (REPO_ROOT / relative).is_file(), relative

    for relative in (
        'backend/open_webui/utils/geotizer_retrieval.py',
        'backend/open_webui/utils/geotizer_semantics.py',
        'backend/open_webui/utils/geotizer_resource_coherence.py',
    ):
        assert not (REPO_ROOT / relative).exists(), (
            f'{relative} was moved into services/, not copied -- a shim left '
            f'behind would let a caller keep the old path indefinitely'
        )


def test_a_pure_module_passes(tmp_path):
    write(tmp_path, 'backend/open_webui/services/project_evidence/claims.py', PURE)

    violations, checked = boundary.check_import_boundary(tmp_path)

    assert violations == []
    assert checked == 1


def test_a_module_level_import_is_rejected(tmp_path):
    write(
        tmp_path,
        'backend/open_webui/services/project_evidence/planning.py',
        'from open_webui.utils.tools import get_tools\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 1
    assert 'from open_webui.utils.tools import ...' in violations[0]


def test_an_in_function_import_is_rejected(tmp_path):
    """The monolith's effect shell binds open_webui only inside functions. A
    checker that looked at module-level imports alone would miss all four."""
    write(
        tmp_path,
        'backend/open_webui/services/artifacts/geotizer/adapter.py',
        'def build():\n    from open_webui.models.users import UserModel\n\n    return UserModel\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 1
    assert ':2:' in violations[0]


@pytest.mark.parametrize(
    'statement',
    [
        'import open_webui\n',
        'import open_webui.utils.chat\n',
        'import open_webui.env as env\n',
        'from open_webui import env\n',
    ],
)
def test_every_import_spelling_is_rejected(tmp_path, statement):
    write(tmp_path, 'backend/open_webui/services/geotizer/errors.py', statement)

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 1


def test_a_relative_import_inside_the_pure_tree_is_allowed(tmp_path):
    """Relative imports stay inside the boundary and must not be flagged."""
    write(tmp_path, 'backend/open_webui/services/project_evidence/claims.py', PURE)
    write(
        tmp_path,
        'backend/open_webui/services/project_evidence/resolution.py',
        'from .claims import Claim\nfrom ..artifacts import nothing\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert violations == []


def test_a_lookalike_package_is_not_flagged(tmp_path):
    """`open_webui_geo_helpers` is not `open_webui`; prefix matching must not
    over-reach."""
    write(
        tmp_path,
        'backend/open_webui/services/project_evidence/planning.py',
        'import open_webui_geo_helpers\nfrom open_webui_extra import thing\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert violations == []


def test_every_violation_across_several_files_is_reported(tmp_path):
    """The gate reports all of them, so one CI run fixes the whole tree."""
    write(
        tmp_path,
        'backend/open_webui/services/project_evidence/a.py',
        'import open_webui\n',
    )
    write(
        tmp_path,
        'backend/open_webui/services/artifacts/cpr/b.py',
        'from open_webui.env import SRC_LOG_LEVELS\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 2


def test_an_unparseable_module_is_reported_not_skipped(tmp_path):
    write(
        tmp_path,
        'backend/open_webui/services/project_evidence/broken.py',
        'def (:\n',
    )

    violations, _ = boundary.check_import_boundary(tmp_path)

    assert len(violations) == 1
    assert 'does not parse' in violations[0]


def test_the_effect_shell_lives_outside_the_pure_tree():
    """A guard on the classification, not on the code: if the pure tree were
    widened to take in an effect-shell root, the boundary would become
    unsatisfiable rather than merely violated."""
    assert boundary.PURE_TREE == 'backend/open_webui/services'
    for effect_shell in ('backend/open_webui/tools', 'backend/open_webui/routers'):
        assert not effect_shell.startswith(boundary.PURE_TREE)
