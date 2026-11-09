# GIS data portal panel

The chat pages show the GIS data portal (`Data_portal`, its React frontend at `GIS_PORTAL_URL`) in a panel to the left of the chat. Two links tie Geomas and the portal:

- **The panel window signs in as the Geomas user.** Geomas gives the portal iframe a ticket, and the portal exchanges it for its own session. No second password.
- **The assistant works in the portal with tools.** The portal's assistant API (`/api/agent`) is connected as an OpenAPI tool server. Every call runs as the user who talks to the assistant, with that user's portal rights.

A Geomas user and a portal account are the same person when the portal account's «Email в Геомасе» equals the Geomas e-mail (case does not matter). The portal admin sets it on the portal's `/admin` page. The portal never creates accounts by itself.

Everything else is on the portal side: section «Геомас» of the `Data_portal` README.

## How it fits together

```
panel --postMessage: ticket, theme, home--> portal window --POST /api/user/geomas/token--> portal backend
model --tool call--> Open WebUI --/api/agent/dp_* (Bearer key, X-User-Email)--> portal backend
```

1. When the portal iframe loads, it asks the panel for a ticket. The panel gets one from `GET /api/v1/gis-portal/ticket` and posts it to the iframe.
2. The portal backend checks the ticket (signature, `iss`, `aud`, expiry), accepts each `jti` once, finds the account by the ticket's `email` and signs the window in.
3. The portal reports `gis-portal:status`. The dot in the panel header turns green and its tooltip names the portal account.
4. A tool call carries the Geomas e-mail in `X-User-Email`. The portal finds the same account and runs the tool as that user.

The assistant has no tools that delete, clean, take in layers, cancel tasks or recompute from scratch. Those need a confirmation in the user's window, which the portal does not have yet.

## Configuration

| Where | Name | Value |
| --- | --- | --- |
| Geomas backend environment | `GIS_PORTAL_SHARED_SECRET` | Secret shared with the portal. It signs tickets. Without it the ticket route answers 503: the panel still shows the portal, but the user signs in with a password. Not `WEBUI_SECRET_KEY`: the portal must be able to check a ticket, not to mint a Geomas session. |
| `src/lib/constants.ts` | `GIS_PORTAL_URL` | `http://87.228.65.110:12000/`. Empty removes the panel and its navbar toggle. Change it and rebuild the frontend when the portal moves. |
| Portal `.env` | `GEOMAS_SHARED_SECRET` | Same value as `GIS_PORTAL_SHARED_SECRET` here. |
| Portal `.env` | `GEOMAS_ORIGINS`, `FRAME_ANCESTORS` | The Geomas origin, e.g. `http://87.228.65.110:8503`. `FRAME_ANCESTORS` lets Geomas frame the portal (CSP `frame-ancestors`). `GEOMAS_ORIGINS` is the list the portal talks to over postMessage. |
| Portal `.env` | `GEOMAS_AGENT_KEY` | Key Open WebUI uses for the portal's assistant API. |
| Portal `/admin` | «Email в Геомасе» | The Geomas e-mail of each person who uses the portal from Geomas. |

Leave `REFERRER_POLICY` unset, or set it to a policy that still sends the origin cross-origin. Never `no-referrer` or `same-origin`: Firefox has no `location.ancestorOrigins`, and the portal recognises Geomas by the referrer.

The backend must run as `open_webui.asgi:app`, which mounts the ticket route. `open_webui.main:app` (as `start.sh` and `open-webui serve` start it) has no ticket route.

Sign-in sets the portal's cookie too, so maps and downloads inside the panel work while Geomas and the portal share a host. If they end up on different domains, the browser may drop the iframe's cookie. API calls keep working with the in-memory token, but maps and downloads stop.

## Connecting the assistant (Admin -> Settings -> External Tools)

Add an OpenAPI connection:

