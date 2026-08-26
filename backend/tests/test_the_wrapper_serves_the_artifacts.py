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
    that refuses every request before it routes one."""
    assert client.get(f'{PREFIX}/files/{RUN_ID}/not_an_artifact.xlsx').status_code == 404
    assert client.get(f'{PREFIX}/nonsense').status_code == 404
    assert client.get('/api/v1/nosuchrouter/files/x/y.xlsx').status_code == 404


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
    from pathlib import Path

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
