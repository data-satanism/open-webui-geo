"""Artefact-neutral text and JSON helpers.

CORE-BOUNDARY-01. These sat next to the owner envelope because that is where
they were first needed, but `project_evidence` calls them too, so leaving them
there would have made the evidence core import the GeoTeaser artefact module.
Recorded in the classification as a call-graph correction.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from ..geotizer.errors import GeotizerOrchestrationError


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract exactly one JSON object from a model response."""
    if not isinstance(text, str) or not text.strip():
        raise GeotizerOrchestrationError('Agent returned an empty response')

    stripped = _strip_json_fence(text)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _decode_embedded_object(stripped)
    if not isinstance(parsed, dict):
        raise GeotizerOrchestrationError('Agent response must be a JSON object')
    return parsed


def _is_nonstring_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        str | bytes,
    )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith('```'):
        first_newline = stripped.find('\n')
        last_fence = stripped.rfind('```')
        if first_newline >= 0 and last_fence > first_newline:
            return stripped[first_newline + 1 : last_fence].strip()
    return stripped


def _decode_embedded_object(text: str) -> dict[str, Any]:
    objects = _decode_embedded_objects(text)
    if len(objects) != 1:
        raise GeotizerOrchestrationError('Agent response must contain exactly one unambiguous JSON object')
    return objects[0]


def _decode_embedded_objects(text: str) -> tuple[dict[str, Any], ...]:
    decoder = json.JSONDecoder()
    objects: list[tuple[int, int, dict[str, Any]]] = []
    for index, char in enumerate(text):
        if char != '{':
            continue
        try:
            value, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append((index, index + consumed, value))
    top_level = [
        candidate
        for candidate in objects
        if not any(other_start < candidate[0] and candidate[1] <= other_end for other_start, other_end, _ in objects)
    ]
    unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for _, _, item in top_level}
    return tuple(unique.values())


def bounded_text(value: str, *, max_chars: int) -> str:
    """Keep the beginning and provenance-rich tail of oversized evidence."""
    if len(value) <= max_chars:
        return value
    tail_chars = min(4_000, max_chars // 4)
    head_chars = max_chars - tail_chars
    removed = len(value) - max_chars
    return (
        f'{value[:head_chars]}\n\n'
        f'[... {removed} evidence characters omitted by orchestrator ...]\n\n'
        f'{value[-tail_chars:]}'
    )
