"""The served Open WebUI application: `open_webui.main.app` with the GeoTeaser routers mounted.

The deployment's uvicorn command names `open_webui.asgi:app`; `main.py` registers no
GeoTeaser router, so an app launched as `open_webui.main:app` (as `start.sh` and
`open-webui serve` do) serves none of the `/api/v1/geotizer` routes.
`app.state.geotizer_wrapper` is True only on an app built through this module.
"""

from fastapi import APIRouter, HTTPException

from open_webui.build_revision import build_revision
from open_webui.main import app
from open_webui.routers import geotizer

# Read here, at import, so the reading is taken while the process is starting
# rather than inside the first request that happens to want it -- git is a
# subprocess with a five-second ceiling, and a request should not be the thing
# that waits for it. `build_revision` caches, so every later reader gets this
# same answer.
#
# The reason recorded here used to be «so the working directory moving cannot
# change the answer». That stopped being true when the path became
# configuration: `checkout_path` reads an environment variable and falls back
# to this file's own parent, and neither is the working directory. Warming the
# cache still has the effect above; it never had that one.
BUILD_REVISION = build_revision()

SPA_MOUNT_NAME = 'spa-static-files'

_unmatched = APIRouter()


@_unmatched.api_route('/{unmatched_path:path}', methods=['GET', 'HEAD'])
async def _no_such_geotizer_path(unmatched_path: str) -> None:
    raise HTTPException(
        status_code=404,
        detail=f'no geotizer artifact at /{unmatched_path}',
    )


_before = len(app.router.routes)
app.include_router(geotizer.router, prefix='/api/v1/geotizer', tags=['geotizer'])
app.include_router(_unmatched, prefix='/api/v1/geotizer', include_in_schema=False)
_appended = len(app.router.routes) - _before

_spa = next(
    (
        index
        for index, route in enumerate(app.router.routes)
        if getattr(route, 'name', None) == SPA_MOUNT_NAME
    ),
    None,
)
if _spa is not None and _appended:
    _added = app.router.routes[-_appended:]
    del app.router.routes[-_appended:]
    app.router.routes[_spa:_spa] = _added

app.openapi_schema = None

app.state.geotizer_wrapper = True
