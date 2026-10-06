"""Stored chunks of one file: reading, deterministic sampling and evidence locators."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

LOCATOR_STRING_KEYS = ('document_id', 'document_version', 'section_path', 'child_chunk_id')
_DIGITS = re.compile(r'[0-9]+')


@dataclass(frozen=True)
class StoredChunk:
    """One stored chunk: its vector-store id, its text and its metadata."""

    chunk_id: str
    text: str
    metadata: Mapping[str, Any]


def stored_chunks(
    ids: Sequence[Any] | None, documents: Sequence[Any] | None, metadatas: Sequence[Any] | None
) -> list[StoredChunk]:
    """Pair the parallel id, text and metadata lists of a vector-store result.

    An entry without a non-empty string id or a string text is skipped. Metadata that is not a
    mapping is read as empty.
    """
    ids = list(ids or ())
    documents = list(documents or ())
    metadatas = list(metadatas or ())
    chunks = []
    for position, chunk_id in enumerate(ids):
        text = documents[position] if position < len(documents) else None
        metadata = metadatas[position] if position < len(metadatas) else None
        if not isinstance(chunk_id, str) or not chunk_id or not isinstance(text, str):
            continue
        chunks.append(StoredChunk(chunk_id, text, metadata if isinstance(metadata, Mapping) else {}))
    return chunks


def evidence_page(metadata: Mapping[str, Any]) -> int | None:
    """The printed page from `page_label` when it is a positive integer or a string of ASCII digits naming one."""
    label = metadata.get('page_label')
    if isinstance(label, bool):
        return None
    if isinstance(label, int):
        return label if label > 0 else None
    if isinstance(label, str) and _DIGITS.fullmatch(label):
        try:
            value = int(label)
        except ValueError:
            return None
        return value if value > 0 else None
    return None


def _start_index(metadata: Mapping[str, Any]) -> int | None:
    value = metadata.get('start_index')
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def evidence_locator(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """The optional evidence locator keys a chunk's metadata supports; a key that fails its rule is absent."""
    locator: dict[str, Any] = {}
    page = evidence_page(metadata)
    if page is not None:
        locator['page'] = page
    start = _start_index(metadata)
    if start is not None:
        locator['start_index'] = start
    for key in LOCATOR_STRING_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            locator[key] = value
    return locator


def _text_digest(chunk: StoredChunk) -> str:
    return hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()


def _document_order(chunk: StoredChunk) -> tuple[tuple[int, int], tuple[int, int], str]:
    page = evidence_page(chunk.metadata)
    start = _start_index(chunk.metadata)
    return (
        (0, page) if page is not None else (1, 0),
        (0, start) if start is not None else (1, 0),
        chunk.chunk_id,
    )


def sample_chunks(chunks: Sequence[StoredChunk], k: int, min_chars: int) -> list[StoredChunk]:
    """The k chunks of at least `min_chars` characters whose text has the smallest SHA-256.

    Ties on the digest go to the smaller chunk id. The selection is returned ordered by evidence
    page, then `start_index`, then chunk id; a chunk missing a key sorts after those carrying it.
    """
    eligible = [chunk for chunk in chunks if len(chunk.text) >= min_chars]
    chosen = sorted(eligible, key=lambda chunk: (_text_digest(chunk), chunk.chunk_id))[: max(k, 0)]
    return sorted(chosen, key=_document_order)
