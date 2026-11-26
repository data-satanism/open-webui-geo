# GeoMAS ontology

`backend/open_webui/services/ontology/geomas.py` loads a copy of two GMM ontology packages and uses them at three points: the GeoTeaser fill's search queries, admission of filled values, and chat retrieval.
All three are on unless `ENABLE_GEOMAS_ONTOLOGY` is `false`.
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
| `ENABLE_GEOMAS_ONTOLOGY` | `True` | `backend/open_webui/config.py`, at import |

Only `false`, in any casing, turns the switch off; unset or any other value leaves it on.
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
| `enum` with a codelist | The value, stripped of surrounding whitespace, punctuation, dashes and quotes (`_ABSENCE_TRIM`) and casefolded, is none of the codelist's labels | `ontology_codelist` |

A refused patch moves to `requires_expert_review` with its value kept, and gets `source_locator.if_not_why_not` with `reason_kind: 'excluded_by_rule'`, the rule, `decided_by: 'policy'`, a Russian `stated_reason` naming `geoteaser` 1.0.0 and the value type, and the value in `refused_text`.
The step adds one run note per rule.
All 29 interval fields are work periods (rows 29 to 32) or plan deadlines (rows 68 to 76), so a deadline stated as a duration with no year goes to expert review.

### Chat retrieval

`expand_queries` keeps every query in its order and appends one widened query for each query that names an ontology concept.

- A query reaches an entity when a label or synonym occurs in it as whole tokens, or a label or synonym holds a code the query holds; the concept-group head of a reached entity is reached too.
- Tokens are NFKC, casefolded, «ё» as «е», dashes as spaces, Latin lookalikes in mixed-script words as Cyrillic, codes folded to Latin, and one Russian ending stripped. The linker is GMM `scripts/validate_question_linking_cases.py` at `7886511`, ported; it does not use `retrieval/lexical.py`.
- The entities reached, plus those joined to them by a `same` relation in either direction, supply the added terms: their labels and synonyms whose tokens are not all in the query already, by `priority` then id, without repeats, at most 12.
- The widened query is the original, a space, and the added terms joined by spaces.
- A `query_collection` call that widens any query logs one info line from `open_webui.services.ontology.geomas`: `GeoMAS ontology (geomas-core 1.2.0, geoteaser 1.0.0) expanded queries: <n>, adding <terms>`, with the added terms of each widened query and without the queries' text.
- Each widened query is one more embedding and vector search in `query_collection`, per collection, and its results go through the same merge to the top `k` as the originals.
- With the switch on, every `query_collection` call on every knowledge base is expanded, so a call embeds and searches at most twice as many queries as it was given.
- When the assets fail to load for any reason, `expand_queries` logs the error and returns the queries unchanged, so chat retrieval runs unexpanded; the GeoTeaser fill raises the load error instead.
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

How much a fill varies from run to run on this instance is not known; the two runs per arm measure it.
Results are compared only within this instance.
The old and the new Geomas can be compared once the ontology module lands in the new Geomas and a fill runs from its UI on the same data.

1. Deploy the branch on the instance as the instance is built. Check that gis_service runs as before and that `ENABLE_GEOMAS_RAG_V2` keeps its setting; both arms use that setting.
2. Arm A: set `ENABLE_GEOMAS_ONTOLOGY=false` and restart. In a new chat with the GeoTeaser model, attach Лекын's knowledge and send the usual fill request, with the usual model, knowledge, message and run mode. Download the card and `/geotizer/files/<run_id>/run_log.json`, and note the run id.
3. Arm B: leave `ENABLE_GEOMAS_ONTOLOGY` unset or set it to `true`, and restart. Repeat step 2 in a new chat with everything else the same.
4. Run A and B once more each, in that order, for runs A1, B1, A2 and B2. Keep the instance's logs of B1 and B2: they hold the expansion lines.
5. Check each run's arm: `run_log.json` has no `ontology` key in A, and names `geomas-core` 1.2.0 and `geoteaser` 1.0.0 in B.
6. Judge the ontology cell by cell, with the four cards side by side, one column per run:
   - Noisy cells: a cell whose value or status differs between A1 and A2, or between B1 and B2, varies on its own, and a difference on it says nothing about the ontology.
   - Candidate effects: a cell that agrees within A and within B but differs between them. For each, read its source in B and name the hook that reached it.
   - Admission: every B cell in expert review with rule `ontology_value_type` or `ontology_codelist` is the ontology's, and the same value is refused every time. For each, decide whether the value is outside the field's type, and count the right and the wrong refusals.
   - Search queries: the KB queries in B's `retrieval_queries` that hold one of a field's `ontology.terms`. A candidate cell whose source in B only such a query cited is the search hook's effect.
   - Chat retrieval: the expansion lines in the B logs, with the terms added and how often. A candidate cell whose source no A run cited, and that no ontology term reached through the KB queries, may come from a widened query.
   - Totals: completeness and the counts of filled and expert-review cells, for the record only. The noisy cells show how far a total moves without the ontology, and two runs per arm cannot tell a gap smaller than that from noise.
7. Optionally, for chat retrieval alone, ask the same few questions about Лекын in a plain chat with its knowledge attached in each arm, and compare the cited sources. The expansion lines carry only the added terms and their count, so match each line to its question by the time of the request.
8. Leave the instance on the default, `ENABLE_GEOMAS_ONTOLOGY` unset, which keeps the ontology on; set it to `false` and restart to turn it off.
