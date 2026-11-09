"""CUST-DEPLOY-01: do the artefacts still reproduce from the release manifest?

The completion criterion says every artefact reproduces from the manifest. That
is a claim about *this* repository at the manifest's pinned commit, so it can
only be checked here -- GMM holds the manifest, but the renderers live in
`open_webui.services.artifacts`.

This is the deployer's check, and the one to run on the customer contour before
anything is published from it. It re-renders the CPR artefacts from the frozen
dossier and compares each digest with the one the manifest recorded. A mismatch
means the contour would produce a different document from the same evidence,
which is the failure the whole dossier design exists to make impossible.

The manifest path is required and has no default. This repository's CI has no
GMM checkout, so a default would be a path that silently does not exist; the
tests exercise the comparison against a manifest built from the local run.

Usage:
    PYTHONPATH=backend python scripts/verify_release_artifacts.py \\
        --manifest ../GMM/operations/deployments/2026-08-12__cust-deploy-01-release-package.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.cpr import audit, coverage, narrative, render  # noqa: E402
from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402

DOSSIER = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
FONT = REPO_ROOT / 'backend/open_webui/static/fonts/NotoSans-Regular.ttf'


def rebuild(dossier_path: Path = DOSSIER) -> dict[str, bytes]:
    """The five artefacts, re-rendered from the frozen dossier."""
    dossier = json.loads(dossier_path.read_text(encoding='utf-8'))
    projection = cpr_project.build_projection(dossier)
    blocks = narrative.plan_narrative(projection, dossier)
    titles = coverage.requirement_titles()
    findings = audit.audit_projection(projection, dossier)

    return {
        'cpr_readiness.docx': render.render_docx(projection, dossier, blocks, titles),
        'cpr_readiness.pdf': render.render_pdf(projection, dossier, blocks, titles, font_path=FONT),
        'coverage.json': render.render_coverage_json(projection, dossier),
        'source_report.md': render.render_source_report(dossier),
        'audit.md': render.render_audit_report(findings),
    }


def compare(manifest: Mapping[str, Any], rebuilt: Mapping[str, bytes]) -> list[str]:
    """Every way the contour could produce something the manifest did not pin."""
    problems: list[str] = []
    recorded = {artifact['name']: artifact for artifact in manifest.get('artifacts') or ()}

    for name in sorted(set(recorded) | set(rebuilt)):
        entry = recorded.get(name)
        payload = rebuilt.get(name)
        if entry is None:
            problems.append(f'{name}: rebuilt but not pinned by the manifest')
            continue
        if payload is None:
            problems.append(f'{name}: pinned by the manifest but not rebuilt')
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry['content_sha256']:
            problems.append(f'{name}: rebuilt digest {digest[:12]} against manifest {entry["content_sha256"][:12]}')
        elif len(payload) != entry['bytes']:
            problems.append(f'{name}: {len(payload)} bytes against manifest {entry["bytes"]}')

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    problems = compare(manifest, rebuild())

    if problems:
        print(f'{args.manifest}: the contour does not reproduce the pinned artefacts')
        for problem in problems:
            print(f'  ERROR: {problem}')
        return 1

    print(f'{args.manifest}: {len(manifest["artifacts"])} artefact(s) reproduce, package {manifest["package_id"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