| Field | Value |
| --- | --- |
| URL | `http://87.228.65.110:12000/api/agent` |
| OpenAPI spec path | `openapi.json` |
| Auth | Bearer, the portal's `GEOMAS_AGENT_KEY` |
| Headers | `{"X-User-Email": "{{USER_EMAIL}}"}` |
| ID / name | `dataportal` / «Портал данных» |
| Access | the groups that use the portal |

Verify should list only `dp_*` tools. Then enable the tool on the models that need it and use native function calling. Re-save the connection after the portal's assistant API changes, because Open WebUI caches the spec.

The bearer key plus a header was chosen over `session` auth because `session` forwards the user's own long-lived Geomas token to the portal. It was also chosen over `ENABLE_FORWARD_USER_INFO_HEADERS`, which is global and would send user details to every external connection, model providers included. The trade-off: whoever holds the portal key can claim any user's e-mail, so keep it admin-only.

## Frontend

| File | Role |
| --- | --- |
| `src/lib/components/gis-portal/GisPortalPanel.svelte` | The panel, rendered in `src/routes/(app)/+layout.svelte`. It is created on first show and never destroyed, only hidden, so the portal keeps its state and WebSocket across hiding the panel and visits to other pages. Its width is a share of the room beside the sidebar: 70% until the user drags it, never leaving the chat under 360px, stored in `localStorage.gisPortalRatio`. It expands the chat sidebar on load and whenever the portal is switched on. Not rendered on mobile. |
| `src/lib/components/gis-portal/bridge.ts` | The postMessage bridge. It accepts messages only from the portal iframe at the portal origin and posts only to that origin. Has its own tests in `bridge.test.ts`. |
| `src/lib/components/gis-portal/stores.ts` | `showGisPortal` (stored in `localStorage.showGisPortal`, open by default); `gisPortalVisible` (shown and not mobile); `gisPortalLink` (whether the portal accepted the ticket, shown as a dot in the panel header). |
| `src/lib/components/chat/Navbar.svelte` | Toggle button left of Tabs. |
| `src/lib/components/chat/Messages/Message.svelte`, `MessageInput.svelte`, `Placeholder.svelte` | While `gisPortalVisible`, horizontal padding drops to `px-1`. |

### postMessage protocol

All messages are `{v: 1, type, ...}`:

| Direction | Messages |
| --- | --- |
| portal -> Geomas | `gis-portal:hello`, `gis-portal:ticket-request {nonce}`, `gis-portal:status {linked, userName}`; `gis-portal:show` is understood but the portal does not send it yet |
| Geomas -> portal | `gis-portal:ticket {nonce, ticket}`, `gis-portal:navigate {hash}` (the panel's home button), `gis-portal:theme {mode}`; `gis-portal:context {chatId}` and `gis-portal:visibility {visible}` are sent, the portal ignores them for now |

## Backend

| File | Role |
| --- | --- |
| `backend/open_webui/routers/gis_portal.py` | `GET /api/v1/gis-portal/ticket`. Requires a human session (`get_human_user`), answers `Cache-Control: no-store`, and 503 without the secret. |
| `backend/open_webui/utils/gis_portal_ticket.py` | `mint_ticket()`: HS256 JWT `{iss: geomas, aud: gis-portal, sub, name, email, iat, exp: +300 s, jti}`. |
| `backend/open_webui/asgi.py` | `open_webui.main:app` plus the ticket router, moved in front of the SPA mount. `main.py` is untouched. |

## Tests

- `backend/tests/test_gis_portal_ticket.py`: ticket claims (with the e-mail) and lifetime, the secret, the route (503, no-store, human session only), and the wrapper serving the ticket before the SPA. Run from the repo root: `PYTHONPATH=backend WEBUI_SECRET_KEY=x DATA_DIR=<tmp> STATIC_DIR=<tmp> python -m pytest backend/tests/test_gis_portal_ticket.py`.
- `src/lib/components/gis-portal/bridge.test.ts`: origin and source checks both ways. `npx vitest run src/lib/components/gis-portal`.
