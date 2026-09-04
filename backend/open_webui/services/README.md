# `services/` — the pure core

Created by `GT-CONV-01` step 4 to hold the purity boundary before there is
anything inside it. The import check that guards this tree is live from now on,
so the first module `CORE-BOUNDARY-01` adds is protected on the commit that
adds it, not on some later commit that remembers to switch a gate on.

## The rule

**No module under this tree may import `open_webui`.**

Enforced by `scripts/check_geotizer_import_boundary.py`, run in `backend.yaml`.
The check reads the roots below, walks every `.py` file with an AST pass, and
fails on any `import open_webui…` or `from open_webui… import …`, including
imports written inside a function body.

## Why

`open_webui.utils.*`, the model classes and the middleware helpers are not a
stable public surface. `CHANGELOG.md` records renames and moves as routine —
an environment variable renamed with only a deprecated alias, admin settings
relocated, the tool-calling default flipped — and there is no deprecation
machinery anywhere in the backend: no `DeprecationWarning` is ever raised, and
`utils/tools.py`, `utils/plugin.py` and `utils/middleware.py` carry no
`__all__`. Anything that imports them inherits that churn.

The measured target is not aspirational. In the production `geoteaser 2.2.0`
Tool, **127 of 348 top-level definitions already have zero `open_webui`
dependency**, and the four that bind it do so through eight in-function imports
with no module-level import at all. Those four are the effect shell:

    resolve_gis_call · build_agent_call · build_vision_call · Tools

They stay outside this tree, in the adapter and the effect shell. Everything
else lifts in unchanged.

## Roots

| Root | Owner task | Holds |
|---|---|---|
| `services/project_evidence/` | `CORE-BOUNDARY-01` | retrieval planning, normalisation, conflict resolution, source selection, observability. Keys on dossier claims, **not** `field_key`. |
| `services/artifacts/geotizer/` | `CORE-BOUNDARY-01` | field mapping, owner envelope, terminal adapter. GeoTeaser-specific logic lives only here. |
| `services/artifacts/cpr/` | `CORE-BOUNDARY-01` | requirement planning, coverage, narrative plan, audit. |
| `services/geotizer/errors.py` | `CORE-BOUNDARY-01` | the six shared exception types. |
| `services/evaluation/` | `RAG-EVAL-01` | the retrieval A/B, scored on the dossier. Imports nothing in here and is imported by nothing in here. |

The check walks the whole tree, not this table. A list of roots is escapable —
`artifacts/consistency.py` matched none of the five originally listed, so
nothing read it — and a directory added later would have been the next one out.
The table describes the tree; the gate reads it.

## What is in here now

460 top-level definitions in 32 modules. `utils/geotizer_orchestration.py` is gone;
so are `utils/geotizer_retrieval.py`, `utils/geotizer_semantics.py` and
`utils/geotizer_resource_coherence.py`.

