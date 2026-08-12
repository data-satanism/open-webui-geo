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

# Every root CORE-BOUNDARY-01 will create. Listed before they exist so the gate
# is live on the commit that creates the first one.
PURE_ROOTS = (
    'backend/open_webui/services/core',
    'backend/open_webui/services/project_evidence',
    'backend/open_webui/services/artifacts/geotizer',
    'backend/open_webui/services/artifacts/cpr',
    'backend/open_webui/services/geotizer',
)


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


def check_import_boundary(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Return (violations, skipped_roots)."""
    violations: list[str] = []
    skipped: list[str] = []

    for relative in PURE_ROOTS:
        directory = root / relative
        if not directory.is_dir():
            skipped.append(relative)
            continue
        for module in sorted(directory.rglob('*.py')):
            violations.extend(
                forbidden_imports(
                    module.read_text(encoding='utf-8'),
                    module.relative_to(root).as_posix(),
                )
            )

    return violations, skipped


def main() -> int:
    violations, skipped = check_import_boundary()

    for relative in skipped:
        print(f'skipped (not created yet): {relative}')

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

    checked = len(PURE_ROOTS) - len(skipped)
    print(f'import boundary check passed ({checked} of {len(PURE_ROOTS)} roots present)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
