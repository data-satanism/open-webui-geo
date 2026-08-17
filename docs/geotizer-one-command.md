# GeoTeaser one-command orchestration

`MainAgent_yulong` exposes one built-in operation, `fill_geotizer`, when its
model metadata contains the existing `mainagent_tool_yulong` tool ID.
Specialist models do not receive this operation and therefore cannot start
nested GeoTeaser runs.

## User contract

The complete workflow starts from one ordinary chat message:

```text
Заполни Геотизер для Верхне-Колпинской площади.
В конце сделай Excel-таблицу и пришли ссылку для скачивания.
```

The parent model calls `fill_geotizer(object_name=...)` once. The function
returns a short completeness summary and an authenticated XLSX download link
under the Open WebUI origin.

An interrupted run can be continued by the same function with its `run_id`.

## Responsibility split

- `gis_service` owns GIS project resolution, DataCube handoff, the canonical
  108-row/351-field state, owner validation, final audit and XLSX rendering.
- Open WebUI owns specialist sub-chat execution and the orchestration loop.
- `MainAgent_tool_yulong` remains the existing KB/WEB/GIS delegation runtime.
- The existing `Sub Agent` runs the final `skilled` owner batch (`ASSEMBLE`)
  without external tools.

The Open WebUI controller does not write workbook cells directly.

## Producer routing

Each batch and evidence route names a `producer`. Those names are
`gis_service`'s — they come from `assignment_policy.json` under
`policy_version: geotizer_assignments.v2` — and Open WebUI passes each one to
`multitask_orchestration.run_agent_task` **verbatim**. There is no translation
step and nothing to configure for it.

`.v2` is what makes that work: it renamed the eight batch owners to `gis`, `kb`,
`web` and `skilled`, which are exactly the four agents the tool serves. Each has
a model valve (`GIS_MODEL`, `KB_MODEL`, `WEB_MODEL`, `SKILLED_MODEL`) and a tool
surface, both on that tool.

A name the tool does not serve is refused where the configuration lives:

```json
{"code": "unknown_agent", "retryable": false,
 "configured": ["gis", "kb", "skilled", "web"]}
```

so the run stops rather than routing a batch to a guessed specialist.

**A `PRODUCER_KIND_MAP` valve did this for one round and is gone.** If a contour
still has it set, it is now inert — delete it or leave it, but do not add it to
a new one. It was a second place the routing could be wrong, and it caused two
outages: once when the code that reads it merged before anyone wrote it, and
once when `.v2` renamed the producers out from under a valve still holding `.v1`
names.

If the batch plan ever renames its owners again, the fix is a tool edit adding
or renaming an agent — the same artefact that already holds that agent's model
valve and tool surface. One place, not two.

## Deterministic loop

For each `next_batch` returned by `geotizer_fill`:

1. ignore evidence routes already satisfied by `start.datacube`;
2. run independent `contributor_call` routes concurrently;
3. call the exact owner producer with only the bounded field catalog,
   DataCube handoff and contributor evidence;
4. require one JSON patch for every owner field and no foreign fields;
5. preflight statuses, values, source inventory, source references and
   locators;
6. submit the atomic owner batch to `gis_service`;
7. repair a rejected owner response at most three times;
8. finalize only after `next_batch` becomes empty.

The controller is capped at 12 batches. The current policy has eight.

## Download boundary

The private GIS artifact route is not exposed as an agent tool. Open WebUI
provides an authenticated proxy:

```text
GET /api/v1/geotizer/files/{run_id}/geotizer.xlsx
```

The proxy reuses the configured `mcpgis` connection and never places its bearer
token in the user-visible URL.

## Validation

Focused tests cover:

- contributor-before-owner ordering;
- `start.datacube` route suppression;
- unsupported producer rejection;
- JSON and fenced-JSON extraction;
- exact field partition validation;
- provenance on negative decisions;
- the full start/submit/finalize state sequence;
- bounded repair before the first state mutation.

Run locally:

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests/test_geotizer_orchestration.py -q
```
