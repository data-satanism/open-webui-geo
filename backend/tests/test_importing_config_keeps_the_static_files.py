"""Importing `open_webui.config` deleted eighteen tracked files, every time.

A-19. `config.py` empties `STATIC_DIR` at import and then copies the frontend
build's static assets back over it. A backend checkout has no build, so the
copy restores nothing and the delete stands: `backend/open_webui/static/` --
the favicons, the splash images, `loader.js`, `custom.css` -- is gone from the
working tree after any import that reaches `config`.

It was blamed on the sandbox and on `git stash` before the cause was found. Two
things follow from it. Every run that touches `config` leaves the tree dirty in
a way that has nothing to do with what was run, and no test may import the
GeoTeaser tool adapter at all -- which is why that adapter is checked by
reading its call sites with `ast` rather than by calling it.

**The real block is read out of `config.py` and executed against temporary
directories.** Not imported: importing `config` pulls in the migrations and the
model layer, so it needs dependencies a backend checkout may not have, and this
file would then be unrunnable exactly where the damage happens. Not copied
either -- a copy of ten lines is a second thing to keep in step, and the defect
being tested is precisely that nobody noticed what these ten lines do.
`validate_utm_zone_arithmetic.py` extracts and runs its subject the same way
and for the same reason.
"""

from __future__ import annotations

import ast
import builtins
import shutil
import tempfile
from pathlib import Path

CONFIG = (
    Path(__file__).resolve().parents[1] / 'open_webui' / 'config.py'
)

#: The block, by the two lines that bound it. Located rather than line-numbered:
#: a line number is a fact about today's file and silently starts describing
#: something else the moment anything above it moves.
START = "_FRONTEND_STATIC = FRONTEND_BUILD_DIR / 'static'"
END = "# LICENSE covers copied Open WebUI logo/favicon assets."


def static_dir_block() -> str:
    """The STATIC_DIR cleanup and refill, exactly as `config.py` runs it."""
    source = CONFIG.read_text(encoding='utf-8')
    # Each marker exactly once, and in order. `index` takes the first hit, so a
    # second copy of either line anywhere in the file would silently select a
    # different span; reversed, the slice is empty, `exec` is a no-op, and the
    # first test below would pass by doing nothing at all.
    assert source.count(START) == 1, 'the cleanup no longer starts uniquely'
    assert source.count(END) == 1, 'the block no longer ends uniquely'
    assert source.index(START) < source.index(END), 'the markers are out of order'
    return source[source.index(START):source.index(END)]


def _survivors(*, with_build: bool | str) -> list[str]:
    """Names left in a throwaway STATIC_DIR after the real block has run."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        static = root / 'static'
        static.mkdir()
        (static / 'favicon.png').write_bytes(b'packaged default')
        (static / 'loader.js').write_text('// packaged default', encoding='utf-8')

        build = root / 'build'
        if with_build == 'empty':
            # The directory exists and carries nothing — the case a mere
            # `is_dir()` check reads as «a build is present».
            (build / 'static').mkdir(parents=True)
        elif with_build:
            # A packaged deployment: the build carries the assets the cleanup
            # exists to install, so replace-then-copy is what upstream wants.
            (build / 'static').mkdir(parents=True)
            (build / 'static' / 'favicon.png').write_bytes(b'from the build')
        else:
            build.mkdir()

        import logging

        exec(  # noqa: S102 - running the subject is the point
            compile(static_dir_block(), str(CONFIG), 'exec'),
            {
                'STATIC_DIR': static,
                'FRONTEND_BUILD_DIR': build,
                'shutil': shutil,
                'logging': logging,
                'Path': Path,
            },
        )
        return sorted(item.name for item in static.iterdir())


def test_the_cleanup_without_a_build_keeps_the_static_files():
    """The defect, stated as the thing it destroys.

    Unguarded, both files are unlinked and neither is replaced, so this comes
    back empty — eighteen tracked files in the real tree, deleted by an import.
    """
    assert _survivors(with_build=False) == ['favicon.png', 'loader.js']


def test_a_deployment_with_a_build_still_gets_the_builds_assets():
    """Upstream's behaviour where upstream's assumption holds.

    The guard must not become «never clean up»: a packaged deployment ships a
    build, and this cleanup is how its assets replace the packaged defaults.
    """
    survivors = _survivors(with_build=True)

    assert 'favicon.png' in survivors
    # Absent from the build, so the cleanup removed it — which is what upstream
    # intends when there is a build to be authoritative about the contents.
    assert 'loader.js' not in survivors


def test_every_name_the_block_uses_is_bound_before_it_in_config():
    """The one thing `exec` with a hand-built globals dict cannot see.

    This file supplies `FRONTEND_BUILD_DIR` and `STATIC_DIR` itself, so if a
    refactor ever dropped either from `config.py`'s own imports the real module
    would die with `NameError` on this very line while both tests here stayed
    green. The block is checked against the file it came from instead: every
    free name it reads must already be bound at module level above it.

    Static, because importing `config` is what this file exists to avoid.
    """
    source = CONFIG.read_text(encoding='utf-8')
    block = static_dir_block()
    tree = ast.parse(block)

    bound_here = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    } | {
        # `except Exception as e` binds a name without being a `Name` node.
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.name
    }
    free = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    } - bound_here - set(dir(builtins))

    # What `config.py` itself has bound by the time the block runs.
    above = ast.parse(source[:source.index(START)])
    bound_above: set[str] = set()
    for node in ast.walk(above):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound_above.update(
                (alias.asname or alias.name).split('.')[0] for alias in node.names
            )
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound_above.add(node.id)

    missing = sorted(free - bound_above)
    assert not missing, (
        f'{missing} are used by the STATIC_DIR block and not bound above it in '
        'config.py — importing the module would raise NameError'
    )


def test_a_build_directory_with_nothing_in_it_does_not_empty_static():
    """`is_dir()` is true of an empty `build/static`, and the first guard used
    it: a build that failed after creating the directory, a `mkdir -p` before
    `npm run build`, a Docker layer that copied nothing — all of them deleted
    every file and restored none, which is the defect one precondition further
    along rather than the defect fixed.
    """
    assert _survivors(with_build='empty') == ['favicon.png', 'loader.js']
