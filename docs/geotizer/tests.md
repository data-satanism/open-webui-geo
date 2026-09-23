# Tests, fixtures and repository guards

The GeoTeaser tests live in `backend/tests/`.
This document lists the guards those tests enforce on the repository, the fixtures and test-module constants they share, and the tests that read source text.

## Running

- CI (`.github/workflows/backend.yaml`, `.github/workflows/geotizer-backend.yaml`) runs the import-boundary check as its own step, from the repository root:

```bash
python scripts/check_geotizer_import_boundary.py
```

- `test_every_required_field_is_required_by_the_contract_that_owns_it` and `test_every_list_member_is_an_array_in_the_contract` (`test_project_evidence_dossier.py`) need a `GMM` checkout beside this repository and skip without one.

## Service layering

`backend/tests/test_geotizer_service_layering.py` holds `LAYERS`, a layer number per module under `backend/open_webui/services`.

- A module under `backend/open_webui/services` may import only modules at the same or a lower layer number.
- `artifacts/geotizer/validation.py` sits at layer 1, the lowest layer any GeoTeaser artefact module occupies.
- `artifacts/geotizer/terminal.py` imports `xlsx_download_path` from `owner_envelope` and sits one layer above it.
- `core/deadline.py`, `project_evidence/claims.py`, `project_evidence/agreement.py` and `artifacts/geotizer/run_scope.py` import nothing from the `services` tree.
- No module outside `services/evaluation` imports a module in it.
- Neither `artifacts/cpr` nor `artifacts/geotizer` imports a module of the other.

## Import boundary

- `check_import_boundary` (`scripts/check_geotizer_import_boundary.py`) reads every `.py` module under `PURE_TREE` (`backend/open_webui/services`).
- `check_import_boundary` rejects any absolute `open_webui` import, at module level or inside a function, in every import spelling.
- `check_import_boundary` allows relative imports and packages that only share the `open_webui` prefix.
- `check_import_boundary` reports an unparseable module as a violation, and returns every violation with the number of modules checked.
- `check_import_boundary` raises `PureCoreMissing` when `PURE_TREE` is absent or holds no module, and `main` then returns 1.
- `OWNED` (`test_deferred_imports_resolve.py`) excludes `services/`, which the import-boundary script covers.
- `OWNED` lists `open_webui/utils/geotizer_orchestration.py`, which does not exist, and `_owned_modules` drops it silently.

## Retired names and model ids

- `RETIRED_SERVICE_PRODUCERS` (`test_geotizer_producer_literals.py`) holds the four retired `gis_service` producer names, which no file outside `EXEMPT_PREFIXES` may contain.
- `_scanned_files` scans every `.py`, `.json` and `.md` file under the repository root, except paths under `EXEMPT_PREFIXES` (only `backend/tests/`) and paths through a `NOT_SOURCE` directory.
- `_python_offenders` checks string constants only, so a comment may name a retired producer.
- `_python_offenders` skips a docstring only when its raw text equals its `ast.get_docstring` form, so an indented multi-line docstring naming a retired producer is reported.
- `test_each_exemption_covers_something_that_is_really_there` requires every exempt prefix to still contain a retired name, and `backend/tests/` meets it through the `RETIRED_SERVICE_PRODUCERS` constant.
- `RETIRED_TOOL_IDS` (`test_geotizer_boundary_contract.py`) holds the Workspace Tool ids the repository records as deleted, `mainagent_tool_yulong` and `sub_agent`.
- `ENTITY_REGISTRIES` (`test_geotizer_boundary_contract.py`) holds the model registries a service entity is created through: `Knowledges`, `Models`, `Groups`, `Users`, `Tools`, `AccessGrants`.
- `MODEL_INVENTORY` (`test_geotizer_model_identities.py`) holds the confirmed model ids of the contour, and a new model id is recorded in `GMM/prompt-verification.md` before it is added there.
- `MODEL_ID_DEFAULTS` lists every module-level name in the repository that holds a model id, by file, and holds only `DEFAULT_AGENT_MODEL_IDS` in `open_webui/utils/geotizer_service_account.py`.
- `RETIRED_MODEL_IDS` holds model ids that were wrong and must not reappear as a string literal under `backend/open_webui`; a comment may still name them.

## Fixtures

| Fixture | Fact |
| --- | --- |
| `backend/tests/data/lekyn-owner-batches.json` | gis_service holds a copy at `tests/data/lekyn-owner-batches.json` and renders from it. |
| `backend/tests/data/lekyn-dossier.example.json` | `ent-licence` is a child of `ent-object`. |
| `backend/tests/data/lekyn-dossier.example.json` | `CPR-1.3.1`, answered from `ent-analogue`, is the only answered cell that draws on an entity that is neither the object nor its child. |
| `OPTIONAL_BUT_LOAD_BEARING` (`test_project_evidence_dossier.py`) | The fields whose removal changes a projection although the contract makes them optional, each with the reason it may be absent. |
| `CHANGES_NOTHING` (`test_project_evidence_dossier.py`) | The fields whose removal changes neither projection. |
| `NOT_IN_THE_REFERENCE_DOSSIER` (`test_project_evidence_dossier.py`) | The array members the reference dossier leaves empty, whose requirement lists only the GMM schema cross-check covers. |
| `BATCHES` (`test_geotizer_status_lines.py`) | The eight batches of `gis_service/arcgis_mcp/geotizer/assets/assignment_policy.json`, with their producers, in the policy's order. |
| `MINERAL_ROW`, `ELEMENT_ROW`, `AGE_ROW`, `ORE_ROW` (`test_the_rows_declared_kind_is_binding.py`) | The field keys of workbook cells D61 «минерал 1», H66 «главное полезное ископаемое 1», H22 «абсолютный возраст» and E47 «объем руды» in `gis_service/arcgis_mcp/geotizer/assets/field_catalog.json`. |
| `FILL_ACTIONS` (`test_the_area_tool_asks_before_it_spends_a_day.py`) | Equals the `action` literal of `GeotizerFillRequest` in `gis_service/arcgis_mcp/geotizer/api.py`. |
| `MAGADAN` (same module) | A (longitude, latitude) pair in EPSG:4326 degrees, the unit `licence_centroid` in `gis_service/arcgis_mcp/geotizer/scope.py` returns, which `utm_zone_for` resolves to EPSG:32656. |
| `Service` (same module) | `scopes=False` models a service that accepts `project_id` on `resolve_scope` and ignores it. |
| `_ConfigurableOrchestrator.Valves` (`test_geotizer_agent_caller.py`) | Discards undeclared keyword arguments, modelling an orchestrator `Valves` model with pydantic `extra="ignore"`. |
| `_request` (`test_kb_collection_scope.py`) | The fake request carries `state.internal`. |

