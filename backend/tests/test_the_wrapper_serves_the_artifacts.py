"""Tests, by live requests, that every GeoTeaser artefact route is served by the `open_webui.asgi` app and that the app
carries the `geotizer_wrapper` marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_webui.routers.geotizer import ARTIFACTS

PREFIX = '/api/v1/geotizer'
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
    """An unknown artefact name and an unknown path under the GeoTeaser prefix return 404."""
    assert client.get(f'{PREFIX}/files/{RUN_ID}/not_an_artifact.xlsx').status_code == 404
    assert client.get(f'{PREFIX}/nonsense').status_code == 404


def test_the_wrapper_marks_the_app_it_built(wrapper_app):
    """The `open_webui.asgi` app has `state.geotizer_wrapper` set to True."""
    assert wrapper_app.state.geotizer_wrapper is True


def test_the_marker_is_set_nowhere_else():
    """Only `open_webui/asgi.py` and this test mention `geotizer_wrapper`."""
    
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
    """With a frontend build present, every artefact route is answered by the router, not the SPA mount, and no route
    follows the SPA mount.
    """
    probe = _with_frontend_build(tmp_path)

    assert probe['spa_mounted'], (
        'the fixture did not produce the SPA mount, so this test is measuring '
        'the same blind spot it exists to close'
    )
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
    assert probe['routes_after_spa'] == 0, (
        'a route registered after the catch-all is unreachable'
    )


def test_the_frontend_probe_proves_the_mount_is_live(tmp_path):
    """With a frontend build present, an unrouted path outside the GeoTeaser prefix is answered by the SPA mount as
    `text/html`.
    """
    probe = _with_frontend_build(tmp_path)
    status, content_type = probe['unrouted']

    assert status == 200 and 'text/html' in content_type, (status, content_type)
