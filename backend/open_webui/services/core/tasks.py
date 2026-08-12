"""The agent task descriptor, shared by the evidence core and the artefacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


AgentKind = Literal['gis', 'kb', 'web', 'skilled']


PRODUCER_AGENT_KIND: Mapping[str, AgentKind] = {
    'GISagent_yulong': 'gis',
    'KBagent_yulong': 'kb',
    'WEBagent_yulong': 'web',
    'SkilledAgent': 'skilled',
}


@dataclass(frozen=True)
class AgentTask:
    kind: AgentKind
    producer: str
    role: Literal['contributor', 'owner']
    task_id: str
    payload: Mapping[str, Any]
