# Open WebUI integration

This document covers the Open WebUI side of GeoTeaser: the Workspace-tool adapter, the run scope it forwards to specialists, the artefact download proxy, the ASGI wrapper that mounts it, and the upstream file the fork still changes.

| File | Role |
| --- | --- |
| `backend/open_webui/tools/geotizer.py` | The adapter: `fill_geotizer`, `fill_geoteaser_area` and `query_geomas_retrieval_plan`. |
| `backend/open_webui/services/artifacts/geotizer/run_scope.py` | The fill's GIS scope, forwarded on every specialist call. |
| `backend/open_webui/routers/geotizer.py` | The authenticated artefact download proxy and the supersede route. |
| `backend/open_webui/asgi.py` | The served application: `open_webui.main.app` with the GeoTeaser router mounted. |
| `backend/open_webui/utils/tools.py` | The one upstream file the fork still changes. |

## `fill_geotizer`

- `fill_geotizer`, and `fill_geoteaser` in the built Workspace artefact, have no required parameters.
- `fill_geotizer` returns an `object_identity_missing` error result when neither `object_name` nor `licence_id` is given.
- The GIS `start` action (`gis_service/arcgis_mcp/geotizer/api.py`, `_geotizer_fill`) also returns `needs_input` with code `object_identity_missing` when neither is given.
- `GEOMAS_OWNER_FIELDS_PER_CALL` and `GEOMAS_FILL_DEADLINE_SECONDS` are environment variables, not valves, interpreted by `resolve_owner_fields_per_call` and `resolve_fill_deadline`.
- `fill_geotizer` passes attached files verbatim through `visual_source_files`, and `attached_source_fingerprints` interprets their shapes.
- `fill_geotizer` passes the KB scope from `_kb_scope` on every run, including when none is configured.
- `fill_geotizer` prints the preamble note above the card.
- `fill_geotizer` logs a failure to emit `chat:message:files` and still returns the built result.
- `fill_geotizer` reports `str(exc)` for a failure and never reads `__cause__`.

## Specialist calls

- `ORCHESTRATOR_TOOL_ID` is the Workspace Tool id of the specialist orchestrator.
- `ORCHESTRATOR_MODE` maps `execution_mode_for_task` values to `run_agent_task` modes.
- `_build_agent_caller` returns a 3-tuple of the agent caller, the parsed status settings and the orchestrator's round-usage drain, and a stub replacing it must return the same arity.
- `_build_agent_caller`'s load-failure message includes the underlying exception's type and text.
- `load_tool_module_by_id` (`open_webui/utils/plugin.py`) returns a fresh `module.Tools()` instance whose valves hold the class defaults, and applies no stored valves.
- Valves an operator sets in Workspace are read only through `Tools.get_tool_valves_by_id`, and `_build_agent_caller` applies them through `orchestrator.Valves`.
- `open_webui/tools/geotizer.py` names no model id; the skilled model is chosen by the Multitask Orchestration tool's `SKILLED_MODEL` valve.
- `open_webui/utils/geotizer_service_account.py` writes the service user's API key through `update_user_api_key_by_id` and writes no key into a Workspace Tool's valves.

## Run scope

- `set_gis_scope` is called by `workflow.py` once the fill has resolved its project.
- `set_gis_scope` stores `project_id` and `run_id` as stripped strings and omits an empty one.
- `set_gis_scope` records `area_member` only when true, and only as the bool `True`.
- `_GIS_SCOPE` defaults to `None` outside any fill.
- `current_gis_scope` returns a copy and never the stored object.
- `scoped_metadata` returns a copy of the caller's metadata with the recorded scope under `SCOPE_METADATA_KEY` (`geomas_gis_scope`), and adds no key when no scope was recorded.
- `scoped_metadata` replaces non-mapping metadata with a new mapping.
- `fill_geotizer` and `fill_geoteaser_area` in `tools/geotizer.py` set `runtime['__metadata__']` to `__metadata__ or {}` before passing it to `scoped_metadata`.
- The adapter passes `scoped_metadata(runtime['__metadata__'])` on every `run_agent_task` call, recomputed per call, so each specialist call carries the run's GIS scope (`project_id`, `run_id`).
- Multitask Orchestration v5.21.5 reads `__metadata__['geomas_gis_scope']`, strips `project_id` from the schema the model sees, and injects the fill's own.
- Multitask Orchestration v5.21.5 reads `AREA_MEMBER` as `bool(scope.get('area_member'))` and suppresses a member's per-specialist status lines.

## `fill_geoteaser_area`

- `fill_geoteaser_area` resolves `geotizer_fill`, `geotizer_area_scope` and `geotizer_area_fold` as separate callables.
- `geotizer_fill` rejects the area actions: its `action` literal in `GeotizerFillRequest` (`gis_service/arcgis_mcp/geotizer/api.py`) declares no area action.
- Every member fill receives `__event_emitter__` and emits its own `run_started` line through it.
- `fill_geoteaser_area` turns any exception into `_error_result` with the exception class name as `code` and `run_id=None`.

## Geological Vision

- `utils/geotizer_vision.py` no longer exists, and nothing re-exports it.
- `VISION_TOOL_IDS` lists the Geological Vision tool ids in the order `find_vision_tool_record` prefers them.
- `find_vision_tool_record`'s only caller is the adapter `tools/geotizer.py`.
- `apply_structured_visual_field_proposals` does not apply a proposal whose value is an empty-finding marker (`core.vocabulary._is_empty_finding`).

