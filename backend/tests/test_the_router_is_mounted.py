"""The routes exist on the *application*, not merely on the router object.

`/api/v1/geotizer/files/{run_id}/geotizer.xlsx` returned 404 from 2026-08-20
until this test was written. `routers/geotizer.py` was intact and complete the
whole time; `14fc6e5f2`, the upstream version bump, deleted the two lines in
`main.py` that included it. Every GeoTeaser artefact download was dead and
every artefact reached its reader off disk.

Four existing checks all had a reason not to see it:

* the deferred-import resolver looks for a missing symbol -- nothing imported
  the router, so there was no symbol to miss;
* the seam check looks for a declaration that vanished -- `main.py` was never
  declared;
* the dead-definition ratchet looks for a definition nobody uses -- the router
  *is* used, by its own module;
* `test_every_artifact_has_a_stable_url` asserts that
  `@router.get('/files/{run_id}/…')` appears in the router's source text. It
  is a substring search over a file. It would pass if that file were never
  imported by anything.

That last one is the near miss and the reason this file exists: a test written
against the component cannot see that the component was never installed.

**Why a live request and not `app.routes`.** Under this FastAPI version
`include_router` leaves a lazy `_IncludedRouter` on `app.routes` rather than
flattening the child's `APIRoute`s into it -- 31 of them, against 40 routes
declared directly on `app`. So no included path, geotizer's or upstream's, can
be found by iterating `app.routes` or by `url_path_for`. An assertion built
that way would have been vacuous in a way nobody would notice, which is the
same defect one level up. Asking the application to route a request is the
only form that cannot lie.

**Why 401 is a pass.** The question is whether anything is mounted at the
path, not whether an anonymous caller may have it. `test_each_download_is_
authenticated` already owns the second question.

**Why the control matters.** «not 404» proves nothing on an application whose
middleware rejects everything before routing. `test_an_unmounted_path_still_
404s` pins that this application distinguishes the two, so the assertion above
it means what it says.
"""

from __future__ import annotations

import pytest

from open_webui.routers.geotizer import ARTIFACTS

PREFIX = '/api/v1/geotizer'
#: A real run id, from the `af707b17` run log. Any well-formed id routes the
#: same way; using one that existed keeps the request honest.
RUN_ID = 'af707b17-467e-408c-be65-1301b500bfd3'


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient

    from open_webui.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize('artifact', sorted(ARTIFACTS))
def test_every_artifact_url_is_mounted_on_the_application(client, artifact):
    response = client.get(f'{PREFIX}/files/{RUN_ID}/{artifact}')

    assert response.status_code != 404, (
        f'{PREFIX}/files/<run_id>/{artifact} is not mounted on the application. '
        f'The router may still declare it -- check `app.include_router` in '
        f'`backend/open_webui/main.py`.'
    )


def test_an_unmounted_path_still_404s(client):
    """The control. Without it the assertion above passes on any application
    that refuses every request before it routes one."""
    assert client.get(f'{PREFIX}/files/{RUN_ID}/not_an_artifact.xlsx').status_code == 404
    assert client.get(f'{PREFIX}/nonsense').status_code == 404
    assert client.get('/api/v1/nosuchrouter/files/x/y.xlsx').status_code == 404


def test_geotizer_is_the_only_router_the_fork_owns():
    """So the answer to «does any other fork router have this shape» is a
    checked fact rather than a claim in a commit message. If the fork adds a
    second router, this fails and that router needs its own mounted-ness
    assertion -- the defect is not specific to geotizer, only its discovery
    was.

    Read from the tree against upstream's own list rather than hard-coded:
    `scripts/check_upstream_footprint.py` already knows which files upstream
    ships, and duplicating that knowledge here is how the two drift.
    """
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    ours = {
        path.name
        for path in (root / 'backend/open_webui/routers').glob('*.py')
        if path.name != '__init__.py'
    }
    upstream = {
        line.rsplit('/', 1)[-1]
        for line in subprocess.run(
            ['git', 'ls-tree', '--name-only', 'upstream-v0.11.0',
             'backend/open_webui/routers/'],
            cwd=root, capture_output=True, text=True,
        ).stdout.split()
        if line.endswith('.py')
    }
    if not upstream:
        pytest.skip('the pinned upstream ref is not fetched in this checkout')

    assert ours - upstream == {'geotizer.py'}
