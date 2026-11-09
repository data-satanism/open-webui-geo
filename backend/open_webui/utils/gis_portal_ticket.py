"""Ticket that tells the GIS data portal which Geomas user sits at a portal window.

The portal is embedded beside the chat (src/lib/components/gis-portal). Geomas signs
a short-lived JWT for the signed-in user and hands it to the portal iframe over
postMessage. The portal (Data_portal, backend/auth/geomas.py) verifies it with the
same secret, finds its own account whose «Email в Геомасе» is the ticket's `email`,
accepts each `jti` once and signs the window in.

The secret is GIS_PORTAL_SHARED_SECRET, deliberately not WEBUI_SECRET_KEY:
the portal must be able to check a ticket, not to mint a Geomas session.

Pure: no FastAPI, no database. The router is routers/gis_portal.py.
"""

from __future__ import annotations

import os
import time
import uuid

import jwt

TICKET_TTL_S = 300
AUDIENCE = 'gis-portal'
ISSUER = 'geomas'
ALGORITHM = 'HS256'


def shared_secret() -> str | None:
    """The secret shared with the portal, or None when the integration is off."""
    value = os.environ.get('GIS_PORTAL_SHARED_SECRET', '').strip()
    return value or None


def mint_ticket(user_id: str, name: str, email: str, *, secret: str, now: float | None = None) -> tuple[str, int]:
    """Signed ticket for one portal window and its lifetime in seconds."""
    issued = int(time.time() if now is None else now)
    claims = {
        'iss': ISSUER,
        'aud': AUDIENCE,
        'sub': str(user_id),
        'name': name or '',
        'email': (email or '').strip(),
        'iat': issued,
        'exp': issued + TICKET_TTL_S,
        'jti': uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM), TICKET_TTL_S
