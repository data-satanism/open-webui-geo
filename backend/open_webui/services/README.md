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

`CORE-BOUNDARY-01` step 1 moved the three modules that already had **zero**
`open_webui` imports before the move, plus the two exception types that had
been declared in two different places:

| Module | Came from | Holds |
|---|---|---|
| `geotizer/errors.py` | `utils/geotizer_orchestration.py` + `tools/geotizer.py` | `GeotizerOrchestrationError`, `GeotizerGisError` |
| `project_evidence/retrieval.py` | `utils/geotizer_retrieval.py` | retrieval planning, evidence chains, locator identity |
| `project_evidence/semantics.py` | `utils/geotizer_semantics.py` | `geotizer_runtime_semantics.v0.2` row semantics (ADR-0020) |
| `project_evidence/resource_coherence.py` | `utils/geotizer_resource_coherence.py` | resource-estimate coherence |

Moved, not copied: the old paths are gone and every importer was rewired. A
compatibility shim would let a caller keep the old path indefinitely, and
`test_geotizer_import_boundary.py` asserts the old paths no longer exist.

`GeotizerGisError` was previously declared inside `tools/geotizer.py`, so the
Workspace-facing tool had to import the orchestration module in order to raise
a GIS failure. Both types now have exactly one declaration site, which
`test_geotizer_core_errors.py` pins.

Still to move: the 81 definitions in `utils/geotizer_orchestration.py`, split
per the classification between `project_evidence/`, `artifacts/geotizer/` and
the 11 mirrors that `gis_service` deletes.

## Where each definition is going

`GMM/operations/gt-conv-01/definition-classification.json` carries the target
module and a reason for all 131 definitions, and is validated in GMM's CI.
Read it before adding anything here.
