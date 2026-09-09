"""The commit this process is running, and whether the tree still matches it.

Runs `0b5ae763` and `bc4af304` both recorded `run_variance.measured: false`,
`reason: build_not_readable`, and `build_ref` null for all three repositories.
So neither run knows which build produced it, and any comparison of their
numbers rests on an assumption nothing checked.

gis_service's `run_variance` reads `.git` as files, deliberately without a
subprocess, and its docstring gives the reason: «a deployment has no `.git` to
read. `Dockerfile` copies `arcgis_mcp/` and nothing else». That premise is
false for THIS contour -- there is no Docker on it, it runs under uvicorn from
a checkout, and `.git` is on disk -- which is why this module exists and why it
may use git directly.

It answers for this repository alone. The audit's `build_ref` spans three, and
the other two are gis_service's to report from wherever it runs.

Kept out of `services/` on purpose: that tree is a counted pure core whose
README carries totals in four places, and a module added there has to be
reconciled with all of them. Kept out of `asgi.py` too, though that is where
the reading is triggered -- `asgi` imports `open_webui.main`, so anything
living there can only be imported by pulling the whole application in, and this
has to be readable by a test and by the tool layer without that.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

#: What a run says about the build it came from when git cannot be asked.
#:
#: NOT `clean`, and not an absent key. «We did not look» and «we looked and
#: nothing had changed» are different facts, and defaulting to the second is how
#: a dirty tree gets recorded as a clean build.
UNKNOWN = 'unknown'

DIRTY = 'dirty'
CLEAN = 'clean'

#: How long git gets. A build reference is worth a moment at import and nothing
#: more; a hung git must not hold the application's start-up open.
GIT_TIMEOUT_SECONDS = 5

#: `backend/open_webui/build_revision.py` -> the checkout root.
_CHECKOUT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str | None:
    """Run git in this checkout, or answer None. Never raises.

    A service that will not start because it cannot name its own revision is
    worse than one that cannot name it. So every way git can fail -- absent
    from the path, an unreadable checkout, a non-zero exit, a hang -- reaches
    the same answer, and none of them reaches the caller as an exception.
    """
    try:
        finished = subprocess.run(
            ('git', *args),
            cwd=_CHECKOUT,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout


@lru_cache(maxsize=1)
def build_revision() -> dict[str, str]:
    """`{'revision': ..., 'tree': 'clean' | 'dirty' | 'unknown'}`.

    Both, never one. `rev-parse` alone lies on a dirty tree: it returns the
    last commit whether or not files changed after it, and this contour edits
    files in place. «b0e6952, dirty» is honest; «b0e6952» alone is not, and it
    is worse than «unknown» because it reads as a measurement.

    Cached: the commit cannot change under a running process, and `git status`
    on a large checkout is not free.
    """
    head = _git('rev-parse', 'HEAD')
    revision = head.strip() if head and head.strip() else UNKNOWN
    if revision == UNKNOWN:
        # Nothing to ask about the tree when the commit it would be compared
        # against is unknown: «dirty relative to nothing» says nothing.
        return {'revision': UNKNOWN, 'tree': UNKNOWN}
    porcelain = _git('status', '--porcelain')
    if porcelain is None:
        return {'revision': revision, 'tree': UNKNOWN}
    return {'revision': revision, 'tree': DIRTY if porcelain.strip() else CLEAN}
