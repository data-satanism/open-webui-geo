"""The GIS data portal ticket: who the Geomas user at a portal window is.

The portal accepts a ticket only if it is signed with the shared secret, meant
for the portal, alive and new, and finds its account by the ticket's e-mail
(backend/auth/geomas.py in Data_portal). These tests pin the Geomas half of that
contract and the route that hands a ticket out -- to a human session only, and
never from a cache.
"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.routers import gis_portal
from open_webui.utils.auth import get_human_user
from open_webui.utils.gis_portal_ticket import AUDIENCE, ISSUER, TICKET_TTL_S, mint_ticket, shared_secret

SECRET = 'shared-with-the-portal'


def decode(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=['HS256'], audience=AUDIENCE, issuer=ISSUER)


def test_a_ticket_names_the_user_and_lives_five_minutes():
    token, expires_in = mint_ticket('user-1', 'Карл', ' karl@geomas.test ', secret=SECRET, now=1_000_000)
    claims = jwt.decode(
        token,
        SECRET,
        algorithms=['HS256'],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={'verify_exp': False, 'verify_iat': False},
    )
    assert claims['sub'] == 'user-1'
    assert claims['name'] == 'Карл'
    assert claims['email'] == 'karl@geomas.test'
    assert claims['exp'] - claims['iat'] == TICKET_TTL_S == expires_in


def test_every_ticket_has_its_own_number():
    first, _ = mint_ticket('user-1', '', 'a@b.c', secret=SECRET)
    second, _ = mint_ticket('user-1', '', 'a@b.c', secret=SECRET)
    assert decode(first)['jti'] != decode(second)['jti']


def test_a_ticket_is_not_valid_under_another_secret():
    token, _ = mint_ticket('user-1', '', 'a@b.c', secret=SECRET)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, 'webui-secret-key', algorithms=['HS256'], audience=AUDIENCE, issuer=ISSUER)


def test_without_a_secret_the_integration_is_off(monkeypatch):
    monkeypatch.delenv('GIS_PORTAL_SHARED_SECRET', raising=False)
    assert shared_secret() is None
    monkeypatch.setenv('GIS_PORTAL_SHARED_SECRET', '   ')
    assert shared_secret() is None


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(gis_portal.router, prefix='/api/v1/gis-portal')
    user = SimpleNamespace(id='user-1', name='Карл', email='karl@geomas.test')
    app.dependency_overrides[get_human_user] = lambda: user
    return TestClient(app)


def test_the_route_hands_out_a_fresh_ticket(client, monkeypatch):
    monkeypatch.setenv('GIS_PORTAL_SHARED_SECRET', SECRET)
    answer = client.get('/api/v1/gis-portal/ticket')
    assert answer.status_code == 200
    assert answer.headers['cache-control'] == 'no-store'
    body = answer.json()
    assert body['expires_in'] == TICKET_TTL_S
    claims = decode(body['ticket'])
    assert (claims['sub'], claims['email']) == ('user-1', 'karl@geomas.test')


def test_the_route_says_when_the_secret_is_missing(client, monkeypatch):
    monkeypatch.delenv('GIS_PORTAL_SHARED_SECRET', raising=False)
    assert client.get('/api/v1/gis-portal/ticket').status_code == 503


def test_the_route_needs_a_human_session():
    app = FastAPI()
    app.include_router(gis_portal.router, prefix='/api/v1/gis-portal')
    dependant = app.router.routes[-1].dependant
    assert get_human_user in [dep.call for dep in dependant.dependencies]


def test_the_wrapper_serves_the_ticket_before_the_spa():
    from open_webui.asgi import app

    names = [getattr(route, 'path', None) for route in app.router.routes]
    route_names = [getattr(route, 'name', None) for route in app.router.routes]
    assert '/api/v1/gis-portal/ticket' in names
    if 'spa-static-files' in route_names:
        assert names.index('/api/v1/gis-portal/ticket') < route_names.index('spa-static-files')
