# Dossier projection and project evidence

`backend/open_webui/services/artifacts/geotizer/project.py` projects a project-evidence dossier onto the GeoTeaser template fields.
`backend/open_webui/services/project_evidence/` holds the dossier contract, claims, GIS proposals and retrieval traces the artefacts share.
`backend/open_webui/services/evaluation/rag_ab.py` evaluates RAG shadow records.

## Dossier contract

- `DOSSIER_REQUIRED`, `ITEM_REQUIRED`, `NESTED_REQUIRED` and `PROJECT_SCOPE_REQUIRED` (`project_evidence/dossier.py`) each equal the `required` list of the matching definition in `GMM/contracts/evidence/project-evidence-dossier.schema.json`, which owns the dossier contract.
- A dossier conflict requires `claim_ids`, `conflict_id`, `kind`, `resolution` and `statement` (`CONFLICT_REQUIRED` in `project_evidence/dossier.py`).
- The dossier precondition checks that fields are present, not that their values are in the schema's vocabularies.
- `require_projectable` (`project_evidence/dossier.py`) is applied by both `artifacts/cpr/project.py` and `artifacts/geotizer/project.py`.
- Both `build_projection` functions raise `DossierNotProjectable` before reading the dossier whenever `projection_preconditions` reports a reason.

## Field projection

- `build_projection` projects all 351 template fields, addresses claims by id only, and carries no value, unit, quoted text or narrative.
- A scalar claim fills only the facet its predicate is registered for.
- A claim whose value is a mapping fills the facets it names.
- `NO_FACET_VALUE` is a sentinel distinct from `None`: `None` means the claim holds a null for the facet, and `NO_FACET_VALUE` means it holds nothing for it.
- `facet_value` treats a mapping value that does not name the field's facet as saying nothing about that cell, even for an `also_accepts` predicate.
- A `stale` claim fills nothing.
- An analogy claim never fills a field that forbids analogy, such as row 8 (licence number).
- Template row 14's three facets `stage`, `start_date` and `end_date` share the predicate `project_stage`.
- `_field_row` marks a row `corroborated` only when more than one claim has `resolution_outcome == 'corroborated'` and `claims_agree_on_a_value` holds for them.
- For a supported `artifact_specific_calculated` or `artifact_specific_advisory` field, `_field_row` sets `returned_claim_id` to the first sorted supporting claim id.
- `_field_row` makes a `not_applicable` row expert-approved only when every gap on the row is approved, the same rule as `cpr/coverage.py::_is_expert_approved`.
- For scope `complete`, `semantic_completeness_percent` is `round(100 * answered / (351 - expert-approved not_applicable), 2)`, where answered cells are `supported` or `corroborated`.
- A `reference_slice` projection omits `semantic_completeness_percent`.
- `load_mapping` raises `GeotizerOrchestrationError` naming the digest when the mapping file differs from its recorded digest.
- `projection_trace` carries `dossier_run_id`, `projection_version` (`cpr_to_geotizer.v1`), `frozen_inputs_hash`, `filled_fields`, and one entry with claim ids for each `supported`, `corroborated` or `conflicted` cell.

## Claims and gaps

- `reviewed_gaps` (`project_evidence/claims.py`) returns every gap covering the predicates, sorted by `gap_id`, whatever the dossier order.
- `resolve_gap_state` resolves overlapping gaps with different states to `('blocked_expert', True)` in any order.
- `scripts/export_geotizer_owner_batches.py` places every dossier conflict in a projection cell or lists it in `conflicts_no_field_can_show`, never both.

## GIS field proposals

- `normalize_gis_field_proposals_with_rejections` (`project_evidence/proposals.py`) returns the accepted proposals and one `{field_key, reason}` record per refused proposal, with `reason` from `GIS_PROPOSAL_REJECTIONS`.
- The reason `not_this_batch` marks a key outside `allowed_field_keys`, and every other reason marks an asked-for key whose proposal is unusable.
- `normalize_gis_field_proposals` returns only the accepted proposals, as a tuple.

## Retrieval traces

- `build_grounded_retrieval_trace` (`project_evidence/retrieval.py`) counts the difference between the number of documents and metadata rows as `rejected['malformed_backend_result']`.
- With no hits, `build_grounded_retrieval_trace` sets `failure_type` by the first match of: a terminal backend failure (`retrieval_failed`), an unsafe context (`unsafe_context`), an unresolved-lineage or strict-filter rejection (`insufficient_context`), a malformed backend result (`retrieval_failed`), and otherwise `no_retrieval_hit`.

## RAG A/B evaluation

- `rag_ab.SHADOW_RECORD_SCHEMA` is a copy of `SHADOW_RECORD_SCHEMA` in `open_webui/utils/geotizer_rag_runtime.py` and must stay equal to it.
- `rag_ab.LIVE_CLAIM_STATES` is a separate copy equal to `claims.LIVE_CLAIM_STATES`, not an import.
- `rag_ab._is_web_sourced` treats a claim as web-sourced when a token of a referenced source's lower-cased `source_type`, split on non-alphanumeric characters, is in `WEB_SOURCE_MARKERS`.
- `rag_ab._is_web_sourced` does not recognise a web source whose `source_type` carries no marker token.
