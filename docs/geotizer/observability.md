# Observability

A fill records what its owner attempts returned, what each specialist round cost, what the specialists searched for, and which build ran it.
Everything is sent to gis_service inside the `run_log` of the `finalize` payload.

| Source | Records |
| --- | --- |
| `backend/open_webui/services/artifacts/geotizer/observability.py` | One diagnostic per owner attempt. |
| `SpecialistRoundLog` in `owner_envelope.py` | Specialist failures and per-round usage. |
| `backend/open_webui/utils/geotizer_query_sink.py` | The searches specialists issued. |
| `record_retrieval_queries` in `owner_envelope.py` | The searches a RAG dispatcher planned. |
| `backend/open_webui/build_revision.py` | The commit the run was built from. |

## Owner attempt diagnostics

- `owner_attempt_diagnostic` assigns an owner attempt one of the `response_mode` values `EMPTY_RESPONSE`, `UNPARSEABLE_RESPONSE` and `PARSED_RESPONSE` (`owner_envelope.py`).
- `UNPARSEABLE_PREFIX_CHARS` is how many leading characters of an `unparseable` response are kept as `text_prefix`.
- `CHARACTERS_PER_TOKEN_ESTIMATE` is the characters-per-token ratio behind `tokens_estimate`, an estimate and not a tokenizer count.
- `OWNER_REQUEST_SECTION_ROLES` maps each prompt section, a top-level key or `context.<key>`, to `instruction`, `evidence` or `repair`.
- A prompt section `OWNER_REQUEST_SECTION_ROLES` does not list counts as `other`.

## Specialist usage

- `SPECIALIST_USAGE_KEYS` are the only usage keys read from a specialist envelope.
- `_specialist_usage`, used by `specialist_failure_signal`, copies only the `SPECIALIST_USAGE_KEYS` present in the envelope's `usage` block, and adds neither `usage` nor `reasoning_only` when none is present.
- `_is_reasoning_only` is true only when `reasoning_tokens` is a number greater than zero.
- `ORCHESTRATOR_ROUND_KEYS` is `SPECIALIST_USAGE_KEYS` plus the orchestrator-measured `content_chars`, `reasoning_chars`, `tool_call_count` and `compacted_chars`.

## Specialist round log

- `SpecialistRoundLog.add` counts a failure before appending it to the capped list.
- `SpecialistRoundLog` counts `issued` and every sub-count over all added failures.
- `SpecialistRoundLog` keeps at most `cap` failure records, with `MAX_RECORDED_SPECIALIST_ROUNDS` (500) as the default cap.
- `stats()` reports `dropped` and `truncated`, and returns `{}` when nothing was added.
- `cap` bounds `records` only, while `rounds()` is uncapped and returns copies.
- `SpecialistRoundLog.observe_round` counts a round for `usage_stats` and, when given `failure`, records the failure in the same call.
- `SpecialistRoundLog` ignores boolean token or character counts.
- `usage_stats` returns `{}` with no rounds, and splits rounds `by_outcome`, `by_agent` and `by_batch`.
- `usage_stats` counts a round without usage as `unmeasured`, and publishes no token percentiles for a population with none measured.
- `SpecialistRoundLog._percentiles` computes nearest-rank percentiles: the p-th percentile of n values is the `ceil(p·n)`-th smallest.
- `SpecialistRoundLog._round_source` names the round population `usage_stats` reports, `specialist_calls` or `orchestrator_rounds`.
- `absorb_orchestrator_rounds` replaces the counted specialist-call population with a non-empty list and switches `usage_stats()['source']` to `orchestrator_rounds`.
- `absorb_orchestrator_rounds` changes nothing and returns 0 for an empty list or a list of non-mapping entries.
- `absorb_orchestrator_rounds` keeps `content_chars`, `reasoning_chars`, `tool_call_count` and `compacted_chars` including zeros, because zero and an absent key are different facts, and adds none a round did not report.
- `absorb_orchestrator_rounds` carries the round's `measured` flag, and `usage_stats` falls back to the presence of token counts when the flag is absent.
- The run log's `specialist_round_usage` has `source` `orchestrator_rounds` when drained orchestrator rounds were absorbed, and `specialist_calls` otherwise, with every round counted as unmeasured.

## Orchestrator round usage

- `round_usage_scope` looks for `open_round_usage` and `drain_round_usage` on the handle, then on the module that defines the handle's class, and returns None unless one object carries both.
- `load_tool_module_by_id` returns a `Tools()` instance, which is why `round_usage_scope` looks on the module that defines the instance's type.
- `round_usage_drain.open()` is the first statement of `run_geotizer_workflow`, and a round recorded before `open()` is dropped.
- `run_geotizer_workflow` calls `round_usage_drain.drain()` at run-log assembly.
- An exception from `round_usage_drain.drain()` is swallowed, and every round is then reported unmeasured.

