# Single-object workflow

`backend/open_webui/services/artifacts/geotizer/workflow.py` fills one GeoTeaser card for one object: it starts or resumes a GIS run, fills every owner batch chunk by chunk, and finalizes the run.
The entry point is `run_geotizer_workflow`.

## Effect shell

- `GisCall`, `AgentCall` and `VisionEvidenceCall` are the effect shell's types; the adapter `tools/geotizer.py` builds them, and `workflow.py` builds none.
- `RagDispatcher` declares the four dispatcher members the run uses: `settings`, `begin_attempt`, `submit_shadow` and `execute_active`.
- `GEOTIZER_ARTIFACT_SET` is `('geotizer_object',)`: the workflow produces one artefact set, of which the audit and the source report are parts.

## Limits

| Constant | Meaning |
| --- | --- |
| `MAX_BATCHES` | The batch loop's safety ceiling, 12. |
| `MAX_OWNER_FIELDS_PER_CALL` | The default chunk size, 18, a multiple of `OWNER_ROW_WIDTH`. |
| `OWNER_ROW_WIDTH` | 6: every teaser resource row (rows 44-56) is six contiguous fields. |
| `MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES` | The owner attempt loop stops after this many consecutive empty owner responses. |
| `MAX_CONSECUTIVE_SPECIALIST_FAILURES` (`owner_envelope.py`) | 2: the owner attempt loop ends after this many consecutive specialist-failure signals. |
| `DEFAULT_FILL_DEADLINE_SECONDS` | Six hours: a hang backstop, not a time budget. |

## Chunking

- `partition_owner_batch` (`owner_envelope.py`) slices a batch's fields into fixed-width chunks without regard to rows, so a chunk boundary can split a row.
- `_resource_row_consistency_violations` (`validation.py`) checks a resource row only among the patches of one owner chunk.
- `resolve_owner_fields_per_call` returns `(MAX_OWNER_FIELDS_PER_CALL, None)` for an unset or empty value.
- `resolve_owner_fields_per_call` accepts a positive integer that is a multiple of `OWNER_ROW_WIDTH` with no note.
- `resolve_owner_fields_per_call` returns the default with a note naming the requested value and the default for any other value.
- The adapter reads the chunk size from the `GEOMAS_OWNER_FIELDS_PER_CALL` environment variable.

## Fill deadline

- The adapter reads the deadline from the `GEOMAS_FILL_DEADLINE_SECONDS` environment variable, interpreted by `resolve_fill_deadline`.
- A note from `resolve_fill_deadline` or `resolve_owner_fields_per_call` is appended to `run_notes`.
- The deadline starts at the top of `run_geotizer_workflow`, before scope resolution and the object profile.
- Deadline expiry is checked between batches and between chunks, and never cancels a call in flight.
- `_produce_and_submit_owner_batch` gives a chunk reached after expiry a failure envelope with `stopped_by_deadline=True` and makes no specialist or owner call for it.
- A batch closed after expiry is still submitted complete, because GIS `finalize` refuses with `missing_owner_batches` while any owner batch is unapplied, whatever `allow_draft` says.
- `_remaining_batch_count` counts the batches in the deadline stop note from GIS's `batches_total` (gis_service `_summary`, `len(self.batch_order)`), and falls back to the applied batches plus one.
- `_remaining_batch_count` never counts from `MAX_BATCHES`.

## Run identity and registry

- `geotizer_run_identity` partitions the run key on `project_id`, else `object:<object_name>`, else `licence:<licence_id>`.
- `geotizer_run_identity` raises `GeotizerOrchestrationError` when `project_id`, `object_name` and `licence_id` are all empty.
- An unpinned request is scoped as `object:<object_name>` with artifact set `('geotizer_object',)`.
- The adapter passes `__message_id__` into the run key as `attempt_key`.
- The adapter logs an absent `__message_id__` as a warning.
- The requesting user's id is part of the run key as `requester_id`.
- The query drain is not part of the run key.
- Without a `requester_id`, `run_geotizer_workflow` uses no registry binding, and every call starts a new run.
- `build_run_registry` returns None, meaning one run per command, when `ENABLE_ENV` (`GEOMAS_RUN_IDEMPOTENCY`) is `0`, `false`, `no` or `off` in any case, when `DATA_DIR` is not writable, or when `os.link` fails there.

