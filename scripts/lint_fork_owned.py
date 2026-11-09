"""Run ruff's dead-code rules over the paths this fork owns, and only those.

The repository-wide check has to stay relaxed: ~356 of the 394 hits under
these rules are in upstream's own files, and those are not the fork's to
change. So the bar is raised by narrowing the tree instead — and the tree is
read from `check_upstream_footprint.py`'s `FORK_OWNED_PREFIXES` rather than
written out again here.

That indirection is the point. The first version of this check listed the
paths by hand in the workflow and missed four of the eleven prefixes, plus
`scripts/` entirely. It missed them silently, because a shorter list looks
exactly like a complete one — and the file it failed to cover was the very
file the same commit edited, which had acquired a duplicate `DECLARED` key
that `F601` would have caught on sight.

`backend/tests` and `scripts` are added on top: neither sits inside upstream's
tree, so neither can appear in a list of upstream paths the fork has touched,
and both are wholly the fork's.

`F811` is deliberately absent. Its 26 hits are one `kb` helper shadowed by a
lambda parameter of the same name in four test files; enabling it would mean
editing tests to satisfy a rule that has found no defect. Stated here rather
than left in a list of numbers.

Run:  python scripts/lint_fork_owned.py [--show-paths]
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOOTPRINT = ROOT / 'scripts' / 'check_upstream_footprint.py'

RULES = 'F401,F403,F405,F541,F841'

#: Fork-authored trees that live outside upstream's, so they cannot appear in
#: a list of upstream files the fork has modified.
ALSO = ('backend/tests', 'scripts')


def fork_owned_prefixes() -> tuple[str, ...]:
    """`FORK_OWNED_PREFIXES`, read with `ast` rather than imported.

    Importing would run the module; reading the literal cannot, and this file
    is invoked by CI before anything else has been installed.
    """
    tree = ast.parse(FOOTPRINT.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'FORK_OWNED_PREFIXES' not in names:
            continue
        return tuple(
            item.value
            for item in ast.walk(node.value)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    raise SystemExit('FORK_OWNED_PREFIXES is not a literal in check_upstream_footprint.py')


def paths_to_check(root: Path = ROOT) -> list[str]:
    """Every existing file or directory the prefixes and `ALSO` name.

    A prefix may be a directory (`.../services/`), a whole path
    (`.../asgi.py`) or a genuine prefix (`.../tools/geotizer`, which matches
    `geotizer.py` and anything beside it). All three are expanded here so the
    caller never has to know which kind it was looking at.
    """
    found: list[str] = []
    for prefix in fork_owned_prefixes() + ALSO:
        candidate = root / prefix
        if candidate.exists():
            found.append(prefix.rstrip('/'))
            continue
        parent = (root / prefix).parent
        stem = Path(prefix).name
        if parent.is_dir():
            found.extend(
                str(match.relative_to(root))
                for match in sorted(parent.iterdir())
                if match.name.startswith(stem)
            )
    # De-duplicated, because `utils/geotizer` and an expanded
    # `utils/geotizer_run_registry.py` would otherwise both be handed to ruff.
    unique: list[str] = []
    for path in found:
        if not any(path == kept or path.startswith(f'{kept}/') for kept in unique):
            unique.append(path)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--show-paths', action='store_true')
    parser.add_argument('--output-format', default='concise')
    args = parser.parse_args()

    paths = paths_to_check()
    if args.show_paths:
        for path in paths:
            print(path)
        return 0
    print(f'ruff {RULES} over {len(paths)} fork-owned paths')
    return subprocess.run(
        ['ruff', 'check', f'--select={RULES}',
         f'--output-format={args.output_format}', *paths],
        cwd=str(ROOT),
    ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
