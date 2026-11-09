"""The served Open WebUI application: `open_webui.main.app` with the Geomas routers mounted.

The prod uvicorn command names `open_webui.asgi:app`. `main.py` stays as upstream ships
it, so an app launched as `open_webui.main:app` (as `start.sh` and `open-webui serve`
do) has no `/api/v1/gis-portal` routes and the data portal panel gets no ticket.
"""

from open_webui.main import app
from open_webui.routers import gis_portal

SPA_MOUNT_NAME = 'spa-static-files'

_before = len(app.router.routes)
# The GIS data portal panel's ticket (docs/gis-portal.md).
app.include_router(gis_portal.router, prefix='/api/v1/gis-portal', tags=['gis-portal'])
_appended = len(app.router.routes) - _before

# main.py mounts the SPA at '/' last; routes added after it would never be reached,
# so they are moved in front of it.
_spa = next(
    (index for index, route in enumerate(app.router.routes) if getattr(route, 'name', None) == SPA_MOUNT_NAME),
    None,
)
if _spa is not None and _appended:
    _added = app.router.routes[-_appended:]
    del app.router.routes[-_appended:]
    app.router.routes[_spa:_spa] = _added

app.openapi_schema = None
