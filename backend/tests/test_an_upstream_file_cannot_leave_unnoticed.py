"""The footprint check compares `.py` files under `backend/open_webui`. That is
right for a CONTENT comparison, which cannot diff a PNG. It was also, until
this file existed, the answer to a question nobody asked: «is the file still
here».

The 0.11.3 port removed twelve upstream files and every check in this
repository stayed green. Two of them were `backend/data/readme.txt` and
`backend/open_webui/data/readme.txt` -- placeholders whose only job is to make
git create the directories `DATABASE_URL` resolves into. Without them sqlite
cannot open the database and every import of `open_webui` dies at alembic's
first connect. Neither file is `.py`; one is not even under
`backend/open_webui`. Neither was ever a member of the compared set, in either
direction, at any pinned ref.

So presence is now checked over the whole tree, and these are the tests that
say the check can still tell.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import check_upstream_footprint as footprint  # noqa: E402


def test_the_presence_census_sees_what_the_content_comparison_cannot():
    """The discriminating assertion. If `every_file` were built on the same
    filter as `source_files`, everything else here would pass and the hole
    would be exactly where it was."""
    present = footprint.every_file('HEAD')
    compared = footprint.source_files('HEAD')

    # The two files the port dropped: one outside the tree, one inside it but
    # not source. Both are in the census; neither is in the comparison.
    for path in ('backend/data/readme.txt', 'backend/open_webui/data/readme.txt'):
        assert path in present, path
        assert path not in compared, path

    assert compared < present


def test_a_file_that_leaves_without_a_reason_is_named():
    upstream = {'a.py', 'backend/data/readme.txt', 'kept.txt'}
    fork = {'a.py', 'kept.txt'}

    missing, resurfaced = footprint.presence_gaps(upstream, fork)

    assert missing == ['backend/data/readme.txt']
    assert resurfaced == []


def test_a_declared_absence_is_not_reported_as_a_loss():
    declared = next(iter(footprint.ABSENT_BY_DESIGN))
    upstream = {declared, 'a.py'}
    fork = {'a.py'}

    missing, resurfaced = footprint.presence_gaps(upstream, fork)

    assert missing == []
    assert resurfaced == []


def test_a_reason_that_outlived_its_file_is_a_failure():
    """The other half, and the one that keeps the list from becoming a place
    absences go to be forgotten: if the file comes back, the entry has to go."""
    declared = next(iter(footprint.ABSENT_BY_DESIGN))
    upstream = {declared}
    fork = {declared}

    missing, resurfaced = footprint.presence_gaps(upstream, fork)

    assert missing == []
    assert resurfaced == [declared]


@pytest.mark.parametrize('path', sorted(footprint.ABSENT_BY_DESIGN))
def test_every_declared_absence_is_really_absent(path):
    """Measured against the working tree rather than against the list itself,
    so the declaration cannot be satisfied by its own existence."""
    assert not (REPO_ROOT / path).exists(), (
        f'{path} is declared absent by design but is present; '
        f'drop the entry — its reason is no longer true'
    )


def test_every_declared_absence_carries_a_reason():
    for path, reason in footprint.ABSENT_BY_DESIGN.items():
        assert reason.strip(), path


def test_the_build_keeps_the_heap_ceiling_the_fork_gave_it():
    """A file-level declaration is not enough for a file carrying two edits.

    `package.json` has two independent fork changes. The 0.11.3 port dropped
    one of them -- `NODE_OPTIONS=--max-old-space-size=8192` on both build
    scripts, added deliberately in `7b3bc5d74` -- and the file went on
    differing from upstream because of the other, so a check asking only «does
    this file still differ» stayed green while the build lost its heap
    ceiling. `Dockerfile` runs `npm run build` directly and its own
    `--max-old-space-size` line is commented out and half this size, so this
    is the only place the ceiling is set.

    Asserted on the value, not merely on the flag's presence: 4096 would also
    contain the substring and would not be what the fork chose.
    """
    import json

    scripts = json.loads((REPO_ROOT / 'package.json').read_text(encoding='utf-8'))['scripts']

    for name in ('build', 'build:watch'):
        assert 'NODE_OPTIONS=--max-old-space-size=8192' in scripts[name], (
            f'{name} lost the heap ceiling the fork set; see 7b3bc5d74'
        )


def _committed(path: str) -> str:
    """The file as committed, not as it sits on disk.

    Importing `open_webui.config` DELETES tracked files under
    `backend/open_webui/static/` -- a pre-existing defect the CI workflow
    documents and works around by checking out fresh each run. So by the time
    a test in this suite reads that directory, the suite itself may have
    removed what it came to look at, and the first run of the test below
    failed with `FileNotFoundError` on a file that is present in the commit,
    in the merge ref, and in the working tree before pytest starts.

    Reading the committed blob answers the question that was actually being
    asked -- what does the tree ship -- and cannot be disturbed by anything
    the process does to the checkout.
    """
    result = subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'show', f'HEAD:{path}'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f'could not read {path} from HEAD: {result.stderr.strip()}'
    return result.stdout


def test_the_installed_app_is_called_what_the_deployment_is_called():
    """`env.py` declares `WEBUI_NAME = 'Geomas'`. The PWA manifest is the other
    place a name reaches a user, and after the 0.11.3 port the two disagreed:
    all thirteen icons the manifest references were re-branded and the manifest
    itself still said «Open WebUI», so installing it gave you the Geomas icon
    under upstream's name.

    Asserted against `env.py` rather than against the literal, so the two
    cannot drift apart again in either direction.
    """
    import json
    import re

    manifest = json.loads(_committed('backend/open_webui/static/site.webmanifest'))
    env = _committed('backend/open_webui/env.py')
    declared = re.search(r"WEBUI_NAME\s*=\s*os\.getenv\(\s*'WEBUI_NAME'\s*,\s*'([^']+)'", env)

    assert declared, 'WEBUI_NAME default not found in env.py'
    assert manifest['name'] == declared.group(1), (manifest['name'], declared.group(1))
    assert manifest['short_name'] == declared.group(1), manifest['short_name']