| Layer | Module | Holds |
|---:|---|---|
| 0 | `geotizer/errors.py` | `GeotizerOrchestrationError`, `GeotizerGisError`, `ensure_state_can_continue` |
| 1 | `geotizer/semantics.py` | `geotizer_runtime_semantics.v0.2` row semantics (ADR-0020) |
| 1 | `core/text.py` | bounded text, JSON extraction, fence stripping |
| 1 | `core/tasks.py` | `AgentTask`, and the parser for the `PRODUCER_KIND_MAP` valve that replaced the hardcoded producer table |
| 1 | `core/vocabulary.py` | field statuses, value origins, negative-value markers |
| 1 | `core/idempotency.py` | the persistent run key, and why a Redis lock is not one |
| 1 | `core/deadline.py` | the wall-clock backstop on a whole fill: checked between units, never enforced by a wrapper |
| 1 | `artifacts/geotizer/validation.py` | the 12 hand-written copies of the GIS submission rules, plus two entry points and one local rule the service has no counterpart for |
| 1 | `project_evidence/agreement.py` | whether independent source domains agreed on a claim |
| 1 | `project_evidence/claims.py` | what counts as a live claim, shared by both projections |
| 1 | `project_evidence/dossier.py` | what a dossier must hold before either artefact projects it |
| 2 | `project_evidence/retrieval.py` | retrieval planning, evidence chains, locator identity |
| 2 | `project_evidence/resource_coherence.py` | resource-estimate coherence |
| 3 | `project_evidence/proposals.py` | normalisation, source selection, conflict resolution |
| 4 | `artifacts/geotizer/owner_envelope.py` | batching, extraction, merge, repair |
| 5 | `artifacts/geotizer/observability.py` | the owner-attempt diagnostic |
| 2 | `artifacts/geotizer/vision.py` | visual evidence: normalising and applying visual proposals |
| 3 | `artifacts/geotizer/prompts.py` | the prompts, contracts and rules the run shows a model |
| 5 | `artifacts/geotizer/project.py` | projecting the dossier onto the 351 fields |
| 5 | `artifacts/geotizer/terminal.py` | the terminal envelope, its attachments, and the progress lines |
| 6 | `artifacts/geotizer/workflow.py` | the run itself, with the effect shell injected |
| 7 | `artifacts/geotizer/area_workflow.py` | an area fill: the object fill composed per member, with no roll-up |
| 1 | `artifacts/cpr/errors.py` | `CprContractError` |
| 4 | `artifacts/cpr/catalog.py` | loading the requirement catalog and verifying its digest |
| 5 | `artifacts/cpr/requirements.py` | requirement planning against the object's lifecycle stage |
| 6 | `artifacts/cpr/coverage.py` | section coverage and the §9 completeness denominator |
| 6 | `artifacts/cpr/narrative.py` | the narrative plan: which sentences, on whose authority |
| 6 | `artifacts/cpr/project.py` | building the projection from a dossier |
| 7 | `artifacts/cpr/audit.py` | auditing a projection against the catalog and the dossier |
| 8 | `artifacts/cpr/render.py` | the artefacts: docx, PDF, coverage.json, source and audit reports, manifest |
| 9 | `artifacts/consistency.py` | do the two artefacts say the same thing about the same fact |
| 10 | `evaluation/rag_ab.py` | the retrieval A/B: `NO_GO \| ITERATE \| GO_SHADOW_EXPANSION` |

Moved, not copied: the old paths are gone and every importer was rewired. A
compatibility shim would let a caller keep the old path indefinitely, and
`test_geotizer_import_boundary.py` asserts the old paths no longer exist.

`GeotizerGisError` was previously declared inside `tools/geotizer.py`, so the
Workspace-facing tool had to import the orchestration module in order to raise
a GIS failure. Both types now have exactly one declaration site, which
`test_geotizer_core_errors.py` pins.

## Layers

**A module may import its own layer or a lower one, never a higher one**, and
imports between modules in this tree are **relative**. Both are enforced by
`test_geotizer_service_layering.py`. Relative imports are what make lifting this
tree out of `open_webui` a move rather than a rewrite, and they are why the
outer check — which greps for `open_webui` — stays meaningful inside the tree.

Two placements are deliberate and look wrong at first glance:

- `artifacts/geotizer/validation.py` is nested under the artefact but sits at
  layer 1. It holds the local copies of the GIS submission rules — see below
  for why they are still here.
- `geotizer/semantics.py` is not under `project_evidence/`, where step 1 first
  put it. It is keyed by GeoTeaser template row — `{15: 'tectonic_domain', …}` —
  so it is template semantics, not evidence. Leaving it in the evidence package
  also broke the layering, since `validation.py` reads it from below.

## The CPR artefact

`artifacts/cpr/` is the second artefact, and it exists to prove the first one
is not the model. It reads the same projection contract the GeoTeaser artefact
does, references the same dossier ids, and shares the evidence core underneath.
Nothing in `project_evidence/` knows it is there.

Four things, in the order a run uses them:

1. **Plan** — every catalog requirement resolved against the object's lifecycle
   stage. A requirement that does not apply *stays in the plan*, marked
   `applicable=False`. §10's named risk is 119 requirements treated as
   mandatory at an early stage; dropping them would hide the judgement rather
   than record it.
