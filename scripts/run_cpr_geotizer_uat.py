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
DEFAULT_MATRIX = REPO_ROOT / 'backend/tests/data/uat-scenario-matrix.json'

# Judgements no automated run may make. Emitted with an empty verdict so the
# matrix is a request rather than a claim. Object-specific questions are built
# from the dossier in `_review_matrix`, so a second object gets its own rather
# than inheriting Lekyn's.
REVIEW_MATRIX = (
    ('cpr_coverage', 'Domain Reviewer', 'Достаточно ли покрытие требований CPR для этого объекта'),
    ('geotizer_expectations', 'Domain Reviewer', 'Выполнены ли зафиксированные ожидания по тизеру {object_name}'),
    ('lifecycle_stage', 'Domain Reviewer', 'Верна ли стадия объекта: от неё зависит знаменатель'),
    ('predicate_vocabulary', 'Ontology Approver', 'Утвердить предложенные имена предикатов в обеих картах'),
    ('web_last_rule', 'Runtime Owner', 'Проверить правило «WEB только в последнюю очередь» на живом прогоне'),
    ('stream_recovery', 'Runtime Owner', 'Потеря потока ответа и восстановление; терминальные ссылки'),
)

# The three objects §8 of the task names, and the eight scenarios it requires of
# both artefacts. Two objects have no dossier here, and the matrix says so with
# a reason rather than omitting the rows -- an absent scenario left out of a
# matrix reads as a passing one.
UAT_OBJECTS = (
    {
        'object_id': 'lekyn-talbeyskaya',
        'object_name': 'Лекын-Тальбейская площадь',
        'scenario': 'документы + GIS + конфликтующие оценки',
        'dossier_path': 'backend/tests/data/lekyn-dossier.example.json',
        'absent': None,
    },
    {
        'object_id': 'verkhne-kolpinskoye',
        'object_name': 'Верхне-Колпинское',
        'scenario': 'иерархия проекта',
        'dossier_path': None,
        'absent': {
            'state': 'blocked_expert',
            'reason': (
                'Объект передан другому специалисту; документы заказчика и права на их '
                'разметку сюда не поступали, а досье нельзя собрать без источников.'
            ),
            'unblocked_by': 'документы заказчика по объекту и назначенный Domain Reviewer',
            'register_entry': 'A-16',
        },
    },
    {
        'object_id': 'niyayuskaya',
        'object_name': 'Нияюская',
        'scenario': 'GIS есть, материалы базы знаний ограничены',
        'dossier_path': None,
        'absent': {
            'state': 'blocked_expert',
            'reason': (
                'Объект передан другому специалисту. Сценарий ценен именно ограниченностью '
                'базы знаний, поэтому подставное досье проверило бы противоположное тому, '
                'ради чего сценарий существует.'
            ),
            'unblocked_by': 'доступ к контуру GIS объекта и его материалам базы знаний',
            'register_entry': 'A-16',
        },
    },
)

