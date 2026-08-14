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
Tool, **127 of 131 top-level definitions already have zero `open_webui`
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

288 top-level definitions in 28 modules. `utils/geotizer_orchestration.py` is gone;
so are `utils/geotizer_retrieval.py`, `utils/geotizer_semantics.py` and
`utils/geotizer_resource_coherence.py`.

| Layer | Module | Holds |
|---:|---|---|
| 0 | `geotizer/errors.py` | `GeotizerOrchestrationError`, `GeotizerGisError`, `ensure_state_can_continue` |
| 1 | `geotizer/semantics.py` | `geotizer_runtime_semantics.v0.2` row semantics (ADR-0020) |
| 1 | `core/text.py` | bounded text, JSON extraction, fence stripping |
| 1 | `core/tasks.py` | `AgentTask` |
| 1 | `core/vocabulary.py` | field statuses, value origins, negative-value markers |
| 1 | `core/idempotency.py` | the persistent run key, and why a Redis lock is not one |
| 1 | `artifacts/geotizer/validation.py` | the 13 hand-written copies of the GIS submission rules |
| 2 | `project_evidence/retrieval.py` | retrieval planning, evidence chains, locator identity |
| 2 | `project_evidence/resource_coherence.py` | resource-estimate coherence |
| 3 | `project_evidence/proposals.py` | normalisation, source selection, conflict resolution |
| 4 | `artifacts/geotizer/owner_envelope.py` | batching, extraction, merge, repair |
| 5 | `artifacts/geotizer/observability.py` | the owner-attempt diagnostic |
| 5 | `artifacts/geotizer/project.py` | projecting the dossier onto the 351 fields |
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
delete the eleven hand-written copies of those rules afterwards.

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
de-coupling the evidence core from the GeoTeaser cell: **48 of the 288
definitions still mention `field_key`**, thirteen of them inside
`project_evidence/`.

Only those thirteen are the residue. The other 35 live in
`artifacts/geotizer/*`, where `field_key` is the artefact's own vocabulary and
belongs. The earlier figure said "nine", which was this table's largest single
row rather than its total -- the table below has summed to thirteen the whole
time.

| Module | Definitions | Mention `field_key` |
|---|---:|---:|
| `project_evidence/proposals.py` | 32 | 5 |
| `project_evidence/resource_coherence.py` | 6 | 4 |
| `project_evidence/retrieval.py` | 21 | 4 |
| `artifacts/geotizer/owner_envelope.py` | 24 | 9 |
| `artifacts/geotizer/validation.py` | 13 | 3 |

Inside `artifacts/geotizer/` that is correct — `field_key` is the artefact's own
vocabulary. Inside `project_evidence/` it is the coupling `EVID-MODEL-01`
exists to remove: a fact keyed by a workbook cell cannot serve a CPR
requirement. `GT-PROJ-01` is where those nine move onto dossier claims, and this
count is its target.

## Where each definition is going

`GMM/operations/gt-conv-01/definition-classification.json` carries the target
module and a reason for all 131 definitions, and is validated in GMM's CI.
Read it before adding anything here.
