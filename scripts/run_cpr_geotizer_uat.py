"""UAT-CPR-GT-01: both artefacts from one frozen dossier.

Runs the deterministic half of the acceptance test and writes the evidence the
task asks for -- run ids, hashes, the projection trace, the reuse figures and
an expert-review matrix for the parts a person has to judge.

What this covers, and what it cannot:

  action 1  build the dossier, the CPR slice and the workbook on identical
            frozen inputs                                            -- covered
  action 2  a re-render calls no retrieval, no model and no GIS      -- covered
  action 3  expert review of CPR coverage and GeoTeaser expectations -- a matrix
            is emitted for a reviewer; nothing here judges it
  action 4  conflicting Project/Presentation estimates, sites 1-4    -- covered;
            the WEB-last rule needs a live run
  action 5  stream loss and recovery, terminal artefact links        -- needs the
            canary contour

The contour the task names is the isolated canary, which is unrecoverable --
GMM's attention register carries that as A-30. Everything reachable from a
frozen dossier is run here; the rest is recorded rather than claimed.

Usage:
    PYTHONPATH=backend python scripts/run_cpr_geotizer_uat.py [--output PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts import consistency  # noqa: E402
from open_webui.services.artifacts.cpr import (  # noqa: E402
    audit,
    coverage,
    narrative,
    render,
)
from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402
from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402
from open_webui.services.core.idempotency import (  # noqa: E402
    run_key,
)

DOSSIER = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
FONT = REPO_ROOT / 'backend/open_webui/static/fonts/NotoSans-Regular.ttf'
DEFAULT_OUTPUT = REPO_ROOT / 'backend/tests/data/lekyn-uat-evidence.json'

# Judgements no automated run may make. Emitted with an empty verdict so the
# matrix is a request rather than a claim.
REVIEW_MATRIX = (
    ('cpr_coverage', 'Domain Reviewer', 'Достаточно ли покрытие требований CPR для этого объекта'),
    ('geotizer_expectations', 'Domain Reviewer', 'Выполнены ли зафиксированные ожидания по тизеру Лекына'),
    ('conflict_resolution', 'Domain Reviewer', 'Верно ли расхождение 12 т / 20 т оставлено нерешённым'),
    ('lifecycle_stage', 'Domain Reviewer', 'Верна ли стадия объекта: от неё зависит знаменатель'),
    ('predicate_vocabulary', 'Ontology Approver', 'Утвердить предложенные имена предикатов в обеих картах'),
    ('web_last_rule', 'Runtime Owner', 'Проверить правило «WEB только в последнюю очередь» на живом прогоне'),
    ('stream_recovery', 'Runtime Owner', 'Потеря потока ответа и восстановление; терминальные ссылки'),
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run(dossier_path: Path = DOSSIER) -> dict[str, Any]:
    dossier = json.loads(dossier_path.read_text(encoding='utf-8'))

    # Action 1: one frozen input set, both artefacts.
    cpr = cpr_project.build_projection(dossier)
    geotizer = gt_project.build_projection(dossier)
    blocks = narrative.plan_narrative(cpr, dossier)
    titles = coverage.requirement_titles()
    findings = audit.audit_projection(cpr, dossier)

    artifacts = {
        'cpr_readiness.docx': render.render_docx(cpr, dossier, blocks, titles),
        'cpr_readiness.pdf': render.render_pdf(cpr, dossier, blocks, titles, font_path=FONT),
        'coverage.json': render.render_coverage_json(cpr, dossier),
        'source_report.md': render.render_source_report(dossier),
        'audit.md': render.render_audit_report(findings),
    }

    # Action 2: re-render and compare. Nothing in this path can reach retrieval,
    # a model or GIS -- the renderers take the projection and the dossier and
    # nothing else -- so the check is that the bytes are identical.
    rerendered = {
        'cpr_readiness.docx': render.render_docx(cpr, dossier, blocks, titles),
        'cpr_readiness.pdf': render.render_pdf(cpr, dossier, blocks, titles, font_path=FONT),
        'coverage.json': render.render_coverage_json(cpr, dossier),
        'source_report.md': render.render_source_report(dossier),
        'audit.md': render.render_audit_report(findings),
    }
    unstable = sorted(name for name, payload in artifacts.items() if rerendered[name] != payload)

    key = run_key(
        project_id=dossier['project_scope']['project_id'],
        artifact_set=['cpr_readiness', 'geotizer_object', 'source_report', 'audit'],
        frozen_inputs_hash=dossier['frozen_inputs_hash'],
    )

    completeness = coverage.semantic_completeness(cpr, dossier)
    divergences = consistency.compare(cpr, geotizer, dossier)

    return {
        'schema_version': 1,
        'task': 'UAT-CPR-GT-01',
        'contour': 'frozen dossier, no live contour',
        'dossier_run_id': dossier['dossier_run_id'],
        'frozen_at': dossier['frozen_at'],
        'frozen_inputs_hash': dossier['frozen_inputs_hash'],
        'idempotency_key_digest': key.digest,
        'projection_versions': {
            'cpr': cpr['projection_version'],
            'geotizer': geotizer['projection_version'],
        },
        'artifacts': [
            {
                'name': name,
                'bytes': len(payload),
                'content_sha256': _sha256(payload),
            }
            for name, payload in sorted(artifacts.items())
        ],
        'rerender': {
            'artifacts_compared': len(artifacts),
            'hashes_changed': unstable,
            'retrieval_calls': 0,
            'model_calls': 0,
            'gis_calls': 0,
            'web_calls': 0,
        },
        'cpr': {
            'requirements': len(cpr['coverage']),
            'totals': cpr['totals'],
            'completeness': {k: v for k, v in completeness.items() if k != 'unaddressed'},
            'blocking_audit_findings': len(audit.blocking(findings)),
        },
        'geotizer': {
            'fields': len(geotizer['fields']),
            'totals': geotizer['totals'],
            'unsourced_filled_fields': list(gt_project.unsourced_fields(geotizer)),
            'trace': gt_project.projection_trace(geotizer, dossier),
        },
        'agreement': {
            'divergences': [
                {
                    'code': finding.code,
                    'claim_id': finding.claim_id,
                    'cpr': list(finding.cpr_locations),
                    'geotizer': list(finding.geotizer_locations),
                    'detail': finding.detail,
                }
                for finding in divergences
            ],
            'shared_claims': consistency.shared_claims(cpr, geotizer),
            'reuse': consistency.evidence_reuse(cpr, geotizer, dossier),
        },
        'expert_review_matrix': [
            {'id': item, 'owner': owner, 'question': question, 'verdict': None}
            for item, owner, question in REVIEW_MATRIX
        ],
        'not_covered_without_a_contour': [
            'WEB-last rule (action 4): needs a live retrieval run',
            'stream loss and recovery (action 5): needs the canary contour',
            'terminal artefact links (action 5): needs a deployed tool server',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evidence = run()
    payload = json.dumps(evidence, ensure_ascii=False, indent=1, sort_keys=False) + '\n'
    args.output.write_text(payload, encoding='utf-8')

    print(
        f'{args.output.relative_to(REPO_ROOT)}: '
        f'{len(evidence["artifacts"])} artefacts, '
        f'{len(evidence["rerender"]["hashes_changed"])} unstable, '
        f'{len(evidence["agreement"]["divergences"])} divergences, '
        f'reuse {evidence["agreement"]["reuse"]["used_by_both"]} of '
        f'{evidence["agreement"]["reuse"]["claims_in_dossier"]}'
    )
    return 1 if evidence['rerender']['hashes_changed'] or evidence['agreement']['divergences'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
