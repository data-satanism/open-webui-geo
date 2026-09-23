# Owner envelope

`backend/open_webui/services/artifacts/geotizer/owner_envelope.py` holds the owner envelope's mechanics: batch tasks, chunk merging, the source inventory, locators, the failure envelope and salvage, chunk provenance, and the owner's context.
`backend/open_webui/services/artifacts/geotizer/prompts.py` renders the owner prompt from that context.
The refusal passes that change cells are in [refusal-passes.md](refusal-passes.md).

## Batch tasks

- `build_batch_tasks` passes the batch's `producer` verbatim as the task's agent name.
- An agent the orchestrator cannot serve is refused by `run_agent_task` in the Workspace tool (`GMM/operations/workspace-exports/multitask_orchestration.py`), not in this repository.

## Merging chunks

- `merge_owner_envelopes` renames each chunk's sources to `<batch_id lower-cased>__part_<n>__<source_id>`.
- `merge_owner_envelopes` applies the same rename to each patch's `source_refs` and to every ref at any depth of its `source_locator`.
- `_rename_locator_refs` renames every `source_ref` string and every string item of a `source_refs` list at any depth of a locator.
- `merge_owner_envelopes` runs `refuse_incoherent_resource_rows` on each chunk before validating it, and again on the merged envelope, where a row split across two chunks is detected.
- A resource row whose patches report more than one value of a row-identity qualifier does not raise.
- `refuse_incoherent_resource_rows` moves each `filled` patch of such a row to `requires_expert_review`, with `value_origin` `None` and a review-text `value` that keeps the original value and names the conflicting qualifier values.
- `refuse_incoherent_resource_rows` sets `source_locator.coherence_refusal` to `INCOHERENT_ESTIMATE_ROW_TRACE` on each patch it moves.
- `refuse_incoherent_resource_rows` writes one run note per conflicting row and leaves other rows untouched.
- `merge_owner_envelopes` still raises `GeotizerOrchestrationError` for a structural violation, such as an unregistered source ref.

## Source inventory

- `normalize_source_inventory` rebuilds every source to the five `GeotizerSource` keys `source_id`, `source_type`, `title`, `locator` and `url`, filling a missing `locator` with `''` and a missing `url` with `None`.
- `normalize_source_inventory` rebuilds an entry missing `source_type` or `title` from its evidence fields.
- The rebuilt `source_type` comes from `source_domain` through `_DOMAIN_TO_SOURCE_TYPE`: `gis`, `web` and `vision` as is, `kb` or `knowledge_base` in any case as `knowledge_base`, and any other domain as `derived`.
- The rebuilt `title` is `<producer> evidence`, else the whitespace-collapsed `retrieval_note`, else the `source_id`.
- The rebuilt `locator` is `source_locator` as sort-keyed JSON.
- `normalize_source_inventory` drops entries without `source_id`.
- `normalize_source_inventory` merges entries of identical content (ignoring `source_id`, with `url` part of the content) into the first, and remaps each patch's `source_refs` onto the survivor with repeats collapsed.
- `normalize_source_inventory` reports each repair in a note, returns a copy of the envelope, and returns no notes when nothing was repaired.
- `UNREGISTERED_LOCATOR_REF_TYPE` is the `source_type` (`derived`) of a source registered for a ref cited inside a locator and absent from the inventory.
- `register_locator_only_sources` adds one such source per unregistered locator ref, titled as cited without registration and located by the citing `field_key`.
- `register_locator_only_sources` leaves registered refs alone and returns one run note naming the added refs.

## Locators

- `source_locator` is either a mapping or a `key=value; key=value` string.
- GIS layer reads produce the string form (`project_id=…; layer_id=…; feature_index=…; geometry=…; coordinates=…; area=…`).
- `locator_map` (`core/text.py`) returns a mapping unchanged, parses a `key=value; …` string into a mapping of string values keeping only the segments that parse, and returns `{}` for anything else.
- `normalise_patch_locators` parses a string `source_locator` into a mapping and leaves `None` and every other shape unchanged.
- `extract_owner_envelope` and `recover_backend_owned_owner_envelope` are the two entry points for an owner envelope, and both apply `normalise_patch_locators`, so no patch past them carries a string `source_locator`.
- `normalize_patch_source_locators` converts string locators to mappings, leaves mappings and `None` unchanged, and returns a run note counting the converted cells only when it converted any.
- `evidence_locator_identity` reads its locator through `locator_map`, so a string or `None` locator does not raise.
- `inject_row_declared_work_stage` and `classify_rule_excluded_patches` write their keys into the parsed mapping of a string locator and keep its keys.
- `locator_source_refs` (`validation.py`) returns every `source_ref` value and every `source_refs` entry found at any depth of a mapping locator, and `[]` for a locator that is not a mapping.
- `_locator_ref_violations` checks every ref `locator_source_refs` returns against the envelope's `source_inventory`.

## Specialist failures

- `SPECIALIST_FAILED_MARKER` is the `status` value a specialist writes when its own call failed; this repository only reads it.
- `specialist_failure_signal` recognises a specialist failure by the payload's own `status: specialist_failed`, whatever its `code`.
- `specialist_round_record` includes `retryable` only when the signal states a bool.
- `specialist_round_record` omits `attempt` when none is given, as for a contributor round.

