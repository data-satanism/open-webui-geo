# Ontology vocabulary induction

`induce_ontology_vocabulary` in `backend/open_webui/tools/ontology_induction.py` reads stored chunks of the documents in the knowledge collections attached to a chat message. It lists the terms they use against the GMM ontology induction seed, with the excerpt each term came from. The result is a proposal for the Domain Reviewer and the Ontology Approver; nothing applies it to any contract.

The built-in is reached through a generated Workspace Tool shim. The deterministic core is `backend/open_webui/services/ontology_induction/` and imports no `open_webui`.

## What a run reads

| Input | Source |
| --- | --- |
| Scope | `utils/kb_collection_scope.resolve_kb_scope(__files__)`: the `__files__` entries with `type: collection` |
| Access | `retrieval/utils.filter_accessible_collections(collection_ids, user, 'read')` for the user `Users.get_user_by_id(__user__['id'])`; an admin passes every collection name it accepts |
| Files of a collection | `Knowledges.get_file_metadatas_by_id`; `File.data` is never read |
| Chunks of a file | `ASYNC_VECTOR_DB_CLIENT.query(collection_name=<collection id>, filter={'file_id': <file id>})` |
| Seed and proposal schema | `services/ontology_induction/assets/`, byte-identical copies of GMM `contracts/ontology/ontology-induction-seed.v0.1.json` and `ontology-induction-proposal.schema.json` at `e20d6dd3f40f0ca205cc97759dcf0c6737283141` (the merge of `data-satanism/GMM#49`) |
| Normaliser | `retrieval/lexical.normalize_geological_text` |

`assets/provenance.json` records each asset's `sha256`, `bytes`, `source_repository`, `source_path` and `source_commit`. Every run verifies both digests and byte counts, plus the seed's `seed_id` and term count, before anything else. A mismatch refuses the run with `pinned_asset_mismatch`, naming the file.

## Order of a run

