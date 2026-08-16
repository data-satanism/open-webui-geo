"""The agent task descriptor, shared by the evidence core and the artefacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


AgentKind = Literal['gis', 'kb', 'web', 'skilled']


# These four names are `gis_service`'s, not this repository's. They come from
# `assignment_policy.json` under `policy_version: geotizer_assignments.v1`, a
# hash-pinned contract asset, and reach here as the `producer` field of a batch
# and of each evidence route. The `_yulong` suffix is part of the contract, not
# a leftover: `assignment_policy.json -> producer -> PRODUCER_AGENT_KIND ->
# valves.GIS_MODEL` is the whole chain that decides which model serves a
# specialist call. Renaming a key here renames nothing upstream; it only stops
# the lookup matching.
PRODUCER_AGENT_KIND: Mapping[str, AgentKind] = {
    'GISagent_yulong': 'gis',
    'KBagent_yulong': 'kb',
    'WEBagent_yulong': 'web',
    'SkilledAgent': 'skilled',
}


# Which is why the table alone is not enough. The service can add a producer or
# spell one differently without this repository knowing, and a table miss aborts
# the whole run at the first batch. Inferring the kind from the name costs a log
# line and keeps the run going; only a name that matches nothing, or matches two
# kinds at once, is a genuine error.
_PRODUCER_KIND_HINTS: tuple[tuple[str, AgentKind], ...] = (
    ('gis', 'gis'),
    ('kb', 'kb'),
    ('knowledge', 'kb'),
    ('web', 'web'),
    ('skilled', 'skilled'),
)


def infer_agent_kind(producer: str) -> AgentKind | None:
    """Resolve a kind from an unmapped producer name, or None if ambiguous.

    Ambiguity is not a tie to be broken. A producer whose name contains both
    'kb' and 'web' could be either, and guessing would route a whole batch to
    the wrong model quietly -- so it returns None and the caller raises.
    """
    folded = producer.casefold()
    kinds = {kind for hint, kind in _PRODUCER_KIND_HINTS if hint in folded}
    return kinds.pop() if len(kinds) == 1 else None


@dataclass(frozen=True)
class AgentTask:
    kind: AgentKind
    producer: str
    role: Literal['contributor', 'owner']
    task_id: str
    payload: Mapping[str, Any]
