"""Pure validation and routing helpers for GeoTeaser artifact downloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

GIS_SERVER_ID = 'mcpgis'


class GeotizerDownloadConfigError(ValueError):
    """Raised when the GIS artifact proxy cannot resolve a safe upstream."""


@dataclass(frozen=True)
class GeotizerDownloadTarget:
    url: str
    connection: Mapping[str, object] | None


def resolve_geotizer_download_target(
    *,
    servers: Sequence[Mapping[str, object]],
    connections: Sequence[Mapping[str, object]] | None,
    run_id: str,
    artifact: str,
    allowed_artifacts: frozenset[str],
) -> GeotizerDownloadTarget:
    """Resolve a safe GIS artifact URL without trusting a stale cache index."""
    if artifact not in allowed_artifacts:
        raise GeotizerDownloadConfigError('Unsupported GeoTeaser artifact')

    try:
        normalized_run_id = str(UUID(run_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GeotizerDownloadConfigError('Invalid GeoTeaser run identifier') from exc

    server = next(
        (item for item in servers if _normalized_server_id(item.get('id')) == GIS_SERVER_ID),
        None,
    )
    if server is None:
        raise GeotizerDownloadConfigError('GIS tool server is not configured')

    connection = _resolve_connection(server, connections or ())
    base_url = str((connection or {}).get('url') or server.get('url') or '').strip()
    parsed = urlsplit(base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise GeotizerDownloadConfigError('GIS tool server has an invalid base URL')

    base_path = parsed.path.rstrip('/')
    upstream_path = f'{base_path}/geotizer/files/' f'{quote(normalized_run_id, safe="")}/{quote(artifact, safe="")}'
    return GeotizerDownloadTarget(
        url=urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                upstream_path,
                '',
                '',
            )
        ),
        connection=connection,
    )


def _resolve_connection(
    server: Mapping[str, object],
    connections: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    """Prefer the cached index, then recover deterministically by server id."""
    server_id = _normalized_server_id(server.get('id'))
    raw_idx = server.get('idx')
    if raw_idx is not None:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(connections):
            candidate = connections[idx]
            if isinstance(candidate, Mapping):
                candidate_id = _connection_server_id(candidate)
                if not candidate_id or candidate_id == server_id:
                    return candidate

    for connection in connections:
        if not isinstance(connection, Mapping):
            continue
        if _connection_server_id(connection) == server_id:
            return connection
    return None


def _connection_server_id(connection: Mapping[str, object]) -> str:
    info = connection.get('info')
    info_id = info.get('id') if isinstance(info, Mapping) else None
    return _normalized_server_id(connection.get('id') or info_id)


def _normalized_server_id(value: object) -> str:
    server_id = str(value or '').strip().lower()
    for prefix in ('server:', 'mcp:'):
        if server_id.startswith(prefix):
            server_id = server_id.removeprefix(prefix)
    return server_id
