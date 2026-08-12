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

A root that does not exist yet is skipped and reported, so the check is
meaningful the day a root appears without being noisy before then.

## What is in here now

110 definitions in eleven modules. `utils/geotizer_orchestration.py` is gone;
so are `utils/geotizer_retrieval.py`, `utils/geotizer_semantics.py` and
`utils/geotizer_resource_coherence.py`.

| Layer | Module | Holds |
|---:|---|---|
| 0 | `geotizer/errors.py` | `GeotizerOrchestrationError`, `GeotizerGisError`, `ensure_state_can_continue` |
| 1 | `geotizer/semantics.py` | `geotizer_runtime_semantics.v0.2` row semantics (ADR-0020) |
| 1 | `core/text.py` | bounded text, JSON extraction, fence stripping |
| 1 | `core/tasks.py` | `AgentTask` |
| 1 | `core/vocabulary.py` | field statuses, value origins, negative-value markers |
| 1 | `artifacts/geotizer/validation.py` | the 13 hand-written copies of the GIS submission rules |
| 2 | `project_evidence/retrieval.py` | retrieval planning, evidence chains, locator identity |
| 2 | `project_evidence/resource_coherence.py` | resource-estimate coherence |
| 3 | `project_evidence/proposals.py` | normalisation, source selection, conflict resolution |
| 4 | `artifacts/geotizer/owner_envelope.py` | batching, extraction, merge, repair |
| 5 | `artifacts/geotizer/observability.py` | the owner-attempt diagnostic |

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
  layer 1. It holds the rule copies that the artefact reads, and
  `CORE-BOUNDARY-01` action 4 deletes it once GIS owns the check. It is not
  deleted yet: removing it before the compatibility tests exist would take away
  the only check the caller has.
- `geotizer/semantics.py` is not under `project_evidence/`, where step 1 first
  put it. It is keyed by GeoTeaser template row — `{15: 'tectonic_domain', …}` —
  so it is template semantics, not evidence. Leaving it in the evidence package
  also broke the layering, since `validation.py` reads it from below.

## The `field_key` residue

The split moves code into the right packages. It does **not** finish
de-coupling the evidence core from the GeoTeaser cell: **25 of the 110
definitions still mention `field_key`**, nine of them inside
`project_evidence/`.

| Module | Definitions | Mention `field_key` |
|---|---:|---:|
| `project_evidence/proposals.py` | 33 | 5 |
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
