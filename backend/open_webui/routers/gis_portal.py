"""GIS data portal panel: a ticket for the portal window beside the chat.

Mounted at /api/v1/gis-portal by open_webui/asgi.py. See docs/gis-portal.md.

Only a human session gets a ticket (get_human_user): API keys, automations
and subagents have no portal window to identify, and a ticket signs its holder
into the portal as the user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from open_webui.utils.auth import get_human_user
from open_webui.utils.gis_portal_ticket import mint_ticket, shared_secret

router = APIRouter()


@router.get('/ticket')
async def issue_ticket(response: Response, user=Depends(get_human_user)):
    secret = shared_secret()
    if not secret:
        raise HTTPException(status_code=503, detail='GIS portal ticket secret is not configured')
    ticket, expires_in = mint_ticket(user.id, user.name, user.email, secret=secret)
    response.headers['Cache-Control'] = 'no-store'
    return {'ticket': ticket, 'expires_in': expires_in}