1. Parameters are checked; an invalid one refuses with `invalid_parameter`.
2. The pinned assets are verified.
3. Any `__files__` entry that is not a collection refuses with `unsupported_attachment`.
4. No attached collection refuses with `kb_scope_unconfigured`, carrying `kb_scope_status: unconfigured`.
5. Any attached collection the user may not read refuses the whole run with `collection_not_accessible`, naming it.
6. With `resume_file_id`, the previous proposal is loaded (see [Resume](#resume)).
7. Documents are listed per collection in attach order. Within a collection they are ordered by name, then file id. A file in two collections is read from the first.
8. The proposal, the Markdown and the checkpoint are written once before any document is processed.
9. Documents are processed in turn, `pending` ones first, then `no_stored_chunks` and `failed` ones kept from a resumed run, up to `MAX_DOCUMENTS`. Each document emits one status event, and all three files are overwritten after it.

No model call is made before step 9. A refusal in steps 1 to 6 writes no file.

## Per document

| Step | Rule |
| --- | --- |
| Read | All stored chunks of the file. A chunk without a string id or string text is skipped. |
| Sample | Chunks of at least `MIN_CHUNK_CHARS` characters; the `CHUNKS_PER_DOCUMENT` whose text has the smallest SHA-256, ties to the smaller chunk id; sent in order of evidence page, then `start_index`, then chunk id. |
| Call | One `generate_chat_completion` call per sampled chunk, bounded by `asyncio.wait_for(MODEL_TIMEOUT_SECONDS)`. |
| Guard | Each reply item passes guards (a), (b), (c) in order or is dropped and counted. |

### The call

| Key | Value |
| --- | --- |
| `bypass_system_prompt` | `True` |
| `messages` | a system message (the induction prompt, a blank line, `SEED TERMS (one JSON object per line):`, the seed block), then a user message holding the chunk text |
| `temperature` | `0` |
| `response_format` | `{"type": "json_schema", "json_schema": {"name": "ontology_induction_items", "schema": REPLY_SCHEMA}}` |
| `chat_template_kwargs` | `{"enable_thinking": false}`, plus `enable_thinking: false` |
| `stream` | `False` |

The seed block lists the `class`, `layer_role`, `entity_scope` and `semantic_family` terms of the seed in seed order, one compact JSON object per line with `term_id`, `label`, `labels_ru` and `description` where present. Field, relation and attribute terms are not sent. The block is built once per run, and the system message is byte-identical for every call of a run.

`REPLY_SCHEMA` in `services/ontology_induction/reply.py` is `{"items": [{"surface_form", "excerpt", "proposed_kind", "proposed_class"?, "suggested_seed_term_id"?}]}`, every string non-empty, `proposed_kind` one of the seed's kinds. No key outside it is allowed.

The default prompt is `DEFAULT_INDUCTION_PROMPT` in `services/ontology_induction/seed.py`. A non-empty `INDUCTION_PROMPT` replaces it. `parameters.prompt_sha256` is the SHA-256 of the prompt used, without the seed block.

### Reply outcomes

A reply is never repaired and never retried.

| Outcome | Counts | When |
| --- | --- | --- |
| `empty_completion` | calls | No choice, or message content empty or absent; this includes a reply carrying only reasoning |
| `unparseable` | calls | Content is not JSON; a fenced JSON block is not JSON |
| `schema_violation` | calls | JSON that does not match `REPLY_SCHEMA`; every item of the call is dropped |
| `timeout` | calls | The call raised `asyncio.TimeoutError` |
| `excerpt_not_in_chunk` | items | Guard (a): the excerpt does not occur in the chunk after runs of whitespace are collapsed to one space |
| `term_not_in_excerpt` | items | Guard (b): the normalised surface form is empty or not a contiguous run of whole tokens of the normalised excerpt |
| `unknown_seed_term` | items | Guard (c): `suggested_seed_term_id` is not a seed term, or `proposed_class` is not a seed `class` term |
| `accepted` | items | The item passed (a), (b) and (c) |

The four item outcomes count items, and the four call outcomes count calls, so a document's outcomes do not sum to its calls. GMM `architecture/ontology/vocabulary-induction.md` describes `outcomes` as counting model calls only.

`empty_completion` does not distinguish a reasoning-only reply from a reply with no content at all. `timeout` does not distinguish `MODEL_TIMEOUT_SECONDS` running out from an upstream HTTP timeout raised as `asyncio.TimeoutError`.

### Document statuses

| Status | When | `chunks_sampled`, `outcomes` |
| --- | --- | --- |
| `pending` | Not processed yet: beyond `MAX_DOCUMENTS`, or the run stopped first | absent |
| `complete` | Every sampled chunk had a call that ended in an outcome | present |
| `no_stored_chunks` | The vector store returned no usable chunk for the file | `0`, all zero |
| `failed` | The chunk query raised, a model call raised an error other than a timeout, or the completion was an API error | `chunks_sampled` is the number sampled; `outcomes` cover the calls before the failure |

`no_stored_chunks` does not distinguish a file that was never indexed (including every file under `BYPASS_EMBEDDING_AND_RETRIEVAL`) from a missing collection or a backend that returns no result on an error, as Chroma's `query` does. A `complete` document may have `chunks_sampled: 0` when no chunk reaches `MIN_CHUNK_CHARS`.

Items of a `failed` or `pending` document are not in the proposal. A run's result lists each failed document with one code, and the full error is logged at `WARNING`:

| Code | Cause |
| --- | --- |
| `chunk_query_failed:<exception type>` | The vector-store query raised |
| `model_call_failed:<exception type>` | `generate_chat_completion` raised an error other than a timeout |
| `api_error` | The completion is a mapping carrying `error` |
| `api_error_status_<n>` | The completion is a response object with status `<n>` |
| `unexpected_response_<type>` | The completion is neither |

No upstream error text reaches the result.

## Evidence locator

Every evidence entry carries `file_id`, `chunk_id`, `excerpt` (as the model quoted it) and `excerpt_sha256` (SHA-256 of the excerpt in UTF-8). The optional keys are copied from the chunk metadata only when they meet their rule; otherwise they are absent.

| Key | Rule |
| --- | --- |
| `page` | `page_label` that is a positive integer, or a string of ASCII digits naming one; never `page` or `source_page_index` |
| `start_index` | an integer ≥ 0 |
| `document_id`, `document_version`, `section_path`, `child_chunk_id` | a non-blank string |

## Merge

| Field | Rule |
| --- | --- |
| Grouping | Accepted items grouped by `normalize_geological_text(surface_form)` |
| `surface_forms` | every distinct surface form, sorted |
| `seed_term_ids` | every seed term whose normalised `label` or `labels_ru` entry equals the form, sorted; more than one entry is an ambiguous match and none is chosen |
| `status`, `proposed_kind`, `proposed_class` | only on an item with no `seed_term_ids`, which is `new_candidate` |
| `proposed_kind`, `proposed_class`, `suggested_seed_term_id` | the value most occurrences carry, a tie going to the smallest value; an optional key is absent only when no occurrence carries it |
| `suggested_seed_term_id` | the model's suggestion; never becomes a link |
| `document_count`, `occurrence_count` | over every accepted occurrence |
| `evidence` | each document's first occurrence in document order, then each document's second, and so on, up to `MAX_EVIDENCE_PER_ITEM`; a repeated `(file_id, chunk_id, excerpt)` is kept once |
| `unseen_seed_term_ids` | seed terms with `labels_ru` that appear in no item's `seed_term_ids` |

Items are sorted by normalised form. Every evidence `file_id` must appear in `documents[]`; otherwise `assemble_proposal` raises `EvidenceOutsideDocuments` (`evidence_file_not_in_documents`) before anything is written.

Two runs over the same chunks with the same replies give the same sample and the same proposal apart from `run_id`, `started_at` and `finished_at`.

## What a run writes

Three Open WebUI files owned by the user, uploaded with `process=False`, so none enters RAG indexing:

| File | Content |
| --- | --- |
| `ontology-induction-<run_id>.json` | The proposal, valid against the pinned proposal schema; its `meta.data.ontology_induction` holds `run_id`, `checkpoint_file_id` and `markdown_file_id` |
| `ontology-induction-<run_id>.md` | The reviewer view in Russian |
| `ontology-induction-<run_id>.checkpoint.json` | `{"run_id", "occurrences": {<file id>: [accepted occurrence]}}`, the accepted items of every `complete` document |

The first write creates each file; later writes overwrite the same storage object and update `meta.size` and `meta.file_hash`. `finished_at` is set once no document is `pending`.

The tool returns Markdown with the JSON file id and both download links, the number of documents per status, the totals per outcome, and the failed documents. It never returns the proposal body.

### Reviewer Markdown

| Section | Content |
| --- | --- |
| 1 | Items with one entry in `seed_term_ids`: term, form, surface forms, documents, occurrences |
| 2 | Items with several entries: form, number of terms, their kinds, ids folded after ten |
| 3 | New candidates grouped by `suggested_seed_term_id`, the group without one last; each group ranked by document count, then occurrence count |
| 4 | Unseen seed terms |
| 5 | The number of seed terms without `labels_ru`, which cannot be matched lexically (217 in seed v0.1) |

Surface forms are document text. Each is written as one code span, cut to 120 characters, with `|` escaped, so Markdown and HTML in it are not rendered.

## Resume

`resume_file_id` is the id of an earlier run's JSON proposal file.

| Check | Refusal |
| --- | --- |
| The file belongs to the user and is readable | `resume_file_not_found` |
| It is a JSON object | `resume_unreadable` |
| `seed_sha256`, `model_id` and `parameters` equal this run's | `resume_mismatch`, naming the keys that differ |
| Its `run_id` is 32 lowercase hex characters, `started_at` has the form `YYYY-MM-DDTHH:MM:SSZ`, every document carries exactly the keys its status requires, and the file is named `ontology-induction-<run_id>.json` | `resume_unreadable` |
| Its `meta.data.ontology_induction` carries the same `run_id` and names the user's `ontology-induction-<run_id>.checkpoint.json` and `ontology-induction-<run_id>.md`, and the checkpoint is a JSON object of that `run_id` | `resume_checkpoint_missing` |

A resumed run keeps the previous `run_id`, `started_at` and files, and overwrites them. A document is skipped when the previous proposal marks it `complete` and the checkpoint holds well-formed occurrences for it. A `no_stored_chunks` or `failed` document keeps its previous entry, under its current name, until it is processed again, after every `pending` document. Those documents are retried in document order, so with `MAX_DOCUMENTS` set, documents that keep failing ahead of others are retried first on every resume. A checkpoint occurrence whose `proposed_class` or `suggested_seed_term_id` is not a seed term makes its document `pending`. Every other document is `pending`. The document list and the scope are those of the current attachment, so a previous document no longer attached leaves the proposal. A resume makes no model call before every check passes.

## Valves

| Valve | Default | Meaning |
| --- | --- | --- |
| `MODEL_ID` | `''` | Model that reads the chunks; empty refuses with `invalid_parameter` |
| `CHUNKS_PER_DOCUMENT` | `3` | Chunks sampled per document, ≥ 1 |
| `MIN_CHUNK_CHARS` | `200` | Chunks shorter than this are not sampled, ≥ 0 |
| `MAX_DOCUMENTS` | `0` | Documents processed by one call; `0` means all; the rest stay `pending` for a resume |
| `MODEL_TIMEOUT_SECONDS` | `180` | Time limit of one model call, finite and > 0 |
| `MAX_EVIDENCE_PER_ITEM` | `5` | Evidence entries kept per item, ≥ 1 |
| `INDUCTION_PROMPT` | `''` | Replaces the default prompt when non-empty |

`MAX_DOCUMENTS` is not in `parameters`, so changing it does not block a resume.

## Installing the shim

```bash
PYTHONPATH=backend python scripts/build_ontology_induction_tool.py --output-dir dist
```

The script writes `dist/ontology_induction_tool.py` and `dist/ontology_induction_tool.manifest.json`. The manifest records the shim's `sha256`, `bytes`, source commit, valve defaults and the tool spec Open WebUI generates. The spec needs `backend/requirements.txt`. `--allow-missing-spec` records its absence and is for developer machines only.

1. Deploy the fork build of the source commit the manifest names; the shim imports `open_webui.tools.ontology_induction`.
2. In Workspace → Tools, create a tool with id `ontology_induction` and paste `ontology_induction_tool.py` unchanged.
3. Set the `MODEL_ID` valve.
4. Enable the tool for the model that should call it.

The shim holds the valves, argument coercion and one call to the built-in. It passes `__request__`, `__user__`, `__event_emitter__` and `__files__` through unchanged and declares no `requirements:`. Its method signature and docstring are derived from the built-in's; the model sees only `resume_file_id`. CI runs the build in `.github/workflows/backend.yaml`; `backend/tests/test_ontology_induction_tool_build.py` checks the shim.

## Privacy

A proposal and its checkpoint carry document excerpts. They stay in Open WebUI Files on the contour and are never committed to any repository. Only reviewed vocabulary without excerpts goes to GMM.

The files belong to the user who ran the tool and stay readable to that user after their access to the source collections is withdrawn. `utils/chat.generate_chat_completion` logs its `form_data`, which holds the chunk text, at `DEBUG`.

## Not verified

- Whether the contour's vLLM honours `response_format` with `json_schema`; no contour run has been made.
- Whether prefix caching is on for the contour's vLLM, which the shared system message would use.

## Tests

| File | Covers |
| --- | --- |
| `backend/tests/test_ontology_induction.py` | The built-in with Open WebUI models faked and files in a temp upload directory: locators, page rule, seed linking, guards, assembly invariant, prompt, refusals, outcomes, determinism, resume, digest check, merge, Markdown |
| `backend/tests/test_ontology_induction_tool_build.py` | The generated shim and its manifest |