2. **Measure** — per-section coverage, and the §9 rate with its denominator
   shown. Exactly one thing may leave the denominator: a `not_applicable` a
   reviewer approved. A requirement the projection says *nothing* about is
   reported as `unaddressed` rather than folded into `missing` — `missing`
   means the projection looked and recorded why, and the six-state vocabulary
   has no word for silence.
3. **Write** — the narrative plan. A statement sentence cites at least one
   claim, estimate or figure; an absence cites a recorded reason; a conflict
   cites both sides and the conflict record. There is no fourth kind, so there
   is no way to plan a sentence asserting something the dossier does not hold.
   The plan carries ids, never text: wording belongs to the renderer.
4. **Audit** — the runtime half of GMM's `validate_evidence_dossier.py`. CI can
   refuse a commit; it cannot refuse a run, and a run assembles a projection
   from live evidence. Findings are returned rather than raised, because the
   audit section is part of what gets delivered.

### The catalog copy

`artifacts/cpr/assets/` carries a byte-identical copy of GMM's
`contracts/cpr/cpr_requirement_catalog.v1.json`, and `provenance.json` records
its digest, source path and source commit. **The digest is verified on every
load.** Without that check the CPR could be planned against one set of
applicability rules and audited against another, with both looking right — the
same silent-drift risk GMM's register carries as A-08 for the geotizer assets
in `gis_service`.

The catalog's status is `draft_for_domain_review` and `catalog.is_draft()`
carries that to the caller. Planning against a draft is fine; presenting the
output as approved is not.

## The rule copies, and why they stayed

`CORE-BOUNDARY-01` action 4 adds `action=validate_batch` to `gis_service` — the
verdict `submit_batch` would reach, without saving anything — and says to
delete the twelve hand-written copies of those rules afterwards.

The compatibility evidence is
`artifacts/geotizer/assets/geotizer-validation-parity.v1.json`: twenty-two
envelopes with the verdict the server actually returns for each, generated
through its HTTP boundary, since six of them are refused by the request model
rather than by the state machine. `test_geotizer_validation_parity.py` runs
every case against `validation.py` in both directions — never stricter than the
server, never weaker.

It found four. All four were source-inventory shapes accepted here and refused
there: a source entry without a title, without a type, without an id, and one
that is not an object at all. That is exactly the HTTP 422 the caller was
hitting after a whole batch had been built, and the fix is the production
Tool's implementation, which had already closed it. GMM's register carries the
direction as A-04.

**The copies are not deleted.** They run inside the owner retry loop: per
candidate during salvage, again on each merge, and once per one-field probe.
Replacing them with a server call puts a network round trip in each of those
places and makes salvage fail whenever GIS is briefly unreachable — the outage
salvage exists to survive. At the boundary the round trip buys nothing either,
because `submit_batch` already validates before it persists.

What they were missing was not deletion but a way to notice drift, and that now
exists and runs on every build. Removing them anyway is a Runtime Owner
decision; it is recorded rather than taken here.

## Run identity

`core/idempotency.py` implements action 6: a run is
`project_id + artifact_set + frozen_inputs_hash`, and repeating the command
with the same key returns the original run.

**A Redis lock is not that key.** A lock stops two starts racing for a few
seconds; it expires, and a retry that consults only the lock starts a fresh run
over the same inputs. The lock guards the *capture*, the key guards the
*identity*, and the registry is read twice — once before the claim and once
under it — so the second read is what decides. An expired lock therefore costs
a wasted start at most, never a second recorded run. Redis being unavailable
entirely still yields one run.

The artefact set is a set: asking for the CPR and the workbook is one request
whichever order they were named in. A changed input, however deeply nested, is
a different run — reusing one whose inputs moved would serve a stale answer to
a fresh question.

### The CPR Readiness slice