## Failure envelope and salvage

- `_owner_failure_sentence` checks a fill-deadline stop first, then specialist failures, then unactionable feedback, then all-empty attempts, then no parsed attempt, and otherwise reports a contract failure.
- `AGENT_FAILURE_STATUS` is the fallback status for cells the run never got an answer for, used only when the batch's `accepted_field_statuses` lists it.
- `EXPERT_REVIEW_STATUS` is the fallback status otherwise, and always in `ASSEMBLE`.
- `owner_failure_envelope` records every attempt's violations in `source_locator.owner_attempt_feedback`, which is an empty list when there are none.
- The fallback `retrieval_note` carries the last attempt's feedback.
- `owner_failure_envelope` omits the «Validation feedback» clause from the retrieval note when `stopped_by_deadline` is set.
- The fallback locator carries `owner_attempt_feedback`, `specialist_failures`, and `stopped_by` (`fill_deadline` or `None`).
- `owner_failure_envelope` passes `scope_name`, falling back to `[object_name]`, as the object name for salvage validation.
- A cell salvaged from a refused chunk has `SALVAGED_CELL_STRIPPED_KEYS` (five fallback locator keys) removed from its locator.
- A cell that is not salvaged keeps `owner_attempt_feedback` and `owner_attempt_diagnostics`.
- `SALVAGED_CELL_STRIPPED_KEYS` differs from `CONTRACT_FAILURE_LOCATOR_KEYS` in gis_service `arcgis_mcp/geotizer/renderer.py`, which holds the two keys that mark a contract failure.

## Chunk provenance

- `chunk_marker` reads a chunk given as `{'index', 'total'}`, as an `index/total` string or as a bare index into `{'index'[, 'total'][, 'batch_id']}`.
- `chunk_marker` returns `None` for a boolean or unusable value.
- `chunk_marker` keeps a `batch_id` the marker itself names over the one passed in.
- `stamp_chunk_provenance` returns a new envelope in which every patch carries `owner_chunk` when a chunk marker was read, and `evidence_incomplete` when contributors failed.
- `evidence_incomplete` holds de-duplicated `{agent, code}` records sorted by agent then code.
- `stamp_chunk_provenance` changes no status or value, and returns a non-list `patches` unchanged.
- `SpecialistRoundLog._by_chunk` is an uncapped index of failures by batch id and chunk index, from which `stamp_chunk_provenance` marks cells.
- `SpecialistRoundLog.failures_for` answers from that index, so the cap on `records` does not affect it, and a record naming no chunk is not indexed.

## Repair prompt bounds

- `PREVIOUS_OUTPUT_CAP` is the character cap on the raw previous output `_capped` keeps and on the serialised patch selection `bounded_previous_output` returns.
- `bounded_previous_output` selects the patches whose index a violation names as `patches[N]`.
- `bounded_previous_output` falls back to a head-and-tail character cap when the draft does not parse or no violation names a patch.
- `_VIOLATION_PREFIX` matches a violation's `patches[N]` prefix and an optional dotted field key after it.

## Owner context

- `compact_batch_context` includes retrieval plans only when `rag_v2_enabled` is set, a knowledge search plan is given and `owner_agent` is `kb`, and does not read the batch's `producer` for this.
- `compact_batch_context` keeps `object_name`, `run_id` and `batch`.
- `compact_batch_context` adds `entity_inventory` only to a chunk that has an entity-scoped field, as an empty list rather than absent when the scope resolved nothing.
- `entity_inventory` returns one entry with `entity_scope: licence_area`, the scope's `licence_id` as `entity_id` and `derived_from: LICENCE_AREA_ENTITY_SOURCE` (`object_scope.licence_id`).
- `entity_inventory` returns `[]` when the scope is not a mapping or has no licence.

## Owner prompt

- `prompts.py` performs no effect and reads no environment; the caller passes `rag_v2_enabled`.
- `context.entity_inventory` carries the entity ids that the `KB-RESOURCE-TECH` rules in `_batch_quality_rules` tell the owner to use verbatim.
- `_owner_prompt` tells the owner to copy an `entity_id` verbatim from `entity_inventory` and states when `not_applicable` applies to an entity-scoped row.
- The output contract's example `source_locator` in `_owner_prompt` is where the prompt says that every key in `field_semantics.required_qualifiers` goes into `source_locator`, including `work_stage`.
- `field_semantics` carries each GRR field's `required_work_stage` and `required_qualifiers`.
- A repair prompt carries `repair_feedback` and `previous_output` as its last two keys, so it shares its prefix with the attempt it repairs.
- A first-attempt prompt carries neither `repair_feedback` nor `previous_output`.

## Run notes

- `render_run_notes` groups `cells_note` notes by template and keyword fields, so a note whose field differs, such as `status`, renders as its own sentence.
- `RUN_NOTE_KEY_SAMPLE` (6) is the number of cell keys a rendered run note lists before it ends the list with an ellipsis.