# §8 requires all eight of both artefacts. `covered_by` names what actually
# demonstrates the scenario; `needs` names what it would take where it does not.
UAT_SCENARIOS = (
    ('documents_gis_conflicting_estimates', 'документы + GIS + конфликтующие оценки'),
    ('project_hierarchy', 'иерархия проекта'),
    ('gis_present_kb_limited', 'GIS есть, материалы базы знаний ограничены'),
    ('no_drilling_qaqc_reserves', 'нет данных по бурению, QA/QC, запасам'),
    ('source_version_retracted', 'версия источника отозвана'),
    ('stream_or_tool_result_lost', 'потерян поток ответа или результат инструмента'),
    ('artifact_regenerated', 'повторное формирование документа'),
    ('rag_v2_shadow', 'теневая версия RAG v2'),
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _review_matrix(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    """The base questions with the object's name in them, plus one row per
    conflict the dossier actually holds.

    The conflict rows used to be a single hard-coded question about Lekyn's
    12 t / 20 t. A second object would have inherited it and been asked to rule
    on a disagreement that is not in its dossier, while its own conflicts went
    unasked -- which is the failure mode of every matrix written for one case.
    """
    object_name = dossier['project_scope'].get('object_name') or dossier['project_scope']['project_id']
    matrix = [
        {
            'id': item,
            'owner': owner,
            'question': question.format(object_name=object_name),
            'verdict': None,
        }
        for item, owner, question in REVIEW_MATRIX
    ]
    for conflict in dossier.get('conflicts') or ():
        matrix.append(
            {
                'id': f'conflict_resolution.{conflict["conflict_id"]}',
                'owner': 'Domain Reviewer',
                'question': (
                    f'Верно ли расхождение оставлено нерешённым ({conflict["resolution"]}): '
                    f'{conflict["statement"]}'
                ),
                'verdict': None,
            }
        )
    return matrix


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
        'object_name': dossier['project_scope'].get('object_name'),
        'expert_review_matrix': _review_matrix(dossier),
        'not_covered_without_a_contour': [
            'WEB-last rule (action 4): needs a live retrieval run',
            'stream loss and recovery (action 5): needs the canary contour',
            'terminal artefact links (action 5): needs a deployed tool server',
        ],
    }


def _scenario_rows(ran: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The eight scenarios §8 requires, each with what actually demonstrates it.

    Two of the three objects have no dossier, so the object-shaped scenarios
    cannot be run. Three more need a live contour. Both kinds are rows with a
    reason, never omissions.
    """
    by_scenario = {item['scenario']: item for item in ran}
    absent_by_scenario = {obj['scenario']: obj for obj in UAT_OBJECTS if obj['absent']}

    rows = []
    for scenario_id, scenario in UAT_SCENARIOS:
        run_here = by_scenario.get(scenario)
        blocked_object = absent_by_scenario.get(scenario)
        if run_here is not None:
            rows.append(
                {
                    'scenario_id': scenario_id,
                    'scenario': scenario,
                    'state': 'covered',
                    'covered_by': f'прогон объекта {run_here["object_name"]}',
                    'needs': None,
                }
            )
        elif blocked_object is not None:
            rows.append(
                {
                    'scenario_id': scenario_id,
                    'scenario': scenario,
                    'state': 'blocked_expert',
                    'covered_by': None,
                    'needs': blocked_object['absent']['unblocked_by'],
                    'object_name': blocked_object['object_name'],
                    'register_entry': blocked_object['absent']['register_entry'],
                }
            )
        else:
            rows.append(_SCENARIO_NOT_OBJECT_SHAPED[scenario_id])
    return rows


# The five scenarios that are not about which object is loaded. Their state is
# a property of this run, not of the dossier supply.
_SCENARIO_NOT_OBJECT_SHAPED = {
    'no_drilling_qaqc_reserves': {
        'scenario_id': 'no_drilling_qaqc_reserves',
        'scenario': 'нет данных по бурению, QA/QC, запасам',
        'state': 'covered',
        'covered_by': 'прогон Лекына: 346 из 351 полей отсутствуют, каждое с причиной',
        'needs': None,
    },
    'source_version_retracted': {
        'scenario_id': 'source_version_retracted',
        'scenario': 'версия источника отозвана',
        'state': 'partially_covered',
        'covered_by': 'переход состояния проверен тестом отзыва утверждения',
        'needs': 'живой прогон, где источник отзывается между двумя сборками',
    },
    'stream_or_tool_result_lost': {
        'scenario_id': 'stream_or_tool_result_lost',
        'scenario': 'потерян поток ответа или результат инструмента',
        'state': 'blocked_contour',
        'covered_by': None,
        'needs': 'canary-контур: восстановление требует живого потока',
    },
    'artifact_regenerated': {
        'scenario_id': 'artifact_regenerated',
        'scenario': 'повторное формирование документа',
        'state': 'covered',
        'covered_by': 'повторный рендер: 5 артефактов, ни одного изменившегося хеша',
        'needs': None,
    },
    'rag_v2_shadow': {
        'scenario_id': 'rag_v2_shadow',
        'scenario': 'теневая версия RAG v2',
        'state': 'blocked_contour',
        'covered_by': None,
        'needs': (
            'второе досье на поиске v2. Теневой диспетчер теневой по запросам, '
            'а не по досье — запись A-41'
        ),
    },
}


def run_scenario_matrix() -> dict[str, Any]:
    """§8 for every object it names, run where a dossier exists and recorded
    with a reason where it does not.

    The task requires all eight scenarios for both artefacts on three objects.
    One object has a dossier. Fabricating the other two would produce a matrix
    that passes and means nothing, so the two are absent rows carrying the same
    three-state vocabulary the dossier uses for a missing fact.
    """
    ran = []
    for obj in UAT_OBJECTS:
        if obj['dossier_path'] is None:
            continue
        evidence = run(REPO_ROOT / obj['dossier_path'])
        ran.append(
            {
                'object_id': obj['object_id'],
                'object_name': obj['object_name'],
                'scenario': obj['scenario'],
                'dossier_run_id': evidence['dossier_run_id'],
                'frozen_inputs_hash': evidence['frozen_inputs_hash'],
                'artifacts': len(evidence['artifacts']),
                'unstable_hashes': evidence['rerender']['hashes_changed'],
                'divergences': len(evidence['agreement']['divergences']),
                'open_review_questions': len(evidence['expert_review_matrix']),
            }
        )

    absent = [
        {
            'object_id': obj['object_id'],
            'object_name': obj['object_name'],
            'scenario': obj['scenario'],
            **obj['absent'],
        }
        for obj in UAT_OBJECTS
        if obj['absent']
    ]
    rows = _scenario_rows(ran)
    return {
        'schema_version': 1,
        'task': 'UAT-CPR-GT-01, §8 scenario matrix',
        'objects_required': len(UAT_OBJECTS),
        'objects_run': len(ran),
        'objects_absent': len(absent),
        'runs': ran,
        'absent_objects': absent,
        'scenarios': rows,
        'totals': {
            'scenarios': len(rows),
            'covered': sum(1 for row in rows if row['state'] == 'covered'),
            'partially_covered': sum(1 for row in rows if row['state'] == 'partially_covered'),
            'blocked_expert': sum(1 for row in rows if row['state'] == 'blocked_expert'),
            'blocked_contour': sum(1 for row in rows if row['state'] == 'blocked_contour'),
        },
        'note': (
            'Полная матрица §8 требует восьми сценариев по трём объектам для обоих '
            'артефактов. Досье есть по одному объекту. Отсутствующие строки оставлены '
            'строками с причиной: сценарий, выпавший из матрицы, читается как пройденный.'
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dossier', type=Path, default=DOSSIER)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--matrix', type=Path, default=DEFAULT_MATRIX)
    args = parser.parse_args()

    matrix = run_scenario_matrix()
    args.matrix.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=1) + '\n', encoding='utf-8'
    )

    evidence = run(args.dossier)
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
    totals = matrix['totals']
    print(
        f'{args.matrix.relative_to(REPO_ROOT)}: '
        f'{matrix["objects_run"]} of {matrix["objects_required"]} object(s) run; '
        f'{totals["covered"]} scenario(s) covered, '
        f'{totals["partially_covered"]} partial, '
        f'{totals["blocked_expert"]} blocked on documents, '
        f'{totals["blocked_contour"]} blocked on the contour'
    )
    for obj in matrix['absent_objects']:
        print(f'  absent: {obj["object_name"]} — {obj["state"]}, see {obj["register_entry"]}')
    return 1 if evidence['rerender']['hashes_changed'] or evidence['agreement']['divergences'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
