# GeoTeaser code documentation

This directory documents the GeoTeaser code in `backend/open_webui/services/artifacts/geotizer/`, the adapter `backend/open_webui/tools/geotizer.py`, the download proxy `backend/open_webui/routers/geotizer.py`, the ASGI wrapper `backend/open_webui/asgi.py`, and the tests that guard them.

| Document | Contents |
| --- | --- |
| [workflow.md](workflow.md) | The single-object workflow: limits, chunking, the fill deadline, run identity and registry, deterministic GIS evidence, the owner attempt loop and the pass order. |
| [owner-envelope.md](owner-envelope.md) | The owner envelope: batch tasks, chunk merging, the source inventory, locators, the failure envelope and salvage, chunk provenance, and the owner prompt. |
| [refusal-passes.md](refusal-passes.md) | The passes that refuse or reclassify cells after the owner answers, their rules, reason constants and conflict handling. |
| [validation.md](validation.md) | The owner-envelope validation rules, the parity corpus, unsatisfiable-row exits, resource, subarea and plan rows. |
| [area.md](area.md) | The area request and area workflow: member resolution, concurrency and deadline, member states, progress lines and area artefacts. |
| [terminal.md](terminal.md) | Status lines, the result card, failure envelopes and artefact links. |
| [open-webui-integration.md](open-webui-integration.md) | The Workspace-tool adapter, the run scope sent to specialists, knowledge-search builtins, the artefact download proxy and its allowlist, the ASGI wrapper and the upstream seams. |
| [observability.md](observability.md) | Owner attempt diagnostics, the specialist round log, query recording, the run log sent to `finalize`, and the build revision. |
| [projection-and-evidence.md](projection-and-evidence.md) | The dossier projection onto the template fields and the shared project-evidence modules. |
| [tests.md](tests.md) | Repository guards the tests enforce, shared fixtures and test-module constants, and the tests that read source text. |
