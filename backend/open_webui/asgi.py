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

from open_webui.main import app
from open_webui.routers import geotizer

app.include_router(geotizer.router, prefix='/api/v1/geotizer', tags=['geotizer'])
app.openapi_schema = None          # the schema may already be cached

# Read by the test and by the deployment check: proves the served app came
# through this module rather than from open_webui.main directly.
app.state.geotizer_wrapper = True
