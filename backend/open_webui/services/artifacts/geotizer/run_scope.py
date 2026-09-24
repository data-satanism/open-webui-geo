"""Which run and which GIS project a specialist call belongs to.

A fill records its resolved scope with `set_gis_scope`, and the adapter puts
it on every specialist call as `__metadata__[SCOPE_METADATA_KEY]` through
`scoped_metadata`. The scope mapping carries:

    project_id    binds every GIS tool call to the fill's project
    run_id        attributes the service's query log lines
    area_member   present and true only, for a fill that is one member of an
                  area

The scope is held in a `ContextVar`, so each concurrently filled area member
carries its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

_GIS_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar('geotizer_gis_scope', default=None)


AREA_MEMBER = 'area_member'


def set_gis_scope(
    *,
    project_id: str | None,
    run_id: str | None,
    area_member: bool = False,
) -> dict[str, Any]:
    """Record this fill's scope for anything it calls. Returns what was set.

    Called once the fill has resolved its project. An empty `project_id` or
    `run_id` is omitted. `area_member` is recorded as the bool `True` when set
    and is absent otherwise, never `False`.
    """
    scope: dict[str, Any] = {
        key: value
        for key, value in (
            ('project_id', str(project_id or '').strip()),
            ('run_id', str(run_id or '').strip()),
        )
        if value
    }
    if area_member:
        scope[AREA_MEMBER] = True
    _GIS_SCOPE.set(scope)
    return scope


def current_gis_scope() -> dict[str, Any]:
    """This fill's scope as a new dict, or `{}` when there is no fill in progress.

    A fill that resolved nothing also returns `{}`; `gis_scope_recorded` tells
    the two apart.
    """
    return dict(_GIS_SCOPE.get() or {})


def gis_scope_recorded() -> bool:
    """Whether a fill recorded a scope in this context, empty or not.

    `current_gis_scope()` returns `{}` both when no fill is running and when a
    fill resolved nothing; this returns True only for the second.
    """
    return _GIS_SCOPE.get() is not None


SCOPE_METADATA_KEY = 'geomas_gis_scope'


def scoped_metadata(metadata: Any) -> dict[str, Any]:
    """`metadata` with this fill's scope added, as a new mapping.

    `metadata` is copied, never mutated, and a non-mapping `metadata` is
    replaced by an empty mapping. The scope is added under
    `SCOPE_METADATA_KEY` whenever `gis_scope_recorded()` is true, even when it
    is empty.
    """
    base = dict(metadata) if isinstance(metadata, Mapping) else {}
    if gis_scope_recorded():
        base[SCOPE_METADATA_KEY] = current_gis_scope()
    return base
