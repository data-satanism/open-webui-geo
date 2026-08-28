"""The Open WebUI application with the fork's routers mounted.

`main.py` is the file upstream edits most, and a merge has already deleted the
registration once -- silently, because an unmounted router raises nothing,
boots cleanly, and 404s only when a user clicks a link. `14fc6e5f2` deleted
five fork additions from that file in one go; `/api/v1/geotizer/*` returned 404
for five days before anyone noticed. Mounting from here keeps the fork's
additions out of the file most likely to lose them.

This is the served app. The deployment's uvicorn command names
`open_webui.asgi:app`, and `main.py` no longer registers the router at all --
it is byte-identical to upstream v0.11.0, carries no seam, and has left
`check_upstream_footprint.py`'s declarations entirely. Nothing for a merge to
delete means nothing a merge can silently take.

It lives inside `open_webui/` rather than in a package of its own because a
package holding only the wrapper would be an inconsistency rather than a
boundary: nine fork-authored files already sit in this tree,
`utils/tools.py:109` imports `open_webui.tools.geotizer` by path, and the
`services/` import-boundary check is keyed to its location. Being here, it is
fork-authored code inside upstream's tree and is declared as such.

The deployment runs with `--reload`, so an import error here is loud: the
reloader logs it and retries rather than serving a half-built app.

Anyone launching by `start.sh` or `open-webui serve` bypasses this module --
both still name `open_webui.main:app`, which no longer mounts anything. The
`geotizer_wrapper` marker is what makes that detectable on boot rather than on
a click.
"""

from fastapi import APIRouter, HTTPException

from open_webui.main import app
from open_webui.routers import geotizer

#: The name `main.py` gives the SPA catch-all it mounts at `/`.
SPA_MOUNT_NAME = 'spa-static-files'

# Registered, then moved ahead of the SPA mount. Appending is not enough.
#
# `main.py` ends with `app.mount('/', SPAStaticFiles(...), name='spa-static-files')`
# and Starlette matches routes in registration order, so a `Mount('/')` matches
# everything after it. Anything registered once `main.py` has finished importing
# -- which is everything this module does -- is unreachable.
#
# The symptom is worse than a 404. `SPAStaticFiles.get_response` falls back to
# `index.html` for any missing path that is not a `.js` file, so a request for
# `geotizer.xlsx` returned **200 with `text/html`** and the frontend's HTML in
# the body. Nothing raises, no error handler fires, and the client gets a web
# page where a workbook should be.
#
# It hid because the mount is conditional on `FRONTEND_BUILD_DIR` existing. No
# container without a built frontend registers it, which is every test
# environment, so the routes were reachable everywhere the suite could look.
# `test_the_wrapper_serves_the_artifacts` builds one deliberately for exactly
# this reason.
#
# The slice rather than a single `pop()`: `include_router` appends one
# `_IncludedRouter` on this FastAPI version and could append one `APIRoute` per
# path on another. Measuring what it added covers both without asserting which.
#: A name under the fork's own prefix that no artefact route claims.
#
# Getting the real routes ahead of the SPA mount fixed the artefacts and left
# the other half standing: a *misspelled* artefact name still matched nothing,
# fell through to `Mount('/')`, and came back 200 `text/html` with the
# frontend's index page in the body. A client asking for a workbook that does
# not exist was handed a web page and a success code, which is worse than the
# 404 it should have had -- a caller checking `response.ok` proceeds, and only
# the parser downstream finds out.
#
# Registered after the artefact routes, so Starlette's in-order matching gives
# them first refusal, and scoped to `/api/v1/geotizer` alone. Upstream's 404
# behaviour on upstream's paths is upstream's business; this claims only the
# prefix the fork owns.
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
# `None` is the API-only deployment, where `main.py` logged «Serving API only.»
# and mounted nothing. There is no catch-all to get ahead of and the routes are
# already reachable, so the order is left exactly as it was.
if _spa is not None and _appended:
    _added = app.router.routes[-_appended:]
    del app.router.routes[-_appended:]
    # `_spa` is still correct after the delete: everything removed sat after it.
    app.router.routes[_spa:_spa] = _added

app.openapi_schema = None          # the schema may already be cached

# Read by the test and by the deployment check: proves the served app came
# through this module rather than from open_webui.main directly.
app.state.geotizer_wrapper = True
