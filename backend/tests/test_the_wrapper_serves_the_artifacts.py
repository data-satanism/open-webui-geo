"""Every GeoTeaser artefact is reachable on the app the deployment serves.

`open_webui.asgi` is that app. `main.py` no longer registers the router at
all -- it is byte-identical to upstream v0.11.0 -- so this file is the only
thing standing between a lost `include_router` line and five more days of dead
downloads. It replaces `test_the_router_is_mounted.py`, which asserted the
same contract against `open_webui.main:app` and became false the moment that
mount was removed. Repointed rather than deleted: the contract is «the served
app serves the artefacts», and only the app it names has changed.

The assertions are live requests, not `app.routes`. Under this FastAPI version
`include_router` leaves a lazy `_IncludedRouter` on `app.routes` rather than
flattening the child's `APIRoute`s into it, so no included path -- geotizer's
or upstream's -- is findable by iterating `app.routes` or by `url_path_for`;
`/api/v1/tools` is not there either. An assertion built that way passes
whether or not anything is mounted, which is the same defect one level up from
the one this file exists to catch.

**This file is now decisive, and it was not before.** While `main.py` also
mounted the router, both modules shared one `app` object and a request could
not say which registration answered it -- deleting the wrapper's
`include_router` left these tests green. With `main.py`'s mount gone, deleting
this module's line fails all six artefact cases and leaves the controls and the
marker passing. Verified on 2026-08-26.

`geotizer_wrapper` distinguishes an app served through this module from one
served straight from `open_webui.main`. `start.sh` and `open-webui serve` both
still name `open_webui.main:app`, which mounts nothing now, so a launch by
either path serves an app with no artefact routes -- the marker is what makes
that visible on boot rather than on a click.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_webui.routers.geotizer import ARTIFACTS

PREFIX = '/api/v1/geotizer'
#: A real run id, from the `af707b17` run log.
RUN_ID = 'af707b17-467e-408c-be65-1301b500bfd3'


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient

    from open_webui.asgi import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope='module')
def wrapper_app():
    from open_webui.asgi import app

    return app


@pytest.mark.parametrize('artifact', sorted(ARTIFACTS))
def test_every_artifact_url_is_served_by_the_wrapper(client, artifact):
    response = client.get(f'{PREFIX}/files/{RUN_ID}/{artifact}')

    assert response.status_code != 404, (
        f'{PREFIX}/files/<run_id>/{artifact} is not mounted on the wrapper app. '
        f'Check `app.include_router` in `backend/open_webui/asgi.py`.'
    )


def test_an_unmounted_path_still_404s(client):
    """The control. Without it the assertion above passes on any application
    that refuses every request before it routes one.

    Scoped to the fork's own prefix, and the third assertion this used to make
    is gone deliberately. `/api/v1/nosuchrouter/...` returns 200 `text/html`
    wherever a frontend build exists -- the SPA catch-all answers every path
    upstream has not routed, and `build/` is tracked on this base, so that is
    now every environment including CI. Asserting a 404 there would be
    asserting upstream's behaviour on upstream's surface, and making it true
    would mean claiming `/api/**` for the fork.

    What the fork can promise is its own prefix, which is what these two
    assertions hold it to.
    """
    assert client.get(f'{PREFIX}/files/{RUN_ID}/not_an_artifact.xlsx').status_code == 404
    assert client.get(f'{PREFIX}/nonsense').status_code == 404


def test_the_wrapper_marks_the_app_it_built(wrapper_app):
    """The marker the deployment check reads.

    Without it a wrong launch command is indistinguishable from a correct one
    until someone clicks a download -- the same silent shape this whole
    exercise is retiring. `open_webui.main` never sets it; only this module
    does.
    """
    assert wrapper_app.state.geotizer_wrapper is True


def test_the_marker_is_set_nowhere_else():
    """So the marker means «served through the wrapper» rather than «this
    string appears somewhere in the tree». If a second writer appears the
    marker stops distinguishing the two apps and this fails on the change that
    caused it."""
    
    backend = Path(__file__).resolve().parents[1]
    writers = sorted(
        path.relative_to(backend).as_posix()
        for path in backend.rglob('*.py')
        if 'geotizer_wrapper' in path.read_text(encoding='utf-8')
    )

    assert writers == [
        'open_webui/asgi.py',
        'tests/test_the_wrapper_serves_the_artifacts.py',
    ]


#: Run in a subprocess, with `FRONTEND_BUILD_DIR` pointing at a directory that
#: exists. It cannot be done in-process: `open_webui.env` reads that variable at
#: import time and `app` is a module singleton, so by the time a test could set
#: it the mount decision is already made.
_FRONTEND_PROBE = r'''
import json, sys
from fastapi.testclient import TestClient
from open_webui.asgi import app
from open_webui.routers.geotizer import ARTIFACTS

RUN = 'af707b17-467e-408c-be65-1301b500bfd3'
names = [getattr(r, 'name', None) for r in app.router.routes]
client = TestClient(app, raise_server_exceptions=False)

def probe(path):
    response = client.get(path)
    return [response.status_code, response.headers.get('content-type', '')]

print('@@' + json.dumps({
    'spa_mounted': 'spa-static-files' in names,
    'routes_after_spa': (
        len(names) - names.index('spa-static-files') - 1
        if 'spa-static-files' in names else None
    ),
    'artifacts': {
        name: probe(f'/api/v1/geotizer/files/{RUN}/{name}')
        for name in sorted(ARTIFACTS)
    },
    # Outside the fork's prefix on purpose: `/api/v1/geotizer/**` now 404s
    # through the wrapper's own catch-all, so it can no longer show that the
    # SPA mount is live. This path is routed by nobody.
    'unrouted': probe('/not-a-route-anyone-registered'),
}))
'''


def _with_frontend_build(tmp_path):
    """Import the wrapper in a fresh process with a frontend build present."""
    import json
    import os
    import subprocess
    import sys

    build = tmp_path / 'build'
    build.mkdir()
    # The mount only needs the directory; `index.html` is what SPAStaticFiles
    # falls back to, and the fallback is the defect's disguise.
    (build / 'index.html').write_text('<html>build</html>', encoding='utf-8')

    backend = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        'FRONTEND_BUILD_DIR': str(build),
        'WEBUI_SECRET_KEY': os.environ.get('WEBUI_SECRET_KEY', 'ci-not-a-real-secret'),
        'PYTHONPATH': os.pathsep.join(
            [str(backend), *filter(None, [os.environ.get('PYTHONPATH')])]
        ),
    }
    result = subprocess.run(
        [sys.executable, '-c', _FRONTEND_PROBE],
        cwd=backend.parent, env=env, capture_output=True, text=True, timeout=600,
    )
    line = next(
        (l for l in result.stdout.splitlines() if l.startswith('@@')),
        None,
    )
    assert line, f'probe produced no result\nstdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}'
    return json.loads(line[2:])


def test_the_artifacts_survive_a_frontend_build(tmp_path):
    """The configuration every other test in this repository cannot reach.

    `main.py` ends with `app.mount('/', SPAStaticFiles(...))` and Starlette
    matches in registration order, so that mount matches everything registered
    after it -- which is everything this wrapper does. The mount is conditional
    on `FRONTEND_BUILD_DIR` existing, and no test container has a built
    frontend, so the suite has only ever measured the one configuration where
    the defect cannot appear.

    It was not a 404 either. `SPAStaticFiles.get_response` falls back to
    `index.html` for any missing path that is not a `.js` file, so a request
    for `geotizer.xlsx` came back **200 with `text/html`** and the frontend's
    HTML as the body -- nothing raised, no error handler fired, and a client
    expecting a workbook got a web page.

    So `content-type` is the discriminator here, not the status code: with a
    catch-all in place every path returns 200, and only the header says whether
    the router or the SPA answered.
    """
    probe = _with_frontend_build(tmp_path)

    assert probe['spa_mounted'], (
        'the fixture did not produce the SPA mount, so this test is measuring '
        'the same blind spot it exists to close'
    )
    # The symptom first, so a failure leads with what a user would see.
    shadowed = {
        artifact: (status, content_type)
        for artifact, (status, content_type) in sorted(probe['artifacts'].items())
        if 'text/html' in content_type
    }
    assert shadowed == {}, (
        f'{len(shadowed)} of {len(probe["artifacts"])} artefacts were answered '
        f'by the SPA rather than the router: {shadowed}'
    )
    for artifact, (status, content_type) in sorted(probe['artifacts'].items()):
        assert status == 401, (artifact, status, content_type)
    # Then the cause, so the failure says why as well as what.
    assert probe['routes_after_spa'] == 0, (
        'a route registered after the catch-all is unreachable'
    )


def test_the_frontend_probe_proves_the_mount_is_live(tmp_path):
    """The control for the case above.

    «Not text/html» means nothing unless something in that process *is* served
    as text/html by the catch-all. A path nobody registered is, which is what
    shows the mount registered and really matching.

    It has to sit outside `/api/v1/geotizer` now. The wrapper answers every
    unmatched name under its own prefix with a 404, so the fork's prefix can
    no longer demonstrate that the SPA mount exists -- which is the point of
    that 404 and the reason this probe had to move.
    """
    probe = _with_frontend_build(tmp_path)
    status, content_type = probe['unrouted']

    assert status == 200 and 'text/html' in content_type, (status, content_type)
