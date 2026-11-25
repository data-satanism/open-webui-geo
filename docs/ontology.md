# GeoMAS ontology

`backend/open_webui/services/ontology/geomas.py` loads a copy of two GMM ontology packages and uses them at three points: the GeoTeaser fill's search queries, admission of filled values, and chat retrieval.
All three are off unless `ENABLE_GEOMAS_ONTOLOGY` is `true`.
Nothing reads GMM, a registry or a database at run time.

## What is copied

| Package | Version | Kind | Files | Manifest sha256 |
| --- | --- | --- | --- | --- |
| `geomas-core` | 1.2.0 | ontology | 18 | `da6162bbbe9aa45f33bdeed75fbbe2be69134dd821b17afe117fc02bfbc8833c` |
| `geoteaser` | 1.0.0 | template | 6 | `8316fdbe318d72d64dcd3b1ad07f737e08d6a0e5723b478b7f9ac23a54a536d5` |

- Source: `data-satanism/GMM`, branch `feat/ontology-module`, commit `7886511d0e18b13285e2f8691245ad41024eee96`, path `contracts/ontology/packages/<id>/<version>/`.
- The packages were built from `ontology-mindmap.html`, sha256 `6a5dd06a73478b8920b406c2f2a2f5fa4e79e573ad8a35dd17f4acf162254df0`, which no repository holds.
- The copies sit byte for byte under `backend/open_webui/services/ontology/assets/<id>/<version>/`, each with its `manifest.json`.
- `assets/provenance.json` records the source, the mind map digest, each package's id, version and manifest digest, and its record counts.
- GMM's `question-linking-cases.v0.2.json` is copied byte for byte to `backend/tests/fixtures/geomas_ontology/` as a test fixture.
- Not copied: `geomas-core` 1.0.0 and 1.1.0, `gmm-core-profile` and `geomas-core__gmm-core-profile`.

### Record counts

| Package | Counts |
| --- | --- |
| `geomas-core` 1.2.0 | 12 classes, 161 attributes, 864 entities (23 with synonyms, 74 in concept groups), 8 relation kinds, 469 relations, 8 qualifiers, 16 notes, 9 codelists, 11 retrieval intents |
| `geoteaser` 1.0.0 | 108 rows, 351 fields, 218 dependencies, 4 source roles, 24 notes, 438 field-attribute links; field value types: 164 text, 93 number, 35 identifier, 29 interval, 23 date, 6 enum, 1 records |

### Loading

`_load` runs once per process and caches its result.
It raises `GeotizerOrchestrationError` naming the file when any of these differs from `provenance.json`:

- the sha256 of a package's `manifest.json`;
- the id or version inside a manifest;
- the sha256 of a file against its manifest;
- a record count.

## The switch

| Variable | Default | Read in |
| --- | --- | --- |
| `ENABLE_GEOMAS_ONTOLOGY` | `False` | `backend/open_webui/config.py`, at import |

A change takes effect after a restart.
With the switch off, the fill's prompts, plans, admission and run log, and every chat retrieval query, are what they were before the module existed.

## The hooks

| Hook | Where | What it does with the switch on |
| --- | --- | --- |
| Search queries | `run_geotizer_workflow(ontology=...)` in `services/artifacts/geotizer/workflow.py`; `fill_geotizer` and the area fill's `member_filler` pass `ENABLE_GEOMAS_ONTOLOGY` (`tools/geotizer.py`) | Each batch taken from `state['next_batch']` passes through `annotate_batch` before anything reads it. |
| Admission | `refuse_values_the_ontology_rules_out` in `services/artifacts/geotizer/owner_envelope.py` | Sends a filled value that does not fit its field's type to expert review. |
| Chat retrieval | `query_collection` in `backend/open_webui/retrieval/utils.py`, one `GEOTIZER-SEAM` line | Passes the queries through `expand_queries`. |

### Field annotation

`annotate_batch` gives each batch field whose `field_key` is in `geoteaser` one key, `ontology`:

| Key | Value |
| --- | --- |
| `terms` | Labels and synonyms of the entities the field's row names in `rows.json` `entities`: first those carrying one of the field's attributes, then the others, each group by `priority` then id; no casefolded repeats; at most 12 |
| `value_type` | The field's `value_type` |
| `codelist` | The labels of the codelist of the field's enum attribute, or `None` |

- The 12 rows that name no entity give an empty `terms` list; 30 of the 351 fields get no terms, the median is 4, and 48 fields reach 12.
- Every contributor payload carries the annotated fields in `bounded_fields`.
- The KB specialist's rules gain one rule when any bounded field carries `ontology`: use `ontology.terms` as further search terms for that field; they widen a search and are never evidence.
- The web and GIS specialists get no rule.
- With `ENABLE_GEOMAS_RAG_V2` on, `_field_terms` in `services/project_evidence/retrieval.py` adds `ontology.terms`, so `build_retrieval_plans` puts them in `should_terms`.

