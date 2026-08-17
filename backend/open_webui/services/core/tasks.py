"""The agent task descriptor, shared by the evidence core and the artefacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


# There is no producer-to-agent translation, and this file is where one kept
# being put. Three shapes stood here across as many rounds -- a compiled table,
# a name-sniffing fallback behind it, then a `PRODUCER_KIND_MAP` valve -- and
# each was a second place the routing could be wrong. Both of the outages this
# work has caused came from that second place rather than from either end of it.
#
# `multitask_orchestration` v4.0.0 removed the tool-side half. What remains is a
# pass-through: the batch plan's `producer` IS the agent name, it travels
# verbatim, and the only question asked of it is asked where the answer lives --
# `run_agent_task` refuses an agent it has no model valve and no tool surface
# for, naming what it does serve. `geotizer_assignments.v2` made that honest by
# renaming the eight batch owners to `gis`, `kb`, `web` and `skilled`, which are
# exactly the four agents the tool serves.
#
# So there is deliberately no agent set in this module. Enumerating one here
# would be a second list that drifts from the tool's, which is the defect in a
# new spelling. If the batch plan renames its owners again, the fix is a tool
# edit adding or renaming an agent -- the same artefact that already holds that
# agent's model valve and tool surface. One place, not two.
#
# And not by inference. Nothing here may derive an agent from a substring of a
# name: a producer named conventionally enough to be guessed would route a whole
# batch on the guess and report nothing, which is worse than the refusal it
# replaces.


@dataclass(frozen=True)
class AgentTask:
    """One specialist call.

    `agent` is the name the batch plan gave the batch's owner, unchanged. It is
    not a kind this repository assigns, which is why it is not called one -- the
    field was `kind` while a translation existed, and keeping that name after
    the translation went would imply a step that no longer happens.
    """

    agent: str
    producer: str
    role: Literal['contributor', 'owner']
    task_id: str
    payload: Mapping[str, Any]
