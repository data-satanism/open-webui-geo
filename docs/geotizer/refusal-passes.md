# Refusal passes

The refusal passes in `backend/open_webui/services/artifacts/geotizer/owner_envelope.py` run on the envelope the owner returned, after extraction and before validation.
They move cells between statuses, keep what they refused in the locator, and return run notes.
Their order is in [workflow.md](workflow.md#pass-order).
Conflict resolution by source authority is in `backend/open_webui/services/project_evidence/proposals.py`.

## Reader-facing reasons

- `MACHINE_TOKEN` in `backend/tests/test_a_rule_that_refuses_says_why_in_russian.py` duplicates `MACHINE_TOKEN` in `gis_service/arcgis_mcp/geotizer/reader_text.py` and must stay identical to it.
- `reader_facing` (`gis_service/arcgis_mcp/geotizer/reader_text.py`) rejects a text containing any `MACHINE_TOKEN` match whole, and does not trim it.
- Of the default reason constants, `UNIT_CONTRADICTS_SOURCE_RU` and `OUT_OF_RADIUS_REASON_RU` are format templates.

## Empty cells and their reasons

- `EMPTY_CELL_STATUSES` holds the statuses (`not_found`, `not_applicable`) that leave a cell empty and owe a reason.
- `EMPTY_CELL_REASON_PREFIX_RU` holds the lead sentence of a projected reason, distinct for `not_found` (a gap) and `not_applicable` (an answer).
- `state_the_negative_search` projects a note for both statuses in `EMPTY_CELL_STATUSES`, with a different sentence for each, and composes nothing when the locator records no search.
- `NEGATIVE_SEARCH_WHERE_RU` is the «где искали» sentence `state_the_negative_search` composes from `page_or_chunk_or_layer_or_feature_or_query` in the patch's `source_locator`.
- `NEGATIVE_FINDING_NOTE_RU` is the sentence `state_the_negative_search` appends from the `page_chunk_section` of each `negative_findings` entry.
- `PROJECTED_REASON_STATUS_KEY` is the `source_locator` key recording the status a projected reason was written for.
- `retire_stale_projected_reasons` clears only a reason stamped with `PROJECTED_REASON_STATUS_KEY` whose stamped status differs from the patch's status.

## Contradictory patch fields

- `coerce_contradictory_patch_fields` turns a `filled` patch whose value is a negative marker into `not_found` with value, unit and value origin null.
- `coerce_contradictory_patch_fields` removes any value, unit and value origin from a `not_found`, `not_applicable` or `conflicted` patch (`_VALUELESS_STATUSES`), or only the value origin when no value is present.
- `coerce_contradictory_patch_fields` writes one run note per coerced patch naming its field, and returns a new envelope without mutating its input.
- `NEGATIVE_VALUE_MARKERS` (`core/vocabulary.py`) is a strict subset of `EMPTY_FINDING_MARKERS`.
- Empty findings that are not negative-value markers, such as «отсутствуют» and «Не выявлено», are kept by the owner preflight as substantive values.

## An absence written as a value

- `ABSENCE_WRITTEN_AS_A_VALUE` holds phrases, stored casefolded, that report that nothing was found.
- `reads_as_an_absence` is true only when the whole value, trimmed of `_ABSENCE_TRIM` punctuation and casefolded, is an entry of `ABSENCE_WRITTEN_AS_A_VALUE`; a value merely containing one is not matched.
- `reads_as_an_absence` never treats a mapping, list, tuple or set as an absence.
- `refuse_absence_written_as_a_value` turns a `filled` cell whose value reads as an absence into `not_found` with `value`, `unit` and `value_origin` set to `None`.
- `refuse_absence_written_as_a_value` keeps the phrase as `if_not_why_not.refused_text` with `reason_kind: absence_reported_as_a_value` and `decided_by: policy`.
- `refuse_absence_written_as_a_value` leaves cells in any other status unchanged.

## Rule-excluded cells

- `_RULE_EXCLUSION` matches a rule named in a note as `rule '<name>'`, with the name in single, double or back quotes.
- `classify_rule_excluded_patches` moves a `not_found` patch whose `retrieval_note` names a rule declared in its own row's `negative_cases` (published by `semantic_hint` as `rules`) to `requires_expert_review`.
- `classify_rule_excluded_patches` leaves patches in other statuses, undeclared rules and rules declared on other rows unchanged.
- `classify_rule_excluded_patches` writes `if_not_why_not` with `reason_kind: excluded_by_rule`, the rule, `decided_by: policy`, `stated_reason` equal to `POLICY_EXCLUSION_NOTE_RU`, and the specialist's note as `specialist_note` through `bounded_text(max_chars=600)`.
- `classify_rule_excluded_patches` sets `retrieval_note` to `POLICY_EXCLUSION_NOTE_RU`, keeps existing locator keys, does not mutate its input, and returns one run note per reclassified cell.
- Template row 71 is a ГРР plan row whose `negative_cases` declare `historical_actual_is_not_plan`.

## Resource estimates from the web alone

- `LONE_SOURCE_REFUSED_FOR_RESOURCES` holds the source types (`web`) that cannot carry a resource estimate on their own.
- `LONE_WEB_RESOURCE_REASON_RU` is the `stated_reason` of a lone-web resource refusal when the patch has no retrieval note.

## Spatial rows without a layer

- `ABSENT_SPATIAL_LAYER_RULE` is the rule name on a filled spatial cell refused because the GIS project has no layer to measure it.
- `ABSENT_SPATIAL_LAYER_REASON_RU` is the `stated_reason` of that refusal when the patch has no retrieval note, and does not name the layer.
- `ABSENCE_TRACE_RU` holds the `selection_trace` sentence, formatted with `labels`, for each blocking absence code gis_service reports: `layer_not_found`, `layer_lacks_required_attribute` and `only_the_source_feature_in_layer`.
- `ABSENCE_TRACE_TAIL_RU` is the closing sentence every `ABSENCE_TRACE_RU` entry ends with.
- `UNNAMED_ABSENCE_NOTE_RU` is the run-note template for an absence code with no `ABSENCE_NOTE_RU` entry, and names the code.
- `ABSENCE_TRACE_RU` and `ABSENCE_NOTE_RU` hold no entry for `no_labelled_feature_in_layer`, which is not in `BLOCKING_ABSENCE_CODES` (`gis_service/arcgis_mcp/geotizer/infrastructure.py`) and is not reported by `unanswerable_field_keys`.
- `refuse_unanswerable_spatial_rows` keeps the status of a `not_found` cell, sets `source_locator.absence_code`, and appends `Роли: <labels>. <code_meaning_ru>` to the retrieval note from the unanswerable item.
- `refuse_unanswerable_spatial_rows` describes an absence code with no `ABSENCE_TRACE_RU` entry from the item's `code_meaning_ru`, and falls back to the `layer_not_found` sentence only when that is empty.

## Objects outside the row radius

- `OUT_OF_RADIUS_RULE` refuses a filled r084 or r085 value whose stated distance exceeds the row radius in `RADIUS_ROW_LIMITS_KM`.
- When the value states no distance, `refuse_out_of_radius_infrastructure` reads the distance from the retrieval note.
- `_DISTANCE_IN_VALUE` matches a distance or a range in км or km, and `_distances_km` reads a range at its nearer end.
- `note_distance_km` discards every stated distance equal to `limit_km` or present in `measured_km`, and returns the smallest remaining one.
- `refuse_out_of_radius_infrastructure` records where the distance was read (`value` or `retrieval_note`) as `stated_distance_read_from` on the refused candidate.
- The refusal's `stated_reason` is `OUT_OF_RADIUS_REASON_RU` filled with the stated distance and the row radius only, and never quotes the refused value.
- The refused value is kept on the candidate.
- When a measurement replaces the value, the measurement's `source_ref` is listed first in `source_refs`, and the refused document's refs are kept.
- `spatial_divergence` is the locator key `project_evidence/proposals.py` writes when a documentary value displaces a GIS measurement.
- `_note_with_displaced_measurement` (`proposals.py`) appends the measurement's unit to its value only when the value does not already contain that unit.

## Text in a numeric row

- `refuse_prose_in_numeric_rows` keeps the refused value on the patch and writes no `candidates`.
- `refuse_prose_in_numeric_rows` puts the refused text in `if_not_why_not.refused_text`, with `NON_NUMERIC_IN_NUMERIC_ROW_RU` as `stated_reason`.
- `refuse_prose_in_numeric_rows` also sets `retrieval_note` to `NON_NUMERIC_IN_NUMERIC_ROW_RU`.
- `states_no_quantity` (`services/geotizer/semantics.py`) takes any value containing a digit to carry a quantity.

## The wrong kind of answer

- `WRONG_KIND_RULES` maps each wrong-kind substitution to its rule name, and `element_for_mineral` and `mineral_for_element` share one rule.
- The three rules are recorded in GMM `operations/domain-review/2026-08-30__five-answers-from-the-domain-reviewer.md`.
- `_wrong_kind_for_the_row` refuses an element in a mineral row, or a mineral in an element row, only when the value names nothing of the other kind.
- `names_an_element` (`services/geotizer/semantics.py`) matches an element name only as a whole token, and an element symbol only as an exact case-sensitive token.
- `names_a_mineral` (`semantics.py`) recognises a mineral only by name from `_MINERAL_NAMES_RU`, and an unrecognised name is not a mineral.
- `is_a_work_year` (`semantics.py`) makes an absolute-age value refusable as a calendar year only when it is a bare year between 1900 and 2100.

## Readings, computations and units

- `a_reading_is_not_a_computation` relabels `calculated` to `direct` only on a `filled` patch whose locator cites `layer_id` or `source_layer_id`, states a figure with a unit (`unit_named_in_locator`), and carries no `operation`, `calculation_crs` or `confirmed_by_calculation`.
- `a_reading_is_not_a_computation` never changes the value or unit.
- A locator that names an operation without quoting a result stays `calculated`.
- `unit_named_in_locator` (`semantics.py`) returns only a unit attached to a number in a locator string, so a unit word in a layer name alone names no unit.
- `refuse_a_unit_the_source_contradicts` refuses a `filled` cell to `requires_expert_review` under `UNIT_CONTRADICTS_SOURCE_RULE`, keeping the value and unit in `candidates`.
- `refuse_a_unit_the_source_contradicts` fires only when the value's unit and the unit its locator states are both known, differ, and `states_a_conversion` is false.
- `states_a_conversion` (`semantics.py`) is true when the locator carries `operation` or `calculation_crs`, or the retrieval note contains a `CONVERSION_MARKERS` stem.

## Row 14: work stage

| Constant | Value |
| --- | --- |
| `WORK_STAGE_FIELD_KEYS` | The stage, start and end attributes of row 14 (`r014.a01`-`a03`). |
| `LICENCE_START_FIELD_KEY`, `LICENCE_END_FIELD_KEY` | The licence term's start (`r009.a01`) and end (`r010.a01`). |
| `LICENCE_CATEGORY_FIELD_KEY` | The licence category (`r011.a01`). |
| `LICENCE_PURPOSE_PREFIXES` | Prepositions that make a row-14 stage value read as a licence purpose clause. |
| `LICENCE_STATE_WORDS` | Licence-registry state words, none of which is a work stage. |

- `refuse_a_licence_record_in_the_work_stage_row` sends a row 14 cell to `EXPERT_REVIEW_STATUS`, keeping the refused value as a candidate, when the stage is a licence state word, equals the row 11 category ignoring punctuation, or starts with a licence purpose prefix.
- `refuse_a_licence_record_in_the_work_stage_row` does the same when the start or end date equals the r009 or r010 licence date from the envelope or `accepted_fields`.
- `_date_parts` lets the position of the four-digit year decide the order of month and day, and never sorts the numbers.
- `_same_date` compares dates as ordered year, month and day across separators, and returns False when a value has no single placeable four-digit year.
- `inject_row_declared_work_stage` sets `source_locator.work_stage` to `GRR_WORK_STAGE_BY_ROW[row_id]` on a `filled` patch of a GRR row that has no `work_stage`.
- `inject_row_declared_work_stage` keeps a work stage the owner supplied, even when it contradicts the row, and touches no other status or row.
- `inject_row_declared_work_stage` returns one run note counting the injected cells.

## Conflicts

- A `conflicted` cell keeps `value` null and records each competing value in `source_locator.candidates` with its unit, value origin, source ref and locator, beside the existing `candidate_locators`, `owner_locator` and `proposal_locator` keys (`project_evidence/proposals.py`).
- `resolve_by_source_authority` (`proposals.py`) ranks conflict candidates by the `source_type` of the registered source each `source_ref` names.
- `resolve_by_source_authority` picks a winner only when exactly one candidate is in `PRIMARY_SOURCE_TYPES` (`gis`, `knowledge_base`, `datacube`), at least one is in `WEB_SOURCE_TYPES` (`web`), and none is in neither set.
- `UNRECORDED_CONFLICT_TRACE` is the `selection_trace` of a conflicted cell whose owner recorded no candidates, naming its source refs.
- `record_unrecorded_conflicts` marks such a cell with `policy = owner_declared_conflict_without_candidates`.
- `ONE_SIDED_CONFLICT_TRACE` is the `selection_trace` of a conflicted cell in which fewer than two candidates state a value.
- `refuse_one_sided_conflicts` turns a `conflicted` patch whose candidates include only one stated value into `requires_expert_review` with `value` `None` and `source_locator.policy = conflict_without_two_stated_values`.
- `refuse_one_sided_conflicts` names the stated value in `selection_trace`, keeps every candidate and the owner's `retrieval_note`, and returns a run note.
- `refuse_one_sided_conflicts` leaves a conflict with two stated values, and a conflict with no candidates, unchanged.
- `_FIELD_KEY_ROW` extracts the three-digit row number from a whole field key `geotizer_object.v<N>.r<NNN>.a<NN>`.

## Searches outside a knowledge-base collection

- `INVALID_SCOPE_REASON_RU` is the retrieval note `flag_invalid_scope_conclusions` writes on a cell whose search never opened a knowledge-base collection.
- `INVALID_SCOPE_TRACE` is the `selection_trace` of a `not_found` cell whose search named a scope that is not a knowledge-base collection.
- A locator carrying a `GIS_LOCATOR_KEYS` key with a non-empty value, or a string containing a `GIS_PROSE_MARKERS` marker, reports a GIS source.
- `flag_invalid_scope_conclusions` leaves a `not_found` unchanged when `names_a_gis_source` recognises its locator.
- `build_knowledge_search_plan` (`project_evidence/proposals.py`) lists the GIS project id in `corpus_scope.not_a_corpus` on every plan, as an instruction not to search it, and not as a record that it was searched.

## Plan deadlines beyond the licence term

- `PLAN_DEADLINE_FIELD_KEYS` holds the plan deadline cells: `a05` of rows 68-72 and `a02` of rows 73-76.
- `_YEAR` matches a four-digit year from 1900 to 2199 not adjacent to other digits.
- `flag_plan_beyond_licence_term` examines only `PLAN_DEADLINE_FIELD_KEYS` and compares years only.
- `flag_plan_beyond_licence_term` compares against the licence end in `LICENCE_END_FIELD_KEY`, read from `accepted_fields` or the same envelope, and judges nothing without it.
- A deadline whose year is later than the licence end year keeps its value and status, gains `source_locator.policy = plan_deadline_beyond_licence_term`, and produces a run note naming the licence end date.

## Model contradictions

- `MODEL_ENTAILED_PHENOMENA` states that the porphyry model stated in rows 16, 18, 19 or 27 entails the alteration row 26.
- The entry's `model_pattern` matches the stem «порфир» only at a word start.
- `flag_model_contradictions` flags a phenomenon row only when every cell of it is `not_found` or `not_applicable` and a filled model row matches the entry's `model_pattern`.
- `flag_model_contradictions` moves flagged cells to `requires_expert_review` with no value.

## GIS retrieval expansion

- `gis_retrieval_expansion` returns one entry per absence code found among the non-accepted GIS trace entries or on the cells, with the `semantic_roles` that carried it and the cells whose `source_locator.absence_code` matches it.
- `gis_retrieval_expansion` splits those cells into `blocked_field_keys`, `searched_elsewhere_field_keys` and `answered_elsewhere_field_keys` (searched cells that are `filled`).
- `_EXPANSION_MARKERS` (`web_search`, `web:`, `http://`, `https://`) holds the substrings that mark a cell as searched outside the project when its case-folded serialised locator contains one.
- A knowledge-base locator without such a substring does not count as searched elsewhere, and a cell with no mapping locator is skipped.