`CPR-SLICE-01` implements the sections the assignment names — 0.4, 1, 2, 3.1,
3.7, 4, 5.3, 7 and the mandatory resource and classification questions: 74 of
the catalog's 126 requirements. `assets/cpr-slice-projection-map.v1.json` says
which dossier predicate answers each of them, so a requirement is answered when
the dossier holds that fact and reported absent when it does not. There is no
path that matches requirement text against claim text.

Against the Лекын run: 3 answered, 2 conflicted, 4 blocked on an expert, 38
missing, 27 out of stage. A document that answers 3 of 88 and is still worth
reading is the point.

Two controls are verified rather than assumed:

- **The draft marking.** `DRAFT — NOT A JORC/NAEN CERTIFICATION` goes in the
  page header of both the `.docx` and the PDF, not only the body — §10 makes it
  a checkable control, and a banner in the body is one keystroke from gone.
  `docx_watermark_is_present` reads it back out of the rendered bytes.
- **Determinism.** Re-rendering the same projection produces the same bytes.
  The `.docx` ZIP entries carry a fixed timestamp and the PDF's `/CreationDate`
  is pinned to the dossier freeze, because §9 requires a re-render to reach the
  same artefact hashes. A document dated when someone pressed the button could
  never satisfy that.

## The workbook as a projection

`GT-PROJ-01`. `assets/cpr_to_geotizer_mapping.v1.json` carries a projection
expression for all 351 fields: 245 read a dossier claim, 106 are marked as
things a CPR does not report — map sheets, sites 1–4, analogues, spatial
distances, the legal-entity portfolio and the GRR plan.

The row is the unit of meaning. A resource row is one estimate with six facets,
so one claim can fill six cells — but only the cells it actually answers. A
scalar claim fills the row's first facet and nothing else; a claim whose value
is a mapping fills the facets it names. Without that rule a claim holding only
a project stage would also fill the stage's start and end dates, and the
workbook would report three answers where the dossier has one.

Against the Лекын run: 4 cells filled, **1.14% semantic completeness**. The
criterion asks for 80%. That gap is a statement about the evidence, not the
projection — nine claims against 351 cells — and nothing here should be tuned
to improve the number. `test_the_eighty_percent_criterion_is_not_met_by_this_dossier`
records it so both the gap and the day it closes are visible.

## The `field_key` residue

The split moves code into the right packages. It does **not** finish
de-coupling the evidence core from the GeoTeaser cell: **87 of the 460
definitions still mention `field_key`**, sixteen of them inside
`project_evidence/`.

The 442nd is `artifacts/geotizer/_with_exit`, added on 2026-09-02. It appends
the status that closes an unsatisfiable row to a violation another rule already
raised — run `06fec58d` lost 25 cells because the subarea refusal said what was
wrong and never what was right, while `94124958` on the same build answered
`not_applicable` and kept them.

The 443rd is `artifacts/geotizer/terminal/_run_variance_lines`, added on
2026-09-03. Four clean runs of one build filled 207, 191, 219 and 137 of 351
cells with nothing changed between them, so the envelope no longer prints the
count alone.

The 444th is `_run_variance_figures`, the same day. A build is three
repositories that drift independently, so the service reports one of four
states — the band, a band measured on another build with the repositories this
one differs in, no band at all, or a build it could not read — and the two
branches that print numbers share one formatter rather than two copies of the
same sentence. Neither definition mentions a `field_key`.

The 445th, 446th and 447th arrived on 2026-09-03 with the query record:
`artifacts/geotizer/workflow/QueryDrain`, the protocol the core is handed so
the boundary holds in one direction; `_agent_call_recording_queries`, which
opens the attribution scope *inside* each specialist coroutine rather than
around the gather that schedules them, because `contextvars` are copied at task
creation and a scope set outside would label all six contributors with whichever
agent was set last; and `_queries_with_citations`, which puts issued queries and
RAG-v2 plans in one list with each entry saying which it is. None mentions a
`field_key`.

