"""Artefact-neutral text and JSON helpers.

CORE-BOUNDARY-01. These sat next to the owner envelope because that is where
they were first needed, but `project_evidence` calls them too, so leaving them
there would have made the evidence core import the GeoTeaser artefact module.
Recorded in the classification as a call-graph correction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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


def locator_map(value: Any) -> dict[str, str]:
    """`source_locator` as a mapping, whichever of its two shapes it arrived in.

    It is polymorphic and nothing said so. Across two consecutive runs the
    split is identical -- 347 mappings and 4 strings -- and the four are GIS
    layer reads, minted by `gis_service`'s scope resolution as a
    human-readable source locator and copied onto the field it binds:

        project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0;
        geometry=full; coordinates=EPSG:4326; area=EPSG:6933

    They land on rows 2, 3, 8 and 12, which belong to `KB-LIC-LEGAL` -- the
    second batch -- so any `.get()` reached on that path kills the whole fill at
    batch 2. `evidence_locator_identity` did exactly that.

    **Parsing rather than guarding is the point.** An `isinstance` check
    returning `{}` stops the crash and silently drops `layer_id`, `project_id`
    and `feature_index` from every reader downstream -- the carried count, the
    qualifier injection and the semantic rules would all quietly see a locator
    with nothing in it. A crash that is fixed by losing data is not fixed. Two
    call sites in this repository already had that guard and were dropping the
    string before this existed.

    Anything that is neither shape returns `{}`, because there is nothing to
    parse and no key worth inventing.
    """
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        return {
            part.split('=', 1)[0].strip(): part.split('=', 1)[1].strip()
            for part in value.split(';')
            if '=' in part
        }
    return {}
