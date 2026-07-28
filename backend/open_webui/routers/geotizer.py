"""Authenticated download proxy for rendered GeoTeaser workbooks."""

from __future__ import annotations

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from open_webui.env import (
    AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA,
)
from open_webui.models.config import Config
from open_webui.utils.auth import get_verified_user
from open_webui.utils.tools import (
    build_tool_server_headers,
    get_tool_servers,
)

router = APIRouter()

ARTIFACTS = {
    'geotizer.xlsx': (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'GeoTeaser',
    ),
    'source_report.md': ('text/markdown; charset=utf-8', 'GeoTeaser_sources'),
    'source_report.pdf': ('application/pdf', 'GeoTeaser_sources'),
    'state.json': ('application/json', 'GeoTeaser_state'),
}


@router.get('/files/{run_id}/geotizer.xlsx')
async def download_geotizer(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """Proxy the private GIS artifact through the authenticated WebUI origin."""
    return await _download_artifact(
        run_id,
        'geotizer.xlsx',
        request,
        user,
    )


@router.get('/files/{run_id}/source_report.md')
async def download_geotizer_source_report_markdown(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    return await _download_artifact(
        run_id,
        'source_report.md',
        request,
        user,
    )


@router.get('/files/{run_id}/source_report.pdf')
async def download_geotizer_source_report_pdf(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    return await _download_artifact(
        run_id,
        'source_report.pdf',
        request,
        user,
    )


@router.get('/files/{run_id}/state.json')
async def download_geotizer_state(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    return await _download_artifact(
        run_id,
        'state.json',
        request,
        user,
    )


async def _download_artifact(
    run_id: str,
    artifact: str,
    request: Request,
    user,
) -> Response:
    servers = await get_tool_servers(request)
    server = next(
        (item for item in servers if str(item.get('id')) == 'mcpgis'),
        None,
    )
    if server is None:
        raise HTTPException(503, 'GIS tool server is not configured')

    server_idx = int(server.get('idx', 0))
    connections = await Config.get('tool_server.connections', []) or []
    if server_idx >= len(connections):
        raise HTTPException(503, 'GIS tool server configuration is stale')
    connection = connections[server_idx]
    headers, cookies = await build_tool_server_headers(
        connection,
        request,
        user,
        server_id='mcpgis',
        metadata={'run_id': run_id, 'artifact': artifact},
    )
    url = (
        f"{str(server.get('url') or '').rstrip('/')}"
        f"/geotizer/files/{run_id}/{artifact}"
    )
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA)
        ) as session:
            async with session.get(
                url,
                headers=headers,
                cookies=cookies,
                ssl=AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
            ) as upstream:
                body = await upstream.read()
                if upstream.status >= 400:
                    detail = body.decode('utf-8', errors='replace')[:500]
                    raise HTTPException(upstream.status, detail)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            f'Failed to download GeoTeaser from GIS service: {exc}',
        ) from exc

    media_type, basename = ARTIFACTS[artifact]
    extension = artifact.rsplit('.', 1)[-1]
    return Response(
        content=body,
        media_type=media_type,
        headers={
            'Content-Disposition': (
                f'attachment; filename="{basename}_{run_id}.{extension}"'
            ),
            'Cache-Control': 'private, no-store',
        },
    )
