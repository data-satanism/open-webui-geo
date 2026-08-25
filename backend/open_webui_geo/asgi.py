"""The Open WebUI application with the fork's routers mounted.

`main.py` is the file upstream edits most, and a merge has already deleted the
registration once -- silently, because an unmounted router raises nothing, boots
cleanly, and 404s only when a user clicks a link. Mounting from here keeps the
fork's additions out of the file most likely to lose them.

Serving this module instead of `open_webui.main:app` is one string in the
deployment's uvicorn command, specified separately. Until that changes this
module is built and tested but not served.

The deployment runs with `--reload`, so an import error here is loud: the
reloader logs it and retries rather than serving a half-built app.

**The lifespan shutdown hook does not move here, and on this version there is
no external registration to move it to.**
`drain_background_dispatches(timeout_seconds=5)` stays in `main.py`. The obvious
candidate is `app.router.on_shutdown.append(...)`, the way a shutdown callback
used to be attached from outside. Checked rather than assumed, because that
hook's absence was silent data loss for weeks: **Starlette 1.6.0 has removed it
entirely.** `Router.__init__` takes `routes, redirect_slashes, default,
lifespan, middleware, max_body_size` -- no `on_startup`, no `on_shutdown` -- a
`Router` instance has no `on_shutdown` attribute, and the string appears nowhere
in the class. `_DefaultLifespan.__aenter__`/`__aexit__` are both `pass`.

So the only registration point is the `lifespan=` argument, and `main.py`
passes one (`main.py:478`). It is consumed when the `FastAPI(...)` object is
constructed, which has already happened by the time this module imports `app`.
There is nothing version-safe to adopt here and nothing on a maybe. The hook
stays where it works, declared in the seam list and the footprint check.

**During the overlap this is a second registration, not the only one.**
`main.py` still mounts the same router, and must keep doing so while the launch
command still names `open_webui.main:app` -- those lines serve every download
today. Two consequences, both bounded and both ending when the follow-up removes
them: the routes are registered twice and FastAPI matches the first, and
regenerating the OpenAPI schema warns about duplicate operation ids. Neither
changes what any path returns.
"""

from open_webui.main import app
from open_webui.routers import geotizer

app.include_router(geotizer.router, prefix='/api/v1/geotizer', tags=['geotizer'])
app.openapi_schema = None          # the schema may already be cached

# Read by the test and by the deployment check: proves the served app came
# through this module rather than from open_webui.main directly.
app.state.geotizer_wrapper = True
