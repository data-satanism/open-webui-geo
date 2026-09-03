"""What a specialist actually searched for, captured where the search happens.

Four clean runs of one build filled 207, 191, 219 and 137 of 351 cells. The
corpus was stable across all four — the same three documents cited in every
run — and the same document yielded 103 citations in one and 58 in another. So
the variance is not in *which* collections were searched but in what was asked
of them, and the queries have never been recorded anywhere.

They could not be. `retrieval_queries` was written from the RAG-v2 retrieval
*plans* — what an owner was asked to look for — and only when a dispatcher was
active or shadowing, which on an ordinary run it is not. The plan is built from
the batch and barely moves between runs; the spread is in what the specialist
did with it, inside a tool loop that runs in the orchestrator Workspace Tool.

This module sits where that loop lands: `query_knowledge_files` and
`grep_knowledge_files` are this fork's builtins, and every orchestrated
specialist search calls one of them. It records the query verbatim.

**Verbatim, never normalised.** The question is why two runs read one document
to different depths; a truncated or lower-cased query cannot answer it. The
only bound is on how many are kept, and the entry that trips the bound says so
rather than the list silently ending.

## How a query finds its run

There is no run id in an orchestrated call's metadata — `is_orchestrated_call`
exists because `request.state.internal` is the only marker there is, and the
specialist's sub-run carries a different request object from the one the
GeoTeaser tool was called with. So the identity travels in a `ContextVar`:
the workflow opens a scope around each specialist call, and the context is
copied into every task and thread the call creates beneath it. A search issued
outside any scope — a person chatting — records nothing, which is both the
privacy answer and the correct one.

The sink is held here rather than in `services/`: `services/` may not import
`open_webui` (the purity boundary), so the core takes a drain through injection
the way it takes `gis_call` and the RAG dispatcher, and the effect shell hands
it this.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

#: How many queries one run keeps. A run issues a few per chunk across ~20
#: batches; this is high enough not to bind in practice and low enough that a
#: pathological loop cannot fill a run log.
MAX_RECORDED_QUERIES = 400

ISSUED = 'issued'

_SCOPE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    'geotizer_query_scope', default=None
)


@contextmanager
def recording_queries(
    log_sink: list[dict[str, Any]],
    *,
    agent: str,
    batch_id: str,
    chunk: str | None,
    attempt: int | None = None,
) -> Iterator[None]:
    """Attribute every search issued inside this block to one specialist call.

    Re-entrant by construction: the token restores whatever scope was active,
    so a nested call cannot strand the outer one.
    """
    token = _SCOPE.set(
        {
            'sink': log_sink,
            'agent': str(agent or ''),
            'batch_id': str(batch_id or ''),
            'chunk': chunk,
            'attempt': attempt,
        }
    )
    try:
        yield
    finally:
        _SCOPE.reset(token)


def is_recording() -> bool:
    return _SCOPE.get() is not None


def record_query(
    *,
    tool: str,
    query: str,
    collections: Sequence[str] = (),
    results: int | None = None,
    result_sources: Sequence[str] = (),
) -> None:
    """Record one search as issued. Never raises into the search that made it.

    A diagnostic that can break a knowledge search is worse than no diagnostic:
    the run would lose cells to the instrument meant to explain why it loses
    cells.
    """
    try:
        scope = _SCOPE.get()
        if scope is None:
            return
        sink = scope['sink']
        if len(sink) >= MAX_RECORDED_QUERIES:
            if not any(item.get('truncated') for item in sink):
                sink.append({'truncated': True, 'recorded': MAX_RECORDED_QUERIES})
            return
        sink.append(
            {
                'source': ISSUED,
                'tool': str(tool),
                'agent': scope['agent'],
                'batch_id': scope['batch_id'],
                'chunk': scope['chunk'],
                'attempt': scope['attempt'],
                # Verbatim. Not stripped, not lower-cased, not shortened.
                'query': query,
                'collections': [str(item) for item in collections],
                'results': results,
                'result_sources': [str(item) for item in result_sources],
            }
        )
    except Exception:  # noqa: BLE001 - see the docstring
        log.debug('geotizer query sink refused an entry', exc_info=True)


class QueryDrain:
    """The injected face of the sink, and everything the core uses of it.

    The core holds a Protocol with these two methods and no import of
    `open_webui`; this is the implementation the effect shell hands over.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def recording(
        self,
        *,
        agent: str,
        batch_id: str,
        chunk: Mapping[str, Any] | str | None,
        attempt: int | None = None,
    ):
        label = (
            f'{chunk.get("index")}/{chunk.get("total")}'
            if isinstance(chunk, Mapping)
            else (str(chunk) if chunk is not None else None)
        )
        return recording_queries(
            self._entries,
            agent=agent,
            batch_id=batch_id,
            chunk=label,
            attempt=attempt,
        )

    def drain(self) -> list[dict[str, Any]]:
        """Everything recorded so far. Read at run-log assembly, once."""
        return list(self._entries)