| `FileRunRegistry` member | Behaviour |
| --- | --- |
| Storage | A binding is a `<key digest>.json` file holding `key` (`project_id`, `artifact_set`, `frozen_inputs_hash`) and `run_id`. |
| `find` | Raises `RunRegistryUnavailable` for a corrupt or zero-byte binding file rather than returning None. |
| `record` | Raises `ValueError` ("already bound") for a different run on a bound key; recording the same run again is a no-op. |
| `forget` | No module under `backend/open_webui` other than the registry calls it. |

## Start and resume

- `_start_gis_run` always sends `licence_id` and `licence_layer_id` on `start`, as `None` when absent.
- GIS records a `kb_scope_status` of `None` as `unknown`.
- A `run_id` that GIS reports as missing raises `GeotizerOrchestrationError(UNRESOLVABLE_RUN_ID)` without starting a run.
- Any other exception from the GIS `get` call propagates unchanged.
- `FINISHED_STATUSES` (`finalized`, `completed`) mean the run has produced its card and will produce no other.
- `_resume_or_explain` marks a resumed run whose status is in `FINISHED_STATUSES` with `resumed_run_was_already_finalized`, and `run_geotizer_workflow` copies the mark onto the final payload.
- `_SOURCE_ID_PATHS` lists the paths, tried in order, at which an item of Open WebUI's `metadata['files']` carries its id.
- `run_geotizer_workflow` writes the active run id into the caller's `started_run` mapping as soon as the GIS run exists.
- `run_geotizer_workflow` calls `set_gis_scope` once per fill, after project resolution, with `area_member`, which the orchestrator tool reads to tell an area member from a single fill.
- `OBJECT_PROFILE_TASK_ID` is both the producer and the task id of the GIS object-profile call, which GeoTeaser issues and `gis_service` never plans.
- `batches_total` is read once from the start state, not from each submit response.

## Chunk evidence

- `_agent_call_recording_queries` enters the query-recording scope inside each coroutine, so every contributor scheduled by `asyncio.gather` has its own scope.
- `_collect_chunk_evidence` records every contributor round with `observe_round` as `burnt` (`empty_completion`), `failed` or `succeeded`.
- `_collect_chunk_evidence` de-duplicates `gis_trace_log` entries by `trace_id`.
- `_collect_chunk_evidence` calls `record_retrieval_queries` for a `kb` contributor only when a RAG dispatcher is in `active` or `shadow` mode.
- `_produce_and_submit_owner_batch` passes `object_scope=current_state.get('object_scope')` to `compact_batch_context`.
- `_produce_and_submit_owner_batch` holds in `scope_name` the non-empty names among the resolved `object_scope.object_name` and the requested `object_name`.
- Both `validate_owner_envelope` call sites pass `scope_name` as `object_name`, so subarea site names are checked against both names.

## Deterministic GIS evidence

- `_receives_deterministic_gis` (`prompts.py`) delivers the deterministic GIS output only to a `GIS-DC` batch holding a field under `INFRASTRUCTURE_ROW_PREFIXES` and to a `KB-STUDY` batch holding a field under `STUDY_ROW_PREFIXES`.
- `INFRASTRUCTURE_ROW_PREFIXES` covers all twelve rows 77-88, which belong to `GIS-DC`, so a `GIS-DC` chunk holding any one of them receives the deterministic output.
- The deterministic calculation answers every row 77-88 (`INFRASTRUCTURE_FIELD_KEYS` in `gis_service` covers r077 to r088).
- `STUDY_ROW_PREFIXES` covers rows 37-42 (trenches, the two drillhole kinds, magnetometry, electrical survey, geochemistry), which belong to `KB-STUDY` and are answered by the deterministic calculation.
- `_contributors_for_batch` uses `_needs_deterministic_infrastructure` to remove the GIS contributor from a `GIS-DC` batch that holds an infrastructure row.
- `_receives_deterministic_gis` is a separate predicate and does not decide whether the GIS contributor is removed.
- `infrastructure_cache` holds one deterministic GIS infrastructure calculation per run, keyed by run id and shared by every chunk.
- `_deterministic_infrastructure_evidence` keeps the calculation's `layer_manifest` in the cache and leaves it out of the evidence given to the owner.
- `_deterministic_infrastructure_evidence` returns the accepted `field_proposals`, the other batches' keys as `deferred_field_keys`, and the refused asked-for proposals as `unusable_field_proposals`.
- `_deterministic_infrastructure_evidence` filters `unanswerable_field_keys` to the asking batch's field keys.
- A calculation whose `workflow_status` is neither `ready` nor `partial` raises `GeotizerGisError` with `code: gis_infrastructure_unavailable`, GIS's `workflow_status`, `returned` naming where the failure was carried (`error`, `violations` or `state`), and a `violations` list that is always present and empty when GIS sent none.
- `run_geotizer_workflow` takes `gis_layer_manifest` from the `layer_manifest` in `infrastructure_cache`, so it is `None` when no chunk called the calculation.
- `record_gis_proposal_rejections` appends each evidence item's `unusable_field_proposals` and each `deferred_field_keys` entry (as reason `not_this_batch`) to one run-level list, tagged with the refusing `batch_id`, and skips entries that are not mappings.
- `mark_rejections_answered_elsewhere` runs once, after the last batch, against the state's fields.
- `mark_rejections_answered_elsewhere` sets `answered_elsewhere` (true only for a `filled` cell) and `answered_status` on each rejection, with `answered_status` `no_such_cell` when no cell has that key.

