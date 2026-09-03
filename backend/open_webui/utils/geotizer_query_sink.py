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
to different depths; a truncated or lower-cased query cannot answer it.

Two bounds, and both report themselves as *numbers beside the list* rather than
as entries inside it. Runs `82365089` and `26aaf34a` both stopped at exactly
401 entries — 400 records and a sentinel `{"recorded": 400, "truncated": true}`
sitting in the same array. That sentinel was two defects. It made the count
meaningless as a measurement: 401 in both runs did not mean the two runs issued
the same number of searches, it meant both exceeded 400 and neither said by how
much. And it made the array heterogeneous: an object with no `agent`, no `tool`
and no `query`, which every consumer that groups by agent or iterates tools has
to know to skip, with nothing in the shape to say so.

So the array now holds query records and nothing else, and `retrieval_query_stats`
beside it carries `issued`, `recorded` and `dropped`. `issued` counts every
search the run made, which is a measurement whether or not the cap bound.

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

#: How many queries one run keeps. Runs `82365089` and `26aaf34a` issued more
#: than 400 each once the WEB half started recording, so the old bound was not
#: "high enough not to bind in practice" — it bound on the first pair that
#: exercised it, and every comparison of those two query sets compares two
#: truncated prefixes. Four times the observed volume, still low enough that a
#: pathological loop cannot fill a run log, and `issued` counts the real number
#: either way.
MAX_RECORDED_QUERIES = 2000

#: A backstop on one entry's size, applied after duplicate alternatives are
#: collapsed. Nothing observed comes close: post-collapse the longest query in
#: either run is 267 characters, a percent-encoded URL from `fetch_url`. This
#: exists so that a single entry can never be the thing that makes a run log
#: unreadable, and when it fires it says so.
MAX_RECORDED_QUERY_CHARS = 4096

ISSUED = 'issued'

#: Characters that give `|` a meaning other than "either of these two
#: alternatives at the top level". If a pattern contains any of them, its
#: alternatives are left exactly as written — collapsing them could change what
#: the pattern matches, and a diagnostic may not do that.
_REGEX_STRUCTURE = frozenset('()[]{}\\')


def collapse_repeated_alternatives(query: str) -> tuple[str, int, int]:
    """`a|b|a|b|a` -> `a|b`, and only when that provably matches the same text.

    Run `26aaf34a` issued a 26,432-character pattern: 2,520 alternatives of
    which **10 were distinct**, the token `линия` repeated thousands of times.
    Run `a067e802` issued a 31,943-character one, 5,319 alternatives and 11
    distinct. Both on the infrastructure batch, both on distance-and-railway
    phrasings. A repeated alternative cannot match anything the first
    occurrence did not, so removing it is not a narrowing of the search — it is
    the same search written once.

    Returns the collapsed query and the two counts, so the record can say a
    collapse happened without carrying 26 KB to prove it.
    """
    if '|' not in query:
        return query, 1, 1
    if any(character in _REGEX_STRUCTURE for character in query):
        # A group, a class or an escape can make `|` mean something else. Leave
        # it alone: an unbounded record is better than a changed search.
        return query, query.count('|') + 1, query.count('|') + 1
    parts = query.split('|')
    seen: dict[str, None] = {}
    for part in parts:
        seen.setdefault(part, None)
    return '|'.join(seen), len(parts), len(seen)

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
    counter: dict[str, int] | None = None,
) -> Iterator[None]:
    """Attribute every search issued inside this block to one specialist call.

    Re-entrant by construction: the token restores whatever scope was active,
    so a nested call cannot strand the outer one.
    """
    token = _SCOPE.set(
        {
            'sink': log_sink,
            'counter': counter if counter is not None else {},
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
    searched_collections: Sequence[str] = (),
    results: int | None = None,
    result_sources: Sequence[str] = (),
    result_document_ids: Sequence[str] = (),
    result_collection_ids: Sequence[str] = (),
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
        counter = scope['counter']
        # Counted before the cap is consulted: `issued` is how many searches the
        # run made, and it stays a measurement after `recorded` stops moving.
        counter['issued'] = counter.get('issued', 0) + 1
        sink = scope['sink']
        if len(sink) >= MAX_RECORDED_QUERIES:
            counter['dropped'] = counter.get('dropped', 0) + 1
            return

        # Verbatim, with one provably-equivalent rewrite: repeated top-level
        # alternatives are collapsed, because `a|b|a` and `a|b` match the same
        # text and one of them is 26 KB.
        recorded_query, alternatives, distinct = collapse_repeated_alternatives(query)
        entry: dict[str, Any] = {
            'source': ISSUED,
            'tool': str(tool),
            'agent': scope['agent'],
            'batch_id': scope['batch_id'],
            'chunk': scope['chunk'],
            'attempt': scope['attempt'],
            'query': recorded_query,
            'collections': [str(item) for item in collections],
            # Which collections were actually read, as opposed to which the
            # caller named. On a call that named none these are the ones the
            # tool enumerated for itself, and that is the only way an unscoped
            # search is visible in the artefact at all.
            'searched_collections': [str(item) for item in searched_collections],
            'results': results,
            'result_sources': [str(item) for item in result_sources],
            # Names are what a person reads; ids are what joins. The first
            # pair recorded only names and the citation join returned 0 on
            # every entry, because a cell's locator carries a uuid and a
            # KB result carries a filename.
            'result_document_ids': [
                str(item) for item in result_document_ids if str(item).strip()
            ],
        }
        if result_collection_ids:
            entry['result_collection_ids'] = [str(item) for item in result_collection_ids]
        if distinct != alternatives:
            # The numbers, not the 26 KB that produced them.
            entry['alternatives_received'] = alternatives
            entry['alternatives_distinct'] = distinct
            entry['query_chars_received'] = len(query)
        if len(entry['query']) > MAX_RECORDED_QUERY_CHARS:
            entry['query_chars'] = len(entry['query'])
            entry['query_truncated'] = True
            entry['query'] = entry['query'][:MAX_RECORDED_QUERY_CHARS]
        sink.append(entry)
    except Exception:  # noqa: BLE001 - see the docstring
        log.debug('geotizer query sink refused an entry', exc_info=True)


class QueryDrain:
    """The injected face of the sink, and everything the core uses of it.

    The core holds a Protocol with these two methods and no import of
    `open_webui`; this is the implementation the effect shell hands over.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._counter: dict[str, int] = {}

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
            counter=self._counter,
        )

    def drain(self) -> list[dict[str, Any]]:
        """Everything recorded so far. Read at run-log assembly, once."""
        return list(self._entries)

    def stats(self) -> dict[str, Any]:
        """How many searches the run made, and how many of them are above.

        A sibling of the list rather than an entry in it. The list stays
        homogeneous — every element has an `agent`, a `tool` and a `query` —
        and the count stays a measurement even when the cap bound.
        """
        issued = self._counter.get('issued', 0)
        dropped = self._counter.get('dropped', 0)
        return {
            'issued': issued,
            'recorded': len(self._entries),
            'dropped': dropped,
            'truncated': dropped > 0,
            'cap': MAX_RECORDED_QUERIES,
        }
