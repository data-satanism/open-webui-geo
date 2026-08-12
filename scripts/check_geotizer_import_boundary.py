#!/usr/bin/env python3
"""Fail if anything in the pure core imports `open_webui`.

GT-CONV-01 step 4 — "freeze the purity boundary and forbid the import in CI".

`backend/open_webui/services/` is the tree CORE-BOUNDARY-01 fills with the
deterministic core. Nothing in it may reach into `open_webui`, because
`open_webui.utils.*`, the model classes and the middleware helpers rename and
move between releases and carry no deprecation machinery. The measured target
is real rather than aspirational: 127 of the production Tool's 131 top-level
definitions already have zero `open_webui` dependency.

The four that do bind it are the effect shell — `resolve_gis_call`,
`build_agent_call`, `build_vision_call` and `Tools` — and they live outside
this tree by design.

Run:  python scripts/check_geotizer_import_boundary.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOT = 'open_webui'

# The whole tree, not a list of the subdirectories known when this was written.
# A list is escapable: `artifacts/consistency.py` sat outside every entry of the
# original five, and `services/evaluation/` would have been the second. The rule
# in the README is "no module under this tree", so that is what is walked.
PURE_TREE = 'backend/open_webui/services'


def forbidden_imports(source: str, path: str) -> list[str]:
    """Every `open_webui` import in one module, including in-function ones."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f'{path}: does not parse: {exc}']

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            # A relative import has no `open_webui` prefix to match on and is
            # fine: it stays inside the pure tree.
            if node.level == 0 and (module == FORBIDDEN_ROOT or module.startswith(f'{FORBIDDEN_ROOT}.')):
                violations.append(f'{path}:{node.lineno}: from {module} import ...')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == FORBIDDEN_ROOT or alias.name.startswith(f'{FORBIDDEN_ROOT}.'):
                    violations.append(f'{path}:{node.lineno}: import {alias.name}')
    return violations


def check_import_boundary(root: Path = ROOT) -> tuple[list[str], int]:
    """Return (violations, modules_checked)."""
    violations: list[str] = []
    directory = root / PURE_TREE
    modules = [module for module in sorted(directory.rglob('*.py')) if '__pycache__' not in module.parts]

    for module in modules:
        violations.extend(
            forbidden_imports(
                module.read_text(encoding='utf-8'),
                module.relative_to(root).as_posix(),
            )
        )

    return violations, len(modules)


def main() -> int:
    violations, checked = check_import_boundary()

    if violations:
        print()
        print('The pure core may not import open_webui. Found:')
        for violation in violations:
            print(f'  ERROR: {violation}')
        print()
        print(
            'Move the effect into the effect shell and inject it, as '
            'resolve_gis_call / build_agent_call / build_vision_call already are.'
        )
        return 1

    print(f'import boundary check passed ({checked} modules under {PURE_TREE})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
