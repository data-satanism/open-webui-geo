"""Authenticated download proxy for rendered GeoTeaser workbooks."""

from __future__ import annotations

import json
import logging

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from open_webui.env import (
    AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA,
)
from open_webui.models.config import Config
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.tools import (
    build_tool_server_headers,
    get_tool_servers,
)

log = logging.getLogger(__name__)
router = APIRouter()

ARTIFACTS = {
    'geotizer.xlsx': (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'GeoTeaser',
    ),
    'geotizer.docx': (
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'GeoTeaser_card',
    ),
    'source_report.md': ('text/markdown; charset=utf-8', 'GeoTeaser_sources'),
    'source_report.pdf': ('application/pdf', 'GeoTeaser_sources'),
    'state.json': ('application/json', 'GeoTeaser_state'),
    # Diagnostic output, not a deliverable. `gis_execution_trace`,
    # `gis_layer_manifest`, `run_notes` and `retrieval_queries` live in this
    # file and nowhere else -- they were moved there on the finding that what
    # describes a *cell* arrives on a patch and what describes a *run* does
    # not. The carrier was chosen and built, and then given no way out: no
    # entry here, no route, no link, reachable only with filesystem access.
    'run_log.json': ('application/json', 'GeoTeaser_run_log'),
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


@router.get('/files/{run_id}/geotizer.docx')
async def download_geotizer_card_docx(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """The Word rendering of the same card the XLSX holds.

    A second format of one run, not a second document: both come from the same
    `state.json`. It is not the CPR Readiness Report -- that is `CPR-SLICE-01`,
    a different artefact behind gate B1 -- and the file itself says so on its
    first line.
    """
    return await _download_artifact(
        run_id,
        'geotizer.docx',
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


@router.get('/files/{run_id}/run_log.json')
async def download_geotizer_run_log(
    run_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """The orchestrator's record of the run, as opposed to of any cell.

    Four things live here and in no other artefact: the GIS execution trace
    every Stage 3-8 acceptance criterion reads, the layer manifest Stage 3's
    scope was derived from, the run notes behind «Ограничения этого запуска»,
    and the retrieval queries the variance question turns on.
    """
    return await _download_artifact(
        run_id,
        'run_log.json',
        request,
        user,
    )


class SupersedeRunForm(BaseModel):
    reason: str = Field(..., min_length=1)


@router.post('/runs/{run_id}/supersede')
async def supersede_geotizer_run(
    run_id: str,
    form_data: SupersedeRunForm,
    request: Request,
    user=Depends(get_admin_user),
):
    """Retire a finished run so it stops feeding later ones. Admin only.

    `get_admin_user`, not `get_verified_user`, and not an action on the
    model-callable tool surface. Retiring a run changes what every later run over
    the same object carries -- GIS records the exclusion in the provenance of the
    runs that did not receive it -- so this is an operator act. A model asked to
    "fill this object again" answers that with `run_mode="clean"`, which needs no
    privilege at all.

    Nothing is deleted. The XLSX, the source report and `state.json` stay
    downloadable at their existing paths; what changes is that the run stops
    being a carry-forward donor and stops being offered as a seed.

    The actor is the authenticated admin, taken from the session rather than
    from the request body: a caller-supplied actor is a caller-supplied claim,
    and this is the field an audit reads.
    """
    payload = await _call_gis(
        request,
        user,
        path=f'/geotizer_runs/{run_id}/supersede',
        body={
            'reason': form_data.reason,
            'actor': str(getattr(user, 'email', None) or getattr(user, 'id', '') or 'unknown'),
        },
        metadata={'run_id': run_id, 'action': 'supersede'},
    )
    log.info(
        'GeoTeaser run %s superseded by %s: %s',
        run_id,
        getattr(user, 'email', None) or getattr(user, 'id', ''),
        form_data.reason,
    )
    return payload


async def _gis_connection(request: Request):
    """The `mcpgis` tool server and its stored connection, or a 503 naming which."""
    servers = await get_tool_servers(request)
    server = next(
        (item for item in servers if str(item.get('id')) == 'mcpgis'),
        None,
    )
    if server is None:
        raise HTTPException(503, 'GIS tool server is not configured')

    server_idx = int(server.get('idx', 0))
    connections = await Config.get('tool_server.connections', []) or []
    connection = next(
        (
            item
            for item in connections
            if str((item.get('info') or {}).get('id') or '') == 'mcpgis'
        ),
        None,
    )
    if connection is None and server_idx < len(connections):
        connection = connections[server_idx]
    if connection is None:
        raise HTTPException(503, 'GIS tool server configuration is stale')
    return server, connection


async def _call_gis(
    request: Request,
    user,
    *,
    path: str,
    body: dict,
    metadata: dict,
):
    server, connection = await _gis_connection(request)
    headers, cookies = await build_tool_server_headers(
        connection,
        request,
        user,
        server_id='mcpgis',
        metadata=metadata,
    )
    url = f"{str(server.get('url') or '').rstrip('/')}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA)
        ) as session:
            async with session.post(
                url,
                json=body,
                headers=headers,
                cookies=cookies,
                ssl=AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
            ) as upstream:
                raw = await upstream.read()
                if upstream.status >= 400:
                    raise HTTPException(
                        upstream.status,
                        raw.decode('utf-8', errors='replace')[:500],
                    )
                return json.loads(raw.decode('utf-8'))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f'GIS service call failed: {exc}') from exc


async def _download_artifact(
    run_id: str,
    artifact: str,
    request: Request,
    user,
) -> Response:
    server, connection = await _gis_connection(request)
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
