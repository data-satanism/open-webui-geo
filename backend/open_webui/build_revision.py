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

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

#: One shape for every source, so a reader does not have to know which service
#: used which mechanism:
#:
#:     {"revision": "b0e6952", "dirty": true,  "source": "git"}
#:     {"revision": "87e82ee", "dirty": false, "source": "build_arg"}
#:     {"revision": null,      "dirty": null,  "source": "external"}
#:
#: `source` is what makes the third row honest. A null revision with no reason
#: reads as a bug; `external` reads as a boundary.
#:
#: `dirty` is `None` and not `False` whenever nothing was looked at. «We did not
#: look» and «we looked and nothing had changed» are different facts, and
#: defaulting to the second is how a dirty tree gets recorded as a clean build.
FROM_GIT = 'git'
FROM_BUILD_ARG = 'build_arg'
FROM_EXTERNAL = 'external'

#: Why `revision` is null, when it is, in the same key `gis_service` uses.
#:
#: Runs `d0e871ec` and `06d1f455` recorded two null revisions beside each other
#: -- one a build argument nobody passed, one a component built elsewhere --
#: and they rendered identically while meaning opposite things. This side has a
#: third case again: git present and the checkout unreadable, which is neither
#: «not asked» nor «not ours». One word each, so a reader can tell which one is
#: theirs to act on.
ABSENCE_KEY = 'revision_absent_because'
#: The reading was taken and found nothing: no git, no checkout, a non-zero
#: exit, or a hang. Distinct from a build that was never stamped -- somebody
#: looked here.
UNREADABLE_ABSENCE = 'unreadable'

#: How long git gets. A build reference is worth a moment at import and nothing
#: more; a hung git must not hold the application's start-up open.
GIT_TIMEOUT_SECONDS = 5

#: Overrides that stop the DIRECTORY deciding what runs.
#:
#: `checkout_path` is configuration, so the directory git is pointed at is not
#: necessarily one this project wrote. A repository's own `.git/config` can name
#: a command in `core.fsmonitor`, and `git status` RUNS it -- measured on git
#: 2.43.0: a config-supplied script executed on a plain `git status` and did not
#: execute with `-c core.fsmonitor=`. `safe.directory` does not help, because it
#: only refuses directories owned by somebody else and the dangerous case is a
#: writable directory owned by this very user.
#:
#: These are passed on every invocation rather than only on `status`: which
#: subcommands consult which config is git's business and it changes between
#: versions, and there is no reading here that wants a hook to fire.
GIT_HARDENING = ('-c', 'core.fsmonitor=', '-c', 'core.hooksPath=/dev/null')

#: Where to look for the checkout. Configuration, not a constant: the default
#: below is right for a deployment that runs the code where it is installed,
#: and wrong the moment the operator installs the package somewhere and keeps
#: the checkout elsewhere. Pointing it at the real location must not need a
#: code change.
CHECKOUT_VARIABLE = 'GEOTEASER_WEBUI_CHECKOUT'

#: `backend/open_webui/build_revision.py` -> the checkout root. Defensible as a
#: default because it is where this file actually is: a deployment that runs
#: from a checkout has `.git` two directories up, and one that does not gets
#: `unknown` rather than a wrong answer.
DEFAULT_CHECKOUT = Path(__file__).resolve().parents[2]


def checkout_path(environ: Mapping[str, str] | None = None) -> Path:
    """The directory git is asked about.

    An empty or unset variable falls back to the default rather than being
    honoured as «look in the current directory», which is what an empty string
    would otherwise mean and is never what an operator intends by clearing a
    variable.
    """
    env = os.environ if environ is None else environ
    configured = (env.get(CHECKOUT_VARIABLE) or '').strip()
    return Path(configured) if configured else DEFAULT_CHECKOUT


def _git(*args: str, cwd: Path | None = None) -> str | None:
    """Run git in the configured checkout, or answer None. Never raises.

    A service that will not start because it cannot name its own revision is
    worse than one that cannot name it. So every way git can fail -- absent
    from the path, an unreadable checkout, a non-zero exit, a hang -- reaches
    the same answer, and none of them reaches the caller as an exception.
    """
    try:
        finished = subprocess.run(
            ('git', *GIT_HARDENING, *args),
            cwd=cwd or checkout_path(),
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
def build_revision() -> dict[str, Any]:
    """`{'revision': ..., 'dirty': ..., 'source': 'git'}`.

    Both values, never one. `rev-parse` alone lies on a dirty tree: it returns
    the last commit whether or not files changed after it, and this contour
    edits files in place. «b0e6952, dirty» is honest; «b0e6952» alone is not,
    and it is worse than a null revision because it reads as a measurement.

    An unreadable checkout answers `{None, None, 'git'}` — a null revision with
    `source: git` says the mechanism was in place and found nothing, which is a
    different fact from `source: external`, where there was never anything here
    to find.

    Cached: the commit cannot change under a running process, and `git status`
    on a large checkout is not free.
    """
    head = _git('rev-parse', 'HEAD')
    revision = head.strip() if head and head.strip() else None
    if revision is None:
        # Nothing to ask about the tree when the commit it would be compared
        # against is unknown: «dirty relative to nothing» says nothing.
        return {
            'revision': None,
            'dirty': None,
            'source': FROM_GIT,
            ABSENCE_KEY: UNREADABLE_ABSENCE,
        }
    porcelain = _git('status', '--porcelain')
    if porcelain is None:
        return {'revision': revision, 'dirty': None, 'source': FROM_GIT}
    return {
        'revision': revision,
        'dirty': bool(porcelain.strip()),
        'source': FROM_GIT,
    }
