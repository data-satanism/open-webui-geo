"""The same contract as `test_the_router_is_mounted.py`, against the wrapper.

`open_webui_geo.asgi` is the app the deployment will serve once its uvicorn
command names it. That is one string outside this repository, and until it
changes this module is built and tested but not served -- so this file is what
says the wrapper works *before* anyone points production at it. A repository
change that silently depends on a deployment change nobody made is how the
router came to be unmounted in the first place.

The assertions are the live-request form for the reason
`test_the_router_is_mounted.py` gives at length: under this FastAPI version
`include_router` leaves a lazy `_IncludedRouter` on `app.routes` rather than
flattening the child's `APIRoute`s into it, so no included path -- geotizer's
or upstream's -- is findable by iterating `app.routes` or by `url_path_for`.
An assertion built that way passes regardless of whether anything is mounted.

**What this file can and cannot prove during the overlap.** `main.py` still
mounts the same router, and must, because the launch command still names
`open_webui.main:app`. Both modules share one `app` object, so a request
routed here cannot distinguish which registration answered it -- and deleting
the wrapper's `include_router` does *not* fail these tests while `main.py`'s
line stands. The decisive experiment is the other one: with `main.py`'s
registration removed and the wrapper's kept, these tests pass and
`test_the_router_is_mounted.py` fails. That was run, and it is what the
verification rests on until the follow-up removes `main.py`'s lines and this
file becomes decisive on its own.

`geotizer_wrapper` is the part that is unambiguous today: it is set by this
module and by nothing else, so it distinguishes an app served through the
wrapper from one served straight from `open_webui.main`. That is what makes a
wrong launch command detectable on boot rather than on a click.
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

    from open_webui_geo.asgi import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope='module')
def wrapper_app():
    from open_webui_geo.asgi import app

    return app


@pytest.mark.parametrize('artifact', sorted(ARTIFACTS))
def test_every_artifact_url_is_served_by_the_wrapper(client, artifact):
    response = client.get(f'{PREFIX}/files/{RUN_ID}/{artifact}')

    assert response.status_code != 404, (
        f'{PREFIX}/files/<run_id>/{artifact} is not mounted on the wrapper app. '
        f'Check `app.include_router` in `backend/open_webui_geo/asgi.py`.'
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
        'open_webui_geo/asgi.py',
        'tests/test_the_wrapper_serves_the_artifacts.py',
    ]
