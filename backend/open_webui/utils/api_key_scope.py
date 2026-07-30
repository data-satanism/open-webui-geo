"""Per-key API endpoint restrictions.

Global API-key restrictions remain the deployment-wide safety net. A key may
add a narrower allow-list in ``api_key.data.allowed_endpoints``. Per-key
patterns are exact by default and support ``{name}`` for one path segment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

ALLOWED_ENDPOINTS_KEY = 'allowed_endpoints'
_PATH_PARAMETER = re.compile(r'^\{[A-Za-z_][A-Za-z0-9_]*\}$')


def normalize_api_path(path: str) -> str:
    normalized = str(path or '').strip()
    if normalized != '/':
        normalized = normalized.rstrip('/')
    return normalized


@lru_cache(maxsize=256)
def _compile_endpoint_pattern(pattern: str) -> re.Pattern[str] | None:
    normalized = normalize_api_path(pattern)
    if not normalized.startswith('/api/'):
        return None

    segments = normalized.split('/')
    compiled_segments: list[str] = []
    for segment in segments:
        if _PATH_PARAMETER.fullmatch(segment):
            compiled_segments.append(r'[^/]+')
        else:
            compiled_segments.append(re.escape(segment))
    return re.compile('^' + '/'.join(compiled_segments) + '$')


def endpoint_matches_pattern(request_path: str, pattern: str) -> bool:
    compiled = _compile_endpoint_pattern(str(pattern or ''))
    if compiled is None:
        return False
    return compiled.fullmatch(normalize_api_path(request_path)) is not None


def scoped_allowed_endpoints(api_key_data: Any) -> tuple[str, ...] | None:
    if not isinstance(api_key_data, Mapping):
        return None
    raw = api_key_data.get(ALLOWED_ENDPOINTS_KEY)
    if raw is None:
        return None
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        return ()
    return tuple(endpoint.strip() for endpoint in raw if isinstance(endpoint, str) and endpoint.strip())


def is_api_key_path_allowed(request_path: str, api_key_data: Any) -> bool:
    allowed_endpoints = scoped_allowed_endpoints(api_key_data)
    if allowed_endpoints is None:
        return True
    return any(endpoint_matches_pattern(request_path, pattern) for pattern in allowed_endpoints)
