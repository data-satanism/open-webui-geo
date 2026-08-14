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
- `/api/v1/chats/new`;
- `/api/v1/chats/{chat_id}`;
- `/api/v1/chats/{chat_id}/delete`;
- `/api/v1/knowledge`.

Every other API route is denied for this key.
