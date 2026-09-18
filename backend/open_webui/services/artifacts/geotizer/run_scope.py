"""Which run and which GIS project a specialist call belongs to.

The question this answers was asked by a log line. During an area fill of
«Тенгкели-Березовская площадь» the service log showed a specialist querying
`project_id=lekyn_new_data` — another project entirely — and nobody could say
whether a member's specialist had chosen it or a different run was open,
because the line carried no run id and the call carried no scope.

`scope_kb_tools` in the orchestrator solved the same shape for knowledge
collections: it strips `knowledge_ids` from the schema the model sees and
injects the run's own, and unscoped KB calls went from 88 to 0 — because the
argument stopped being the model's to get right. Four prompt attempts at this
class of problem have failed on this project and one wrapper has not failed.

The GIS tools are the same shape and cannot be bound the same way yet.
`scope_kb_tools` reads collections from `__metadata__`, which Open WebUI
populates for a chat; a GIS project id comes from the fill request and is
never in the chat's metadata. `run_agent_task` takes `agent`, `prompt`,
`mode`, `original_user_request` and `expected_output` and no scope argument at
all, so today nothing about the run reaches the specialist's tool calls.

So this is the first half, and it is the fork's: the fill records what it
resolved, and the adapter forwards it to the orchestrator when the installed
version can accept it. The second half — stripping `project_id` from the GIS
tool schema and injecting this value — is a Workspace Tool change and is not
in this repository.

A `ContextVar` rather than a parameter, for two reasons. `AgentCall` is
positional and every test fake implements it, so a new argument would break
them all to carry something none of them uses. And an area fills members
concurrently: a task started by `asyncio.gather` copies the context at
creation and each member sets its own, which a module-level value would not
survive.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

#: What the fill resolved, or an empty mapping outside any fill.
# `None`, not `{}`: a mutable default is one object shared by every context
# that never called `set`, and one call site reaching for it directly instead
# of through `current_gis_scope` would corrupt it for all of them -- the same
# symptom as the bugs this module exists to prevent. The sibling in
# `gis_service` defaults to an immutable string for the same reason.
_GIS_SCOPE: ContextVar[dict[str, str] | None] = ContextVar('geotizer_gis_scope', default=None)


def set_gis_scope(*, project_id: str | None, run_id: str | None) -> dict[str, str]:
    """Record this fill's scope for anything it calls. Returns what was set.

    Called once the fill has resolved its project, not at entry: before
    resolution there is nothing true to record, and a scope holding the
    caller's unresolved guess would be worse than none — that guess is exactly
    what `project_id` refusals exist to stop being believed.
    """
    scope = {
        key: value
        for key, value in (
            ('project_id', str(project_id or '').strip()),
            ('run_id', str(run_id or '').strip()),
        )
        if value
    }
    _GIS_SCOPE.set(scope)
    return scope


def current_gis_scope() -> dict[str, str]:
    """This fill's scope, or `{}` when there is no fill in progress.

    Empty is a true answer and is returned as one: a specialist call made
    outside any fill has no run to be attributed to, and inventing one would
    put a real run's id on somebody else's query.
    """
    return dict(_GIS_SCOPE.get() or {})


def scoped_arguments(accepted: Any) -> dict[str, str]:
    """The scope keywords an orchestrator build actually accepts.

    Feature detection by signature, the shape this adapter already uses for
    `run_agent_task` itself and for `licence_id` in the Workspace shim. A build
    that takes neither gets neither, and the caller says so once rather than
    failing every specialist call with an unexpected keyword.
    """
    scope = current_gis_scope()
    names = {'project_id': 'gis_project_id', 'run_id': 'geomas_run_id'}
    return {parameter: scope[key] for key, parameter in names.items() if key in scope and parameter in (accepted or {})}
