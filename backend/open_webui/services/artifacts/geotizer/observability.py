"""Observability for the owner attempt."""

from __future__ import annotations

import hashlib
from typing import Any
from .owner_envelope import (
    _owner_payload_candidates,
)


def owner_attempt_diagnostic(
    text: str,
    *,
    attempt: int,
) -> dict[str, Any]:
    """Return bounded diagnostics without persisting raw owner text."""
    rendered = text if isinstance(text, str) else str(text)
    candidates = _owner_payload_candidates(rendered)
    return {
        'attempt': attempt,
        'sha256': hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
        'character_count': len(rendered),
        'candidate_count': len(candidates),
        'candidate_keys': [sorted(str(key) for key in candidate.keys())[:12] for candidate in candidates[:4]],
    }