## Owner attempt loop

`_produce_valid_owner_envelope` asks the owner for an envelope up to `MAX_OWNER_ATTEMPTS` times and falls back to `owner_failure_envelope` with salvage.

- The loop stops when an attempt's violation set equals the previous attempt's, and reports it through `_owner_failure_sentence(..., unactionable_feedback=True)`.
- A specialist failure signal with `retryable` exactly `False` stops the loop after one call.
- A signal with no `retryable` field is retried like `retryable: true`, up to `MAX_CONSECUTIVE_SPECIALIST_FAILURES`.
- The failure envelope's `attempts` is the number of attempts made.
- The loop bounds repair feedback with `grouped_repair_feedback` and the previous output with `bounded_previous_output` before `_owner_prompt` receives them; `_owner_prompt` does not bound them.
- The grouped feedback form is used only in the repair prompt, and `feedback_by_attempt` keeps the ungrouped violations.
- After a parsed envelope, the repair feedback is `validate_owner_envelope`'s return value, plus a coverage line when the owner answered with field proposals only.
- The refusal passes in `owner_envelope.py` run on the envelope the owner returned, and their notes are never shown to the owner.
- Notes from `normalize_source_inventory`, `coerce_contradictory_patch_fields`, `normalize_patch_source_locators` and `inject_row_declared_work_stage` reach `run_notes` on every attempt.
- Notes from the later passes reach `run_notes` only when the attempt ships or when it repeats the previous attempt's violation set.

## Pass order

- `normalize_source_inventory` runs before any pass that reads `source_refs`.
- `coerce_contradictory_patch_fields` runs before `repair_negative_provenance`, and `classify_rule_excluded_patches` runs after it.
- `normalize_patch_source_locators` runs before `inject_row_declared_work_stage`.
- `inject_row_declared_work_stage` runs before `validate_owner_envelope`.
- `register_locator_only_sources` runs before validation, so `_locator_ref_violations` fires only for a ref written after that repair.
- `refuse_absence_written_as_a_value` runs before the proposal appliers, on the attempt path and on the salvage path.
- `refuse_absence_written_as_a_value` and `refuse_a_licence_record_in_the_work_stage_row` each run once on the attempt path and once on the salvage path, and the latter receives `accepted_fields` on both.
- `refuse_lone_web_resource_values` runs after every proposal applier.
- `refuse_out_of_radius_infrastructure` runs after the appliers and before `spatial_divergence_notes`; `refuse_prose_in_numeric_rows` follows it, then `refuse_the_wrong_kind_of_answer`.
- `a_reading_is_not_a_computation` runs before `refuse_a_unit_the_source_contradicts`.
- `record_unrecorded_conflicts` runs after the appliers, and `retire_stale_projected_reasons` is the last pass.
- `classify_rule_excluded_patches` runs before the batch is submitted.
- The chunk-provenance stamp is added after validation: every envelope the loop returns, including the `owner_failure_envelope` fallback, passes through `_stamped_with_chunk_provenance`.
