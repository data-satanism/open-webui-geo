# GeoTeaser orchestrator service account

GeoTeaser delegates KB, GIS and Web work through an internal Open WebUI API
client. The client must not reuse a personal administrator API key.

Provision the identity inside the Open WebUI runtime:

```bash
open-webui provision-geotizer-service-account
```

The command is idempotent. It:

- creates a non-interactive `user` without a password/auth record;
- creates a dedicated group with `features.api_keys`, Web search and chat-call
  permissions;
- copies read-only knowledge grants from the `Test Team` group;
- grants read access only to `gisagent`, `kb-agent` and `web-agent`, plus their
  required registered base model `TESTAGENT.Qwen/Qwen3.5-35B-A3B-GPTQ-Int4`
  (`DEFAULT_AGENT_MODEL_IDS` / `DEFAULT_BASE_MODEL_IDS` in
  `utils/geotizer_service_account.py`). The three `…yulong` ids this document
  used to name are the retired ones GEOMAS-DEF-001 records; nothing grants them
  anything now;
- grants read access to the `mcpgis` tool-server connection;
- creates an API key restricted to the exact routes required by the
  delegator;
- prints only a SHA-256 fingerprint, never the key.

The key is **not** written into any Workspace Tool's valves. This document used
to say it was stored in the encrypted valves of `mainagent_tool_yulong`, and
that write existed; `CORE-BOUNDARY-01` action 5 deleted it (register entry
A-49). A live key in a tool's valves is readable by anyone who can open the
tool, whereas the key on the service account stays behind that account's ACL.
`test_no_credential_is_written_into_a_workspace_tool_s_valves` holds it.

Rotate the key explicitly:

```bash
open-webui provision-geotizer-service-account --rotate-key
```

The per-key endpoint scope is stored in `api_key.data.allowed_endpoints`.
Deployment-wide `auth.api_key.endpoint_restrictions` remains supported and is
applied in addition to the per-key scope.

The service key can call:

- `/api/chat/completions`;
- `/api/v1/knowledge`.

Every other API route is denied for this key.

Every chat route was on this list until CORE-BOUNDARY-01. They were scoped in so
the HTTP sub-chat delegator could open one chat per specialist, poll it and
delete it; Multitask Orchestration v3 replaced that transport with an in-process
agent loop and states in its own header that it uses no `httpx`, no
`/api/v1/chats/new`, no polling and no citation walk over fetched chat objects —
which is all three routes.

They came out in two passes, and the first one was wrong in a way worth keeping
on the record. It deleted only the `/api/v1/chats/new` literal and left the two
`{chat_id}` entries, and this page then said the key could no longer open a
chat. It could: `{name}` in a per-key pattern compiles to `[^/]+`, so
`/api/v1/chats/{chat_id}` is `^/api/v1/chats/[^/]+$` and matches
`/api/v1/chats/new` exactly. Deleting the literal revoked nothing. A wrong
security claim is worse than the privilege it describes, because it is the one
nobody re-checks.

This list is checked against the code by
`test_the_documented_scope_is_the_scope_that_is_provisioned`, so it cannot drift
from `DEFAULT_ALLOWED_ENDPOINTS` again — the second pass fixed the constant, the
comment and the test, and left this page stale for exactly as long as it took a
review to notice.
