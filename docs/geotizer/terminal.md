# Terminal output and status lines

`backend/open_webui/services/artifacts/geotizer/terminal.py` renders what the caller is handed back: the status lines emitted during a fill, the result card, the failure envelope, and the artefact links.

## Status lines

- `PHRASE` holds every status sentence, keyed by language then sentence key, with `{subject}` supplied by `StatusSettings.say`.
- The `ru` and `en` entries of `PHRASE` state the same fact.
- The Russian narrator is first-person singular.
- Any sentence naming a specialist must take its inflected form from the orchestration tool's case tables.
- `{members}` in `area_progress` is the noun from `StatusSettings.members_word`, not a number.
- `SUBJECT_DEFAULT` holds the subject of a status line that names no member, per language.
- `StatusSettings.subject_name` renders an empty subject as `SUBJECT_DEFAULT` for the language (`Геотизер` for `ru`, `GeoTeaser` for `en`).
- An empty `StatusSettings.subject` means the run itself, and an area member's lines use `member_subject`.
- The run line names the object as `object_name`, else `licence_id`, else `—`.
- An area member's `run_started` line omits the ` — <object>` tail that a single-object run's line carries.
- `StatusSettings.batch_line` takes the section label from `next_batch['label']`, which `gis_service/arcgis_mcp/geotizer/assets/assignment_policy.json` (`geotizer_assignments.v3`) sets on every batch.
- `_filled_cells` gives counts whose last two digits are 11-14 the genitive-plural form, whatever their last digit.

## Result card

- `carry_forward_summary`: a GIS build that records carry-forward provenance emits `run_mode` on every summary, including clean runs.
- An absent `run_mode` means the mode was not recorded.
- `derived_from: field_markers` means GIS reconstructed the carried count from field markers for a run that recorded no provenance.
- `target_line` takes the target from `fill_quality.target_fill_rate`, and no target value is hard-coded in `terminal.py`.
- `completeness_lines` reads the strict and basic figures from `audit.completeness`, never from `counts`.
- gis_service carries the `strict` and `basic` completeness pairs only under `audit.completeness` (`core._completeness`), and `counts` is `GeotizerService._summary`'s flat per-status dict.
- `completeness_pair` (`gis_service/arcgis_mcp/geotizer/core.py`) makes `strict` count `filled` cells and `basic` count cells that carry a contributed value.
- `completeness_lines` renders `total == 0`, a card with no cells, as «не определено».
- `completeness_lines` prints the whole-card `Заполнено` line first.
- `completeness_lines` then prints the in-stage fraction and the out-of-stage cell count with its sections, only when the service sent a complete `stage_scope` (in the final state, `counts` or `audit.completeness`), and computes no stage figure itself.
- `completeness_lines` prints one line for each of the five statuses (`filled`, `not_found`, `requires_expert_review`, `conflicted`, `agent_contract_failed`), and 0 for a status the service did not send.
- `completeness_lines` adds the calculated and analogue shares to the filled line only when `value_origins` is present.
- `completeness_lines` prints the run-variance band only from the `run_variance` the service sent, read from the final state or its `audit`, and computes no band figure itself.
- `_run_variance_lines` distinguishes the `run_variance` states `measured`, `stale` (a band measured on another build, printed with the repositories that differ), `unattributable` (the build could not be read) and unmeasured.
- `_run_variance_lines` prints nothing when `run_variance` is absent.
- `MAX_PRINTED_CONFLICTS` caps the disagreements the card prints, and the card always states the total.
- `conflict_section` returns `''` when nothing is conflicted.
- `conflict_section` reads the count from `counts`, falling back to `audit.completeness`, and states the count and points at `state.json` even without conflict detail.
- `conflict_section` prints each disagreement as `«value unit» [source_ref]` pairs joined by `↔` under `element / attribute`, falling back to the field key.
- `card_docx_link`'s link label contains no parentheses.
- `run_detail_lines` renders the retrieval-query count through `retrieval_query_line(final)`.

## Failures

- `MAX_TRACEBACK_LINES` is the number of innermost traceback lines `failure_details` keeps.
- `failure_details` returns the `details` mapping of an exception that carries one (`GeotizerGisError`), and returns None for a plain `GeotizerOrchestrationError`.
- `failure_details` tells a project-raised error from an escaped one by `isinstance(exc, GeotizerOrchestrationError)`, and `GeotizerOrchestrationError` subclasses `ValueError`.
- `GeotizerGisError` (`services/geotizer/errors.py`) keeps a mapping `details` unchanged, carries a list as `{'violations': list}`, a string as `{'message': string}`, None or no argument as `{}`, and any other value as `{'message': str(value)}`.
- The string form of `GeotizerGisError` is `json.dumps` of its `details`, and `GeotizerGisError` subclasses `GeotizerOrchestrationError`.
- `_gis_error_user_message` relays gis_service's own non-empty `message` for a `licence_scope` refusal.
- `_gis_error_user_message` replaces a fallback message that looks like serialised JSON, which `GeotizerGisError.__str__` produces, with a one-sentence summary naming the code and pointing to `details`.
- `_gis_error_user_message` returns a prose fallback unchanged.
- `recovered_run_id` returns `started_run['run_id']`, else the exception's `run_id`, else the requested run id, else `None`.
- The failure envelope's `resumable` is true only when that run id is not empty.

## Artefact links

- `_proxy_source_report_paths` requires `markdown`, `pdf` and `state`, and returns `{}` when any one is missing.
- `docx` and `run_log` are optional in `_proxy_source_report_paths`.
- `_proxy_source_report_paths` accepts a path only when it starts with `/geotizer/files/` and ends with its artefact's fixed file name, and returns it under the `/api/v1` proxy prefix.
- A present artefact whose path is not of that form raises `GeotizerOrchestrationError`.
- `_proxy_source_report_paths` reads `run_log` from the top level of the final payload, not from `source_report`.
- The `geotizer.docx` file name is set by gis_service (`arcgis_mcp/geotizer/service.py`) and matched as a literal in `_proxy_source_report_paths`.
- A fill offers its artefacts only as links in the result text, because `FileItem.svelte` opens a `chat:message:files` record of type `file` through `/api/v1/files/{id}` and the artefacts have no Open WebUI file id.