## Issued searches

- `open_webui.tools.builtin` has four functions that call `record_query`: `query_knowledge_files`, `grep_knowledge_files`, `search_web` and `fetch_url`.
- Each of the four call sites passes `started` taken from `query_clock()` before the call.
- `record_query` computes `elapsed_ms` from the `started` value the call site passes, and records `None` when no `started` is passed.
- `record_query` records nothing outside a `recording_queries` scope, drops an entry it cannot build without raising, and a nested scope restores the outer one on exit.
- `record_query` collapses repeated `|` alternatives (first-seen order) in a pattern with no group, class or escaped `|`, recording `alternatives_received`, `alternatives_distinct` and `query_chars_received`.
- `record_query` truncates a query to `MAX_RECORDED_QUERY_CHARS`, recording `query_truncated` and `query_chars`.
- `QueryDrain` keeps at most `geotizer_query_sink.MAX_RECORDED_QUERIES` entries.
- `QueryDrain.stats()` reports `issued` (how many searches the run made), `recorded`, `dropped` (how many the cap dropped), `truncated` and `cap`.
- `QueryDrain.stats()` is published as `retrieval_query_stats` beside the query list, never as an entry in it.
- With `query_drain=None`, no issued query is recorded.

## Planned searches

- `record_retrieval_queries` does nothing when the log is None.
- `record_retrieval_queries` records every plan, including disabled ones, with its batch, `index/total` chunk, agent, query id, status, tier, exact query and must and should terms.
- `MAX_RECORDED_QUERIES` in `owner_envelope.py` is the most planned-search entries `record_retrieval_queries` records per run.
- After `MAX_RECORDED_QUERIES` entries `record_retrieval_queries` appends one `{'truncated': True, 'recorded': MAX_RECORDED_QUERIES}` marker and records nothing more.

## Queries in the run log

- With a `query_drain`, the run log sent into `finalize` carries `retrieval_queries` and `retrieval_query_stats`, and the terminal payload carries the same `retrieval_queries`.
- Without a `query_drain` and without a RAG dispatcher in `active` or `shadow` mode, the run log has no `retrieval_queries`.
- The citation join reads the fields from the workflow's own state before `finalize`, not from `finalize`'s answer.
- `_queries_with_citations` counts a citation when a recorded result document id is a filled cell's `source_locator.document_id` or appears inside its `source_refs`.
- `_queries_with_citations` omits `citations` when no result document ids were recorded, and omits empty collection ids from `cited_collections`.
- `_query_stats` returns sorted `collections_read`, `collections_marked` and `collections_read_unmarked` whenever it returns stats.
- With nothing marked, `_query_stats` reports every collection read as unmarked.
- `collections_marked` records the collections attached to the run (`kb_configured_collections`) and is not enforced.
- `kb_configured_collections` marks which collections the run is about and grants nothing.

## Run log

- `run_geotizer_workflow` sends the run-level records (`run_notes`, `retrieval_queries`, `gis_execution_trace`, `gis_layer_manifest`, `gis_proposal_rejections` and the other records) into GIS `finalize` as `run_log`.
- `run_geotizer_workflow` sends `gis_proposal_rejections` beside `gis_execution_trace`.
- `finalize` in `gis_service/arcgis_mcp/geotizer/service.py` saves the `run_log` it receives as `run_log.json` beside the run state.
- `state.json` is written by gis_service, and a key attached only to the terminal payload `run_geotizer_workflow` returns does not reach it.
- `_run_timing`'s `outside_batches_seconds` covers the setup before the first batch and the finalize after the last.

## Build revision

- `run_geotizer_workflow` sends its `build_revision` argument as `run_log.build_revision`, and sends no such key when the argument is not given.
- `build_revision` returns `revision` (the HEAD commit), `dirty` (from `git status --porcelain`, `None` when the status cannot be read) and `source` `FROM_GIT`, and is cached for the process.
- When HEAD cannot be read, `build_revision` returns `revision` and `dirty` as `None` with `ABSENCE_KEY` (`revision_absent_because`) set to `UNREADABLE_ABSENCE` (`unreadable`), and does not run `git status`.
- A revision that was read carries no `ABSENCE_KEY`.
- `checkout_path` reads the checkout from `CHECKOUT_VARIABLE` (`GEOTEASER_WEBUI_CHECKOUT`) and falls back to `DEFAULT_CHECKOUT` (the repository root) when it is unset, empty or blank.
- `_git` runs git with `GIT_HARDENING` (`core.fsmonitor=` and `core.hooksPath=/dev/null`), and returns `None` when git is missing, the checkout is unreadable, the call times out or git exits non-zero.

## RAG shadow dispatch

- `main.py` registers no shutdown drain for `utils/geotizer_rag_runtime.py`.
- The first shadow dispatch logs one warning per process until `register_shutdown_drain` is called.
