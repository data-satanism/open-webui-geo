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
- grants read access only to `gisagentyulong`, `skilledagentyulong` and
  `webagentyulong`;
- grants read access to the `mcpgis` tool-server connection;
- creates an API key restricted to the exact routes required by the
  delegator;
- stores the key in the encrypted valves of `mainagent_tool_yulong`;
- prints only a SHA-256 fingerprint, never the key.

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
