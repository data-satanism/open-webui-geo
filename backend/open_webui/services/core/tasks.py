"""The agent task descriptor, shared by the evidence core and the artefacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from ..geotizer.errors import GeotizerOrchestrationError


AgentKind = Literal['gis', 'kb', 'web', 'skilled']

# Derived from the annotation rather than written out beside it, so a fifth
# kind cannot be accepted by the valve parser while the type still says four.
AGENT_KINDS: frozenset[str] = frozenset(get_args(AgentKind))


# `assignment_policy.json -> producer -> PRODUCER_KIND_MAP -> valves.GIS_MODEL`
# is the chain that decides which model serves a specialist call, and only the
# middle link is configurable from outside. The producer names are
# `gis_service`'s, written in a hash-pinned contract asset that this repository
# does not own, so a table of them compiled into Git is a copy that goes stale
# silently on the day the service renames one. `PRODUCER_KIND_MAP` is a valve on
# `multitask_orchestration`, configured in Workspace beside the four model
# valves it feeds, and this repository ships no default for it: a contour nobody
# has configured must say so rather than guess.
#
# That day arrived. `policy_version: geotizer_assignments.v2` renamed the eight
# specialist producers to the four agent kinds, so the valve an operator writes
# today is `gis=gis,kb=kb,web=web,skilled=skilled` -- a near-identity. Two
# things it is tempting to conclude from that, and both are wrong. The valve is
# not now redundant: the names still belong to the service, `.v3` can move them
# again, and the whole point of the middle link is that the move costs a
# Workspace edit rather than a deploy. And the identity must not be shipped as a
# default, for the reason directly below -- a contour running on a default is a
# contour whose routing nobody chose, which is indistinguishable from one whose
# operator has not looked at it yet.
#
# A table stood here until the round before this one, and behind it an
# `infer_agent_kind` fallback that read 'gis'/'kb'/'web'/'skilled' out of the
# producer's spelling. Both are gone, and the fallback in particular is not
# coming back as a fix for the failure below. It hides the exact
# misconfiguration the valve exists to surface -- an unconfigured contour whose
# producers happen to be conventionally named runs green while routing every
# batch on a guess about somebody else's naming convention, and reports nothing
# -- whereas the strictness costs a run that stops at its first batch with a
# message naming the producer and the valve, which an operator fixes once.


def parse_producer_kind_map(raw: str) -> dict[str, AgentKind]:
    """Parse the `PRODUCER_KIND_MAP` valve's `producer=kind,producer=kind` text.

    Every rejection here is one that would otherwise land mid-run. A valve is a
    free-text field an operator types into, and each way it goes wrong -- an
    entry with no `=`, a kind outside the four, the same producer written twice
    -- stays invisible until a batch carrying that producer arrives, which can
    be the fortieth batch of a run that has already spent its specialist calls.
    Parsing strictly at read time turns all of them into a message before the
    run starts.

    A duplicate key is rejected even when both sides agree, because the two
    spellings of the same intent are indistinguishable from a half-finished
    edit, and the one that wins is whichever came last in a text field.

    An empty valve is not an error: it parses to an empty map and fails at the
    first lookup instead, where `agent_kind_for_producer` can name the producer
    that was actually asked for. Blank segments are skipped for the same reason
    -- a trailing comma has nothing in it to get wrong.
    """
    mapping: dict[str, AgentKind] = {}
    for segment in raw.split(','):
        entry = segment.strip()
        if not entry:
            continue
        left, separator, right = entry.partition('=')
        producer = left.strip()
        kind = right.strip()
        if not separator or not producer or not kind:
            raise GeotizerOrchestrationError(
                f'PRODUCER_KIND_MAP entry {entry!r} is not producer=kind; the valve format is '
                '"ProducerName=kind,OtherProducer=kind"'
            )
        if kind not in AGENT_KINDS:
            raise GeotizerOrchestrationError(
                f'PRODUCER_KIND_MAP entry {entry!r} names agent kind {kind!r}, which does not exist; '
                f'the kinds are {sorted(AGENT_KINDS)}'
            )
        if producer in mapping:
            raise GeotizerOrchestrationError(
                f'PRODUCER_KIND_MAP maps producer {producer!r} twice, to {mapping[producer]!r} and {kind!r}; '
                f'remove one so the routing is not decided by entry order'
            )
        mapping[producer] = kind
    return mapping


@dataclass(frozen=True)
class AgentTask:
    kind: AgentKind
    producer: str
    role: Literal['contributor', 'owner']
    task_id: str
    payload: Mapping[str, Any]
