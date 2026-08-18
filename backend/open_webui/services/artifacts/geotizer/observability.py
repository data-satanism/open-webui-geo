"""Observability for the owner attempt."""

from __future__ import annotations

import hashlib
from typing import Any
from .owner_envelope import (
    EMPTY_RESPONSE,
    PARSED_RESPONSE,
    UNPARSEABLE_RESPONSE,
    _owner_payload_candidates,
)

#: How much of an unparseable response is kept. See `owner_attempt_diagnostic`
#: for why only the unparseable case keeps any of it.
UNPARSEABLE_PREFIX_CHARS = 500


def owner_attempt_diagnostic(
    text: str,
    *,
    attempt: int,
) -> dict[str, Any]:
    """Classify one owner attempt and return bounded diagnostics.

    `response_mode` separates the two ways an attempt reaches the contract with
    nothing. They are not the same failure and they do not have the same fix:

      - `empty` — the specialist returned no characters. Nothing was written,
        so there is nothing to repair and no feedback that can change the next
        attempt. On run `6056e157` this took 24 of the 35 lost cells, and on
        `KB-GRR-FACTORS` all three attempts returned zero characters.
      - `unparseable` — the specialist wrote at length and none of it was an
        owner envelope. `KB-GEO` wrote 8,929 then 4,706 then 4,445 characters
        across three attempts with no candidate in any of them.

    Both used to be recorded as the same thing, and the card called both "did
    not satisfy the deterministic field contract", which is true of neither.

    **`text_prefix` is kept only for `unparseable`, and that is a deliberate
    narrowing of the previous no-raw-text rule.** A parsed response's content
    is already in the card, cell by cell, so recording it again buys nothing.
    An unparseable one is the only case where the text exists nowhere else and
    the run cannot be diagnosed without it -- with `candidate_count=0` and no
    prefix, `KB-GEO`'s three attempts are indistinguishable from each other and
    from any other prose. The prefix is bounded to
    `UNPARSEABLE_PREFIX_CHARS` characters and lands in `state.json`, which is
    downloadable, so it is owner output and should be read as such.
    """
    rendered = text if isinstance(text, str) else str(text)
    candidates = _owner_payload_candidates(rendered)
    if not rendered.strip():
        response_mode = EMPTY_RESPONSE
    elif not candidates:
        response_mode = UNPARSEABLE_RESPONSE
    else:
        response_mode = PARSED_RESPONSE
    diagnostic = {
        'attempt': attempt,
        'sha256': hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
        'character_count': len(rendered),
        'candidate_count': len(candidates),
        'candidate_keys': [sorted(str(key) for key in candidate.keys())[:12] for candidate in candidates[:4]],
        'response_mode': response_mode,
    }
    if response_mode == UNPARSEABLE_RESPONSE:
        diagnostic['text_prefix'] = rendered[:UNPARSEABLE_PREFIX_CHARS]
    return diagnostic
