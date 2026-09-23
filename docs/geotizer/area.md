# Area request and area workflow

An area fill resolves a named area or a set of licences into members, fills each member with the single-object workflow, and asks gis_service to fold the filled members into one area card.
`backend/open_webui/services/artifacts/geotizer/area_request.py` resolves the request and renders the answer.
`backend/open_webui/services/artifacts/geotizer/area_workflow.py` fills the members and calls the fold.

## Cost and limits

| Name | Meaning |
| --- | --- |
| `MEMBER_HOURS` | The measured wall-clock cost of filling one area member, in hours, used by `cost_phrase` for every cost statement. |
| `DEFAULT_AREA_DEADLINE_SECONDS` | `None`: an area has no deadline by default. |
| `GEOMAS_AREA_DEADLINE_SECONDS` | Sets an area deadline; `run_geotizer_area_workflow` records each member past it as `not_attempted` with `area_deadline_reached`. |
| `DEFAULT_CONCURRENT_MEMBERS` | Three members fill at once by default. |
| `GEOMAS_AREA_CONCURRENT_MEMBERS` | Sets how many members fill at once. |

- `concurrent_members` gives `DEFAULT_CONCURRENT_MEMBERS` with no note for an unset valve.
- `concurrent_members` gives the default with a note naming the raw value for a non-integer, zero or negative value.
- `run_geotizer_area_workflow` uses `concurrent_members` to bound how many members fill at once and never how many are filled.
- `run_geotizer_area_workflow` falls back to `DEFAULT_CONCURRENT_MEMBERS` for a `concurrent_members` value that is not an integer.

## Resolving members

- `SEARCH_UNREADABLE`: gis_service's `resolve_scope` always returns `scope_resolution`, so an answer without it is refused as unreadable and never reported as not found.
- `PROJECT_NOT_FOUND` has the value `scope_project_not_found`, gis_service's own error code for a `project_id` that matches no project.
- `POLICY_VERSION_UNKNOWN`: a supplied `policy_version` other than `AREA_POLICY_VERSION` is refused, never used.
- `ARG_NOT_CONFIRMED` is the state of a sent `project_id` whose answer lacks `scoped_to_project`.
- A gis_service older than the scoping accepts `project_id` on `resolve_scope` and ignores it without error.
- `ARG_NOT_HONOURED` is set on `project_id_state` only by `_confine`, and only after it sees rows from a project other than the target.
- `_search` moves the suggested project names gis_service puts in `candidates` with `candidates_are: known_projects`, when a search matched nothing, to `known_projects`.
- `_not_found_message` prints gis_service's `searched_projects` verbatim as «Искали в проектах: N».
- `_LAYER_MEANING_RU` glosses only the three `GIS_Data_RF` licence layers, and any other layer is printed with `_LAYER_STATE_UNKNOWN_RU`.
- `_member` carries gis_service's reason in `centroid_unavailable`: `unreadable:<ExceptionType>` or `outside_the_world`.
- `resolve_area_members` resolves a name search to a project, which has no polygon, so its single member carries `centroid_unavailable = NAME_SEARCH_HAS_NO_POLYGON`.
- `_CENTROID_CAUSE_RU` is keyed by gis_service's `scope.CENTROID_UNREADABLE` and `scope.CENTROID_OUTSIDE_THE_WORLD`, plus `NAME_SEARCH_HAS_NO_POLYGON`.
- `_SCOPE_FIELDS` holds the only member keys forwarded to `geotizer_area_scope`, whose `AreaMember` model forbids undeclared fields.

## Contract and CRS

- `AREA_POLICY_VERSION` must equal `policy_version` in gis_service's `arcgis_mcp/geotizer/assets/area_aggregation_policy.v1.json`.
- `GMM/scripts/validate_area_policy_version.py` checks the `AREA_POLICY_VERSION` copies against each other.
- `_GEOGRAPHIC_CRS` mirrors gis_service's `measurement_crs._GEOGRAPHIC`.
- `utm_zone_for` restates gis_service's `measurement_crs.utm_zone_for`.
- `test_the_worked_examples_resolve_to_the_zones_the_task_names` and `GMM/scripts/validate_utm_zone_arithmetic.py` pin the two `utm_zone_for` copies to the same worked examples.

## Filling members

- `fill_area` merges area members with the scope manifest's `entities` by `entity_id`, never by position.
- `fill_area` passes the resolved `project_id` and `calculation_crs` to `run_geotizer_area_workflow`, and gis_service digests them into the area's id.
- `run_geotizer_area_workflow` passes `area_member` to every member fill as the literal `True`, which `run_scope` reads with `bool(scope.get('area_member'))`.
- Concurrent members share no state.
- The orchestrator's per-fill round usage lives in a `ContextVar` that each `asyncio.gather` task copies, and `test_each_member_keeps_its_own_rounds` checks this.
- `counts` is mutated only between awaits on one event loop and takes no lock.
- A member's `running` count is incremented inside the `try` whose `finally` decrements it.
- `member_filler` calls each `per_member` factory once per member call, lets an explicit caller argument override the built value, and exposes the factory names as `per_member_keys`.
- `QueryDrain.drain()` returns everything recorded since construction and never clears, so `fill_geoteaser_area` supplies a fresh instance per member through `per_member`.

## Member states

- `FAILED`: a member is `failed` only when an exception escaped its fill.
- A member whose run finished and refused to publish is `filled` and carries its own `status`.
- `_UNREACHED` is the only translation from member states to the fold's `unreached` vocabulary.
- gis_service's `area_summary.member_status` renders an unrecognised state as unknown.

## Progress reporting

- `run_geotizer_area_workflow` calls `on_progress` once before any member is scheduled, and once after each member's start and each member's settle.
- `report` takes and delivers each progress snapshot under the `delivery` lock, one at a time.
- `progress_line.error` records the first progress-report failure, not the last.
- The area document carries `progress_line` only when an `on_progress` call raised or a member reported a state outside `_SETTLED`.
- `area_progress_line` counts members per state.
- `area_progress_line` derives `waiting` as members minus the other states, floored at zero.
- `area_progress_line` omits the failed and not-started terms when they are zero.

## Artefacts and the answer

- `AREA_ARTEFACT_LABELS` copies the names in gis_service's `area_card.AREA_ARTEFACTS`.
- An artefact name missing from `AREA_ARTEFACT_LABELS` is silently not linked, and GMM's cross-repository job checks the two lists.
- Every name `AREA_ARTEFACT_LABELS` links needs an `ARTIFACTS` entry and a `/files/{run_id}/<name>` GET route in `backend/open_webui/routers/geotizer.py`.
- `ARTEFACT_PROXY_PREFIX` is the same `/api/v1` prefix `terminal._proxy_download_path` puts on a member's link.
- A current GIS service's area record lists seven files and an empty `not_rendered` (gis_service `area_card.NOT_RENDERED` is `{}`).
- An empty `not_rendered` means nothing is missing.
- An absent `not_rendered` key comes from a service that predates the area source report.
- `AREA_ARTEFACT_LIMITS` is printed only while the service's `not_rendered` record names the source report (`SOURCE_REPORT_NOT_RENDERED`), or when the record is absent.
- `render_area_answer` prints the cost notice, the refused-deadline note, the refused-concurrency note and the scope notice above the member list, in that order.