The 450th and 451st are `artifacts/geotizer/area_workflow.py`, added on
2026-09-04: `run_geotizer_area_workflow` and `_member_order`. The 32nd module,
and the only one so far that fills more than one object. It is a *composition*
over `run_geotizer_workflow` rather than a mode inside it — the single-object
path is the one with four measured runs behind it, and a branch would put it one
step from an unmeasured path. Each member is filled by exactly the call a
single-object request makes; the area supplies only what a member cannot, which
is its own order and its own bound. It does not aggregate, and says so with a
state and a reason rather than a missing key. Neither mentions a `field_key`.

The 452nd, 453rd and 454th arrived on 2026-09-04 in
`artifacts/geotizer/workflow.py`, because two fills that finished took 2h32m43s
and 2h47m59s and the run log said nothing about where that time went. `_stamp`
reads one UTC instant in the one format the rest of the log already uses;
`_batch_timing` describes a single owner batch — its wall-clock ends, its
seconds, the queries recorded while it ran, and how many specialist calls
issued at least one of them; `_run_timing` sums those rows and reports the
remainder against the run's own two ends, so a reader can see whether the
batches ran one after another or overlapped without timing anything twice. All
three derive from clocks the run already keeps, and none mentions a
`field_key`.

The 455th is `artifacts/geotizer/terminal/failure_details`, added on
2026-09-04. Run `475dc4f5` returned `code: ValueError · details: null` on
«dictionary update sequence element #0 has length 1; 2 is required» — a message
naming no key, no value and no frame, on a fill that died in its first seconds.
`details` had always been `getattr(exc, 'details', None)`, which finds a value
on the errors this project raises deliberately and `None` on every exception
that escaped from below them: the one kind that needs a frame was the one kind
that got none. This splits by origin rather than by type — `GeotizerOrchestrationError`
derives from `ValueError`, so the type name answers nothing — and gives an
escaped exception its last forty traceback lines, innermost first to survive.
It mentions no `field_key`.

The 456th to 460th arrived on 2026-09-04 and are two changes.

Three of them read the specialist envelope this repository already received
and was discarding: `artifacts/geotizer/owner_envelope/_specialist_usage`,
`_is_reasoning_only`, `specialist_round_record` and `specialist_round_stats`.
`empty_completion` carries `finish_reason`, `completion_tokens` and
`reasoning_tokens`, which separates a model that declined from a content filter
from a reasoning budget that consumed the whole completion. The third is the
one the audit asks about: Open WebUI parses `<think>` out of the content, so a
round whose work lands in that channel yields no content and no `tool_calls`,
and the loop sees an empty round. Nothing branches on it — the record exists so
the decision has a number under it.

`normalise_patch_locators` is A-178's answer: `source_locator` is polymorphic,
`locator_map` is called at 20 sites, and 45 raw reads are correct only because
a string has not been handed to them yet. The parse moves to the two doors an
owner envelope comes through. Only the string shape is touched — absence stays
absence, because `{}` is not `None` and `validation.py` reads the difference.
None of the five mentions a `field_key`.

The 449th is `_query_stats`, added on 2026-09-03. Runs `82365089` and
`26aaf34a` both ended with exactly 401 query records, the last of them
`{"recorded": 400, "truncated": true}` — a truncation sentinel living inside
the array it described. It made the count useless as a measurement (401 in both
runs meant only that both exceeded 400) and the array heterogeneous for every
consumer that groups by agent or iterates tools. This puts `issued`, `recorded`
and `dropped` in `retrieval_query_stats` beside the list, along with which
collections the run actually read and which of those the user had not attached.
It mentions no `field_key`.

The 448th is `_cited_document_ids`, added on 2026-09-03. The first pair of runs
to carry a query record joined a KB result to a cell on the *filename*, and it
returned 0 on all 406 entries that had results: a result carries
`Проект ГРР Лекын-Тальбейское 2025.pdf` and a locator carries
`document_id: cdd1bdf0-…`. This reads the ids off both carriers a cell uses —
`source_locator.document_id` and the uuid embedded in each `source_ref` — so
the join is on identity. It mentions no `field_key`, which is why the residue
stays at 87.