### Admission

`refuse_values_the_ontology_rules_out` runs right after `refuse_the_wrong_kind_of_answer`, on the attempt path and on the salvage path of `_produce_valid_owner_envelope`.
It acts only on a `filled` patch whose field carries `ontology`.

| Field `value_type` | Refused when | Rule |
| --- | --- | --- |
| `number` | `states_no_quantity(value)` is true | `ontology_value_type` |
| `date`, `interval` | The value holds no year from 1800 to 2100 and no `d.m.y` or `d/m/y` date | `ontology_value_type` |
| `enum` with a codelist | The value, stripped and casefolded, is none of the codelist's labels | `ontology_codelist` |

A refused patch moves to `requires_expert_review` with its value kept, and gets `source_locator.if_not_why_not` with `reason_kind: 'excluded_by_rule'`, the rule, `decided_by: 'policy'`, a Russian `stated_reason` naming `geoteaser` 1.0.0 and the value type, and the value in `refused_text`.
The step adds one run note per rule.
All 29 interval fields are work periods (rows 29 to 32) or plan deadlines (rows 68 to 76), so a deadline stated as a duration with no year goes to expert review.

### Chat retrieval

`expand_queries` keeps every query in its order and appends one widened query for each query that names an ontology concept.

- A query reaches an entity when a label or synonym occurs in it as whole tokens, or a label or synonym holds a code the query holds; the concept-group head of a reached entity is reached too.
- Tokens are NFKC, casefolded, «ё» as «е», dashes as spaces, Latin lookalikes in mixed-script words as Cyrillic, codes folded to Latin, and one Russian ending stripped. The linker is GMM `scripts/validate_question_linking_cases.py` at `7886511`, ported; it does not use `retrieval/lexical.py`.
- The entities reached, plus those joined to them by a `same` relation in either direction, supply the added terms: their labels and synonyms whose tokens are not all in the query already, by `priority` then id, without repeats, at most 12.
- The widened query is the original, a space, and the added terms joined by spaces.
- The added terms are logged at debug level by `open_webui.services.ontology.geomas`.
- Each widened query is one more embedding and vector search in `query_collection`.
- When the assets fail verification or cannot be read, `expand_queries` logs the error and returns the queries unchanged, so chat retrieval runs unexpanded; the GeoTeaser fill raises `GeotizerOrchestrationError` instead.
- `query_collection` is also reached by `query_knowledge_files`, `tools/geotizer_retrieval.py` and the retrieval router's query endpoint, so the KB specialist's searches during a fill are widened too.

| Query | Reaches | Widened query adds |
| --- | --- | --- |
| «запасы C2 по Лекыну» | `D05`, `core-profile:ResourceEstimate` | `Прогнозные ресурсы`, `ресурсы p1 p2 p3`, `Оценка ресурсов`, `запасы А В С1 С2` |
| «Магнитометрия на участке» | `GP-013`, `GP-071`, `semantic-layer-roles:magnetic_survey` | `Магниторазведка`, `Магнитные данные` |
| «Какая стадия работ?» | nothing | nothing |

### The run record

With `ontology` true, `run_log` carries `ontology` next to `build_revision`: the package ids, versions and manifest digests, the GMM repository and commit, and the mind map's sha256.
With it false the entry is absent, and `run_log.json` has no `ontology` key.

## What the hooks do not use

The hooks read entities, their labels, synonyms, concept groups, attributes and priorities, `same` relations, codelists, and the template's rows and fields.
They do not use relations of any other kind, `geoteaser` dependencies, source roles (`accepts`), qualifiers, retrieval intents or notes.

## By-hand A/B for Лекын

1. Deploy with `ENABLE_GEOMAS_ONTOLOGY` unset or `false`, and note the `ENABLE_GEOMAS_RAG_V2` setting.
2. Arm A: open a new chat with the GeoTeaser model, attach Лекын's knowledge, and send the usual fill request.
3. Download the card and `run_log.json` from `/geotizer/files/<run_id>/run_log.json`, and note the run id.
4. Arm B: set `ENABLE_GEOMAS_ONTOLOGY=true`, restart, and repeat steps 2 and 3 with everything else the same.
5. Run each arm twice in the order A, B, A, B, since a fill varies from run to run.
6. Compare, per run:
   - `run_log.json` `ontology`: absent in A, naming `geomas-core` 1.2.0 and `geoteaser` 1.0.0 in B;
   - `run_log.json` `retrieval_queries`;
   - on the card: completeness, cells filled, cells in expert review, cells whose value or source changed, and cells refused with `ontology_value_type` or `ontology_codelist`.
7. Optionally, ask the same few plain-chat questions in each arm.
8. Set `ENABLE_GEOMAS_ONTOLOGY` back to `false` and restart.
