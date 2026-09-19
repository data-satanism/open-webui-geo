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

The GIS tools are the same shape, and they travel the same channel.
`run_agent_task` takes `agent`, `prompt`, `mode`, `original_user_request` and
`expected_output` and no scope argument at all — but it also takes
`__metadata__`, as every Open WebUI tool does, and that is where
`scope_kb_tools` reads its collections from. A GIS project id never arrives
in `__metadata__` by any other route, because Open WebUI populates it from
the chat and a chat has no project, so the fork can put one there under its
own key without displacing anything.

This is the fork's half and it is now complete: the fill records what it
resolved, and the adapter puts it on every specialist call as
`__metadata__['geomas_gis_scope']`. The second half — stripping `project_id`
from the GIS tool schema and injecting this value, the way `scope_kb_tools`
strips `knowledge_ids` — is a Workspace Tool change and is not in this
repository. Until it lands the key is carried and unread, which is a
different state from the one before this change: unread by a tool that could
read it, rather than never sent.

An earlier version of this module forwarded the scope as keyword arguments
to builds whose signature declared `gis_project_id` and `geomas_run_id`. No
build declares them, so it forwarded nothing on every call ever made, and
the area run of «Тенгкели-Березовская площадь» came back with six of seven
members answering about a project three thousand kilometres away.

A `ContextVar` rather than a parameter, for two reasons. `AgentCall` is
positional and every test fake implements it, so a new argument would break
them all to carry something none of them uses. And an area fills members
concurrently: a task started by `asyncio.gather` copies the context at
creation and each member sets its own, which a module-level value would not
survive.
"""

from __future__ import annotations

from collections.abc import Mapping
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


def gis_scope_recorded() -> bool:
    """Whether a fill recorded a scope in this context, empty or not.

    `current_gis_scope()` returns `{}` for both «no fill is running» and «a
    fill ran and resolved nothing», and those are different facts about the
    call. The first says this adapter carries no scope; the second says it
    carries one and the fill had nothing to put in it. Only the second should
    reach the orchestrator as a key: a key that is present and empty is the
    fork stating «this run has no project», while an absent key is the fork
    saying nothing at all, and a tool reading them alike cannot tell an old
    WebUI from a run that resolved nothing.
    """
    return _GIS_SCOPE.get() is not None


#: Where the scope travels, and under what name.
#:
#: `__metadata__` rather than a new argument, because `__metadata__` is
#: already one of the parameters Open WebUI injects into every tool call and
#: `run_agent_task` already declares it. A build that wants the scope needs no
#: signature change to read it, and a build that does not want it is unharmed
#: by one more key -- which is why this replaced the signature-detection path
#: that stood here. That path forwarded the scope only to a build whose
#: signature accepts `gis_project_id`, and no build's does, so it returned
#: `{}` on every call ever made while looking exactly like a binding.
#:
#: This is the channel `scope_kb_tools` already reads collections from:
#: `marked_collections(extra_params['__metadata__'])`. A GIS project id never
#: enters `__metadata__` by any other route -- Open WebUI populates it from
#: the chat, and a chat has no project -- so the key cannot collide with
#: anything the platform put there.
SCOPE_METADATA_KEY = 'geomas_gis_scope'


def scoped_metadata(metadata: Any) -> dict[str, Any]:
    """`metadata` with this fill's scope added, as a new mapping.

    A copy, never a mutation. One `__metadata__` dict is built per tool
    invocation and shared by every specialist call the run makes, and an area
    fills its members concurrently: writing into it would put the last
    member's project on every other member's calls -- the defect this module
    exists to close, reintroduced by the fix for it.

    A non-mapping `metadata` is replaced rather than refused. The adapter
    already passes `runtime['__metadata__'] or {}`, and a build that sends
    something else is a build whose specialist calls should still carry the
    scope; dropping it to preserve a value that is not a mapping would be
    protecting the wrong thing.
    """
    base = dict(metadata) if isinstance(metadata, Mapping) else {}
    if gis_scope_recorded():
        base[SCOPE_METADATA_KEY] = current_gis_scope()
    return base