The 441st is `artifacts/geotizer/refuse_a_unit_the_source_contradicts`, added
on 2026-09-02 with five others. Two of the six name a field key and are in
`artifacts/geotizer/` — `a_reading_is_not_a_computation`, which stops a number
transcribed off a layer summary from claiming `value_origin: calculated`, and
`refuse_a_unit_the_source_contradicts`, which refuses a value whose unit its
own source disagrees with. The other four are the unit vocabulary in
`geotizer/semantics.py` — `canonical_unit`, `unit_named_in_locator`,
`_locator_strings`, `states_a_conversion` — and none of them mentions a field
key, which is why the residue rose by two and not six: they answer «what unit
does this string state», a question with nothing to do with which cell asked.

`artifacts/geotizer/_stage_scope_lines`, added the same day.
It mentions no `field_key`, which is why the residue stays at 85: it prints
the completeness figure against the denominator the agreed report profile
asks for, and it reads that projection off what the service sent rather than
computing it here.

Sixteen, not fourteen. `normalize_gis_field_proposals_with_rejections` and
`_gis_proposal_rejection` were added on 2026-08-31 so the proposal filter
could say which key it refused and why, and both name the field key because
that is their subject. The direction of travel here is meant to be downward,
so a rise is recorded rather than absorbed: it is the price of run
`803ce041`'s finding that a proposal for a key the asking batch owned could
be dropped and reported nowhere at all.

Only those sixteen are the residue. Of the other 71, **67** are in
`artifacts/geotizer/*`, where `field_key` is the artefact's own vocabulary and
belongs. The 62nd is `record_gis_proposal_rejections`, added on 2026-09-01 so
run `1c46b6ca`'s dropped proposals could be read out of `run_log.json` instead
of only out of an evidence item no artefact carries; it names field keys
because a rejection with no key names nothing. The 63rd and 64th are
`_wrong_kind_for_the_row` and `refuse_the_wrong_kind_of_answer`, added on
2026-09-01 for the Domain Reviewer's answers of 2026-08-30; both name field
keys because three of the five answers are bound to named rows and to nothing
else. The 65th is `mark_rejections_answered_elsewhere`, added on 2026-09-02:
it joins a refused proposal to the cell that key names, so a log of 39
rejections stops reading as 39 losses. The remaining **4** are in `artifacts/consistency.py` (1),
`evaluation/rag_ab.py` (2) and `geotizer/semantics.py` (1). The first three
compare the two artefacts and must therefore speak both vocabularies. The
fourth is `expects_a_number`, which answers "does this cell take a quantity?"
and needs the field key because the template declares no types and «значение»
means a distance on six rows and prose on a seventh -- a different
justification again from the artefact's, and worth naming rather than folding
into it.

Every number in this section is recomputed by
`backend/tests/test_services_readme_counts.py`. It has been wrong four separate
ways -- a total that was really one table row, a stale tree size, a layer table
five modules short, and "35 in `artifacts/geotizer/*`" when 32 are -- because
prose is the one place nobody recomputes.

The five modules with the most mentions, recomputed rather than carried
forward. It is a sample, not the accounting for all 50 -- these rows sum to 31.

| Module | Definitions | Mention `field_key` |
|---|---:|---:|
| `artifacts/geotizer/owner_envelope.py` | 20 | 10 |
| `artifacts/geotizer/vision.py` | 13 | 6 |
| `artifacts/geotizer/workflow.py` | 22 | 6 |
| `project_evidence/proposals.py` | 32 | 5 |
| `artifacts/geotizer/project.py` | 15 | 4 |

Inside `artifacts/geotizer/` that is correct — `field_key` is the artefact's own
vocabulary. Inside `project_evidence/` it is the coupling `EVID-MODEL-01`
exists to remove: a fact keyed by a workbook cell cannot serve a CPR
requirement. `GT-PROJ-01` is where those fourteen move onto dossier claims, and this
count is its target.

## Where each definition is going

`GMM/operations/gt-conv-01/definition-classification.json` carries the target
module and a reason for all 131 definitions, and is validated in GMM's CI.
Read it before adding anything here.
