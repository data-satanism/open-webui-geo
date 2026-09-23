# Validation rules

`backend/open_webui/services/artifacts/geotizer/validation.py` holds this repository's copies of the GIS service's owner-envelope rules and a few local rules.
`validate_owner_envelope` returns the violations that become the owner's repair feedback.

## Entry points and helpers

- `validate_owner_envelope` and `owner_submission` are entry points, and `_with_exit` is a message helper; none of the three is a rule copy.
- `_subarea_patch_violations` (with `_normalized_site_name` and `_names_the_whole_area`) and `_resource_unit_violations` are local rules with no counterpart in gis_service's validator.

## Parity corpus

- `backend/tests/test_geotizer_validation_parity.py` runs every case of `assets/geotizer-validation-parity.v1.json` (22 cases) against this module and requires the GIS service's `valid` verdict.
- Parity compares only the `valid` verdict, and the service's violation codes are recorded for diagnosis.
- The corpus covers five rule functions (`_contract_violations`, `_partition_violations`, `_patch_violations`, `_source_inventory`, `_value_origin_violations`), all through `KB-LIC-LEGAL` cases.
- The rules that apply only to resource, plan or assemble batches have no corpus case.
- The corpus is pinned to `policy_version` `geotizer_assignments.v3` and carries no retired producer name.

## Envelope structure

- `_partition_violations` refuses an envelope whose patch count differs from the batch's field count.
- `_source_inventory` returns the set of non-blank `source_id`s and a list of violations.
- `_source_inventory` reports an inventory that is not an array, an entry that is not an object, an entry without a non-blank `source_id`, and an entry missing `source_type` or `title` (named with the entry's id).
- `validate_owner_envelope` therefore rejects an envelope whose `source_inventory` has an entry missing `source_type` or `title`.
- `_patch_violations` requires `value` to be null for status `not_found`, `not_applicable`, `conflicted` or `agent_contract_failed`.
- `_patch_violations` requires a `source_locator` only on `filled` patches.
- `_value_origin_violations` refuses any non-`filled` patch whose `value_origin` is not null.
- `locator_source_refs` feeds `_locator_ref_violations`, which checks every returned ref against the envelope's `source_inventory`.

## Semantic rules

- `_semantic_patch_violations` parses `source_locator` with `core.text.locator_map`, so a locator given as a `key=value; …` string is read as a mapping.
- Semantic rules therefore read qualifiers such as `work_stage` from a string locator.
- Each semantic violation carries the field key after its position, as `patches[i] <field_key>`.
- A missing qualifier is named by its `source_locator.<key>` path.
- Resource and GRR rejections quote the value that would satisfy the rule (allowed estimate states, required entity scope, required analogue relation, required work stage) beside the value sent, and report a qualifier that was not sent as `(unset)`.
- `semantic_hint` and `validate_owner_envelope` read the same row tables (`RESOURCE_ENTITY_SCOPE_BY_ROW`, `RESOURCE_ESTIMATE_STATES_BY_ROW`, `ANALOGUE_RELATION_BY_ROW`, `GRR_WORK_STAGE_BY_ROW`), so the prompt and the rejection state one contract.

## Unsatisfiable rows

- `NO_VALUE_SATISFIES_EXIT_RU` is the one sentence, formatted with a `{condition}`, that `_with_exit` appends to a refusal of a row no value may satisfy.
- The sentence tells the owner to return `status: not_applicable` with a reason.
- The `NO_*_RU` constants (`NO_NAMED_SUBAREAS_RU`, `NO_ESTIMATE_IN_STATE_RU`, `NO_ANALOGUE_RU`, `NO_WORK_AT_STAGE_RU`, `NO_ENTITY_AT_SCOPE_RU`, `NO_ESTIMATE_TO_IDENTIFY_RU`) are the conditions it names.
- The top-level functions of `validation.py` hold 34 refusal messages (`patches[{index}]`).
- Ten of them go through `_with_exit`: two subarea messages, `site_name`, three resource identity messages (`entity_id`, `entity_scope`, `resource_estimate_id`), `estimate_state`, two analogue messages and `work_stage`.
- The other refusal messages carry no exit.

## Resource rows

- `resource_row_identity_conflicts` returns `{row: {qualifier: [values]}}` over the per-row qualifiers in `ESTIMATE_ROW_IDENTITY_QUALIFIERS` (`services/geotizer/semantics.py`), which include `site_name` for row 50 and exclude `source_document_id` for row 55.
- `resource_row_identity_conflicts` is the data half of `_resource_row_consistency_violations`, which turns its result into violations.
- `owner_envelope.refuse_incoherent_resource_rows` reads the result of `resource_row_identity_conflicts` to mark a row for expert review.
- `_resource_unit_violations` refuses a unit only when the unit is recognised and belongs to another dimension.
- `semantics.RESOURCE_UNITS_BY_FAMILY` is not exhaustive, and an unlisted unit is never refused.
- `RESOURCE_UNIT_FAMILIES` (`semantics.py`) inverts `RESOURCE_UNITS_BY_FAMILY` and requires that no unit is listed under two families.

## Named subareas

- `NAMED_SUBAREA_ROWS` are rows 50-53, the template's named subareas of the licence area, «Участок 1» to «Участок 4».
- `AREA_SCOPE_WORDS` holds words that mark a site name as naming the whole licensed area.
- `_SUBAREA_ORDINAL`: a digit in a site name marks it as a numbered subarea, which `_names_the_whole_area` never treats as the whole area.
- `_subarea_patch_violations` applies to `filled` patches on `NAMED_SUBAREA_ROWS` and reports one violation per cell.
- A value repeating the row's own site name takes precedence over a site name that names the object.
- The self-naming check runs without any object name.
- The object-name check is skipped when `object_name` is empty.
- The object-name check refuses a `site_name` equal to the object name ignoring case and separators, and names the value in the violation.
- An absent `site_name` on rows 50-53 is refused once by `_resource_patch_violations`, not by `_subarea_patch_violations`.

## Plan rows

- `_plan_patch_violations` names in its GRR work-stage refusal the stage `GRR_WORK_STAGE_BY_ROW` requires for the row.
- `_plan_patch_violations` refuses `temporal_role` `historical_actual`, the structured signal of a historical value.
- `_note_dates_itself_before_the_plan` reads the prose note, and is true when the case-folded note contains `historical` or `историческ` (`_HISTORICAL_WORDS`, matched as substrings) or a whole-token year from 1900 to 2019 (`_PLAN_NOTE_PAST_YEAR`).
- `_plan_patch_violations` applies the note rule only to a `direct` patch on a plan row (68-76).