- `RECORDED_MAX_CHECKS` (`test_geotizer_validation_latency_budget.py`) is computed by `worst_case_checks` as `MAX_OWNER_ATTEMPTS` × owner chunks per template, plus `MAX_BATCHES`.
- `_export_is_a_shim` (`test_geotizer_source_inventory_repair.py`) treats `GMM/operations/workspace-exports/geoteaser.py` as a shim when it is missing, or when it mentions `fill_geotizer` and has fewer than 500 lines, and the `reference` fixture then skips the parity tests.
- The module-level `PRODUCER_KINDS` dict in `test_geotizer_orchestration.py` is unused.
- `test_the_seven_cell_limit_is_a_listing_limit_and_not_a_count` (`test_run_notes.py`) expects six listed keys, the value of `RUN_NOTE_KEY_SAMPLE`, although its name says seven.

## Tests that read source text

| Test | Reads | Must stay |
| --- | --- | --- |
| `test_the_shim_and_the_builtin_say_the_same_thing_about_run_mode`, `test_the_whole_parameter_description_reaches_the_generated_schema` (`test_geotizer_tool_build.py`) | `fill_geotizer.__doc__` and the `ADAPTER` docstring in `scripts/build_geotizer_tool.py` | The `THE_CONTRACT_SENTENCES` text in both. |
| `test_the_adapter_says_where_it_came_from_and_not_to_edit_it` (`test_geotizer_tool_build.py`) | The built artefact | The `# Generated by scripts/build_geotizer_tool.py from ...` and `# Do not edit in the Workspace. ...` lines inside the `ADAPTER` string literal. |
| `test_each_download_is_authenticated`, `test_the_attachment_never_replaces_the_download_link` (`test_geotizer_boundary_contract.py`) | Fixed-width text windows (600 and -600/+400 characters) of `routers/geotizer.py` and `tools/geotizer.py` | Code within those windows. |
| `test_the_rule_still_only_looks_at_direct_patches` (`test_plan_row_historical_marker.py`) | `inspect.getsource(validation._plan_patch_violations)` | The code line `origin == 'direct' and _note_dates_itself_before_the_plan(note)`. |
| `test_the_workflow_normalises_before_it_repairs` (`test_a_string_source_locator_does_not_kill_the_fill.py`) | `workflow.py` text | `normalize_patch_source_locators(envelope)` first occurring before `inject_row_declared_work_stage(next_batch, envelope)`. |
| `test_the_workflow_injects_before_it_validates` (`test_the_row_declares_the_work_stage.py`) | `workflow.py` text | `inject_row_declared_work_stage(next_batch, envelope)` first occurring before `violations = validate_owner_envelope(`. |
| `test_the_feedback_surface_is_the_validator_and_only_the_validator` (`test_a_refusal_that_cannot_be_satisfied_names_its_exit.py`) | `validation.py`'s top-level functions and `workflow.py` text | 34 occurrences of `patches[{index}]` and 11 of `_with_exit(` (the definition included) in `validation.py`; `violations = validate_owner_envelope(` and `feedback = list(violations)` in `workflow.py`. |
| `test_every_search_tool_a_specialist_uses_records_what_it_was_asked` (`test_the_queries_a_run_issued_reach_the_run_log.py`) | `open_webui/tools/builtin.py` source | The four functions whose text contains `record_query(`. |
| `test_the_field_is_named_for_the_call_and_not_for_the_thinking` (`test_where_two_and_a_half_hours_went.py`) | `geotizer_query_sink.__doc__` and `geotizer_query_sink.record_query.__doc__` | Both docstrings, as strings. |
| `test_services_readme_counts.py` | `services/README.md` and the `services` tree | The `field_key` residue count `services/README.md` states, equal to the recomputed count. |
| `test_the_run_log_carries_every_run_level_record` (`test_retrieval_query_log.py`) | `inspect.getsource(workflow)` on the `run_log = {` block | The run-level record keys in that block. |
| `test_the_pipeline_wires_both_rules_on_both_paths`, `test_the_salvage_path_is_given_the_same_licence_term_as_the_loop` (`test_an_absence_is_not_a_value.py`) | An AST scan of `workflow.py` for `refuse_*` calls | The two calls of each rule and their `accepted_fields` argument. |
| `test_every_seam_is_present_and_marked`, `test_the_file_carries_no_unlisted_marked_lines`, `test_the_detector_notices_a_seam_that_lost_its_marker` (`test_geotizer_seams.py`) | `open_webui/utils/tools.py` | The two `# GEOTIZER-SEAM` comments. |
| `test_main_carries_no_fork_code` (`test_geotizer_seams.py`) | `git diff` of `open_webui/main.py` against the pinned upstream ref | An empty diff. |
