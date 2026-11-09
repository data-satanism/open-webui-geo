"""The strict lint's paths are derived from one list, not written out twice.

The first version listed them by hand in the workflow and missed four of the
eleven fork-owned prefixes, plus `scripts/` entirely. It missed them silently,
because a short list looks exactly like a complete one — and the file it failed
to cover was the one the same commit edited, which had acquired a duplicate
`DECLARED` key that `F601` would have caught on sight.

So the question this file asks is not «does ruff pass» but «is the thing ruff
was pointed at still everything the fork owns».
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINTER = ROOT / 'scripts' / 'lint_fork_owned.py'
FOOTPRINT = ROOT / 'scripts' / 'check_upstream_footprint.py'

sys.path.insert(0, str(ROOT / 'scripts'))


def _paths() -> list[str]:
    done = subprocess.run(
        [sys.executable, str(LINTER), '--show-paths'],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return [line for line in done.stdout.splitlines() if line.strip()]


def _prefixes() -> tuple[str, ...]:
    import ast

    tree = ast.parse(FOOTPRINT.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == 'FORK_OWNED_PREFIXES'
            for t in node.targets
        ):
            continue
        return tuple(
            item.value
            for item in ast.walk(node.value)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    raise AssertionError('FORK_OWNED_PREFIXES is no longer a literal')


def test_every_fork_owned_prefix_is_covered_by_the_lint():
    """A prefix the footprint check calls ours and the lint never looks at is
    a file where dead code accumulates with nothing to say so."""
    covered = _paths()

    for prefix in _prefixes():
        stem = prefix.rstrip('/')
        assert any(
            path == stem or path.startswith(f'{stem}/') or path.startswith(stem)
            for path in covered
        ), f'{prefix} is fork-owned and outside the lint: {covered}'


def test_the_two_trees_that_are_not_upstreams_are_covered_too():
    """`backend/tests` and `scripts` cannot appear in a list of upstream paths
    the fork has touched, because neither sits inside upstream's tree. The
    duplicate `DECLARED` key lived in `scripts/`."""
    covered = _paths()

    assert 'backend/tests' in covered
    assert 'scripts' in covered


def test_the_workflow_that_actually_runs_calls_the_derived_check():
    """`backend.yaml` filters to `main` and `dev`, so nothing in it runs for a
    pull request on this fork. A lint step there is not a lint step."""
    workflow = (
        ROOT / '.github' / 'workflows' / 'geotizer-backend.yaml'
    ).read_text(encoding='utf-8')

    assert 'scripts/lint_fork_owned.py' in workflow
    # And no hand-written path list beside it, which is what drifted.
    assert 'backend/open_webui/utils/kb_collection_scope.py' not in workflow