## Knowledge search builtins

- `query_knowledge_files` and `grep_knowledge_files` (`open_webui/tools/builtin.py`), with no attached collection and no `knowledge_ids`, search every knowledge base `Knowledges.search_knowledge_bases` returns for the user, whose default order is `updated_at` descending.
- `get_async_tool_function_and_apply_extra_params` (`open_webui/utils/tools.py`) gives a tool only the extra params its signature declares.
- The tool spec `convert_function_to_pydantic_model` and `convert_pydantic_model_to_openai_function_spec` build omits underscore-prefixed parameters such as `__model_knowledge__`.
- `get_attached_knowledge` (`open_webui/utils/tools.py`) sets `source` to `model` or `folder` on each attached knowledge item.
- `get_builtin_tools` reads `request.state.internal`.
- `FORK_SYMBOLS` (`backend/tests/test_upstream_retrieval_symbols.py`) lists the fork-owned symbols `tools/geotizer_retrieval.py` imports, and `PUBLIC_SYMBOLS` and `PRIVATE_SYMBOL` list the upstream ones.

## Artefact download proxy

- `ARTIFACTS` is the allowlist of artefact filenames the router serves.
- Every artefact the proxy serves has an `ARTIFACTS` entry (media type, download filename stem) and a matching `@router.get('/files/{run_id}/<name>')` route.
- `ARTIFACTS` must equal the keys of `ATTACHMENT_CONTENT_TYPES` in `terminal.py`, with the same content types.
- A new artefact name must be listed by the GIS service, by `ARTIFACTS` and by `terminal.ATTACHMENT_CONTENT_TYPES`.
- `_download_artifact` reads `ARTIFACTS[artifact]` for the media type after the upstream download, so every routed name needs an `ARTIFACTS` entry.
- `run_log.json` is the only artefact carrying `gis_execution_trace`, `gis_layer_manifest`, `run_notes` and `retrieval_queries`.
- `summary.md` exists for area runs only.
- The download routes depend on `get_verified_user`.
- `supersede_geotizer_run` depends on `get_admin_user`, records the session user as the actor, and takes a `SupersedeRunForm` that carries only `reason`.
- `_upstream_detail` truncates a string detail to `UPSTREAM_ERROR_CHARS` and returns a non-string JSON detail intact.

## ASGI wrapper

- `open_webui/main.py` does not mount the GeoTeaser router.
- `backend/start.sh` and `open-webui serve` (`open_webui/__init__.py`) launch `open_webui.main:app`, which therefore serves no artefact route.
- `open_webui/asgi.py` includes the GeoTeaser router and `_no_such_geotizer_path`, which answers 404 for any unmatched `GET` or `HEAD` path under `/api/v1/geotizer` and is registered after the artefact routes.
- `SPA_MOUNT_NAME` (`spa-static-files`) is the name `main.py` gives the SPA catch-all mounted at `/`.
- `asgi.py` moves the routes `include_router` appended ahead of the SPA mount, because Starlette matches in registration order and the SPA mount answers any unmatched non-`.js` path with `index.html` and status 200.
- `asgi.py` measures the number of routes `include_router` added rather than assuming one.
- `main.py` mounts `SPAStaticFiles` at `/` only when `FRONTEND_BUILD_DIR` exists, and with no SPA mount (an API-only deployment) `asgi.py` leaves the route order unchanged.
- `open_webui.env` reads `FRONTEND_BUILD_DIR` at import time, so `backend/tests/test_the_wrapper_serves_the_artifacts.py` imports `open_webui.asgi` in a fresh subprocess (`_with_frontend_build`) with a frontend build to test the ordering.
- `asgi.py` resets `app.openapi_schema` to None after mounting.
- `app.state.geotizer_wrapper` is set to True only in `asgi.py`, and `test_the_marker_is_set_nowhere_else` checks that.

## Building and installing the Workspace tool

- `builder.tool_spec` (`scripts/build_geotizer_tool.py`) execs the built artefact and returns `get_tool_specs(Tools())`.
- `builder.tool_spec` raises `SpecUnavailable` when `open_webui.utils.tools` cannot be imported.
- `install_geotizer_tool.py` sends every request through `_OPENER` with `timeout=REQUEST_TIMEOUT_SECONDS`, and never through `urllib.request.urlopen`, whose default opener follows redirects.

## Upstream seams

- `SEAMS` (`backend/tests/test_geotizer_seams.py`) maps each upstream file the fork still changes, by path relative to `backend/`, to the substrings that must appear on a line marked `GEOTIZER-SEAM`.
- `SEAMS` holds one file, `open_webui/utils/tools.py`, with two lines.
- The two lines carry a trailing `# GEOTIZER-SEAM` comment that must stay: `from open_webui.tools.geotizer import query_geomas_retrieval_plan  # GEOTIZER-SEAM` and `builtin_functions.append(query_geomas_retrieval_plan)  # GEOTIZER-SEAM`.
- `DEPARTED` lists the upstream files the fork no longer changes, which must contain neither the marker nor the word `geotizer`, in code or in a comment.
- `open_webui/main.py` must be byte-identical to the upstream ref named in `scripts/upstream_ref.txt`, so no comment in it may be removed.
