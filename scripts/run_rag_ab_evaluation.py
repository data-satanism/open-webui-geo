"""RAG-EVAL-01: measure the control arm, and show what the harness would reject.

A v2 shadow retriever exists -- `ENABLE_GEOMAS_RAG_V2_SHADOW` in
`utils/geotizer_rag_runtime.py` dispatches the plans a second time in the
background and appends one record per query to `GEOMAS_RAG_SHADOW_TRACE_DIR`.
It cannot produce the second arm this task needs, and the reason is by design:
it *"persists its result without exposing it to the GeoTeaser evidence"*, so it
shadows **queries**, never dossiers. This A/B compares dossiers. Producing a v2
arm means running the evidence pipeline on v2 retrieval and freezing a second
dossier, which needs the canary contour (register A-30) and a pinned index --
`.env.example` still carries `GEOMAS_RAG_V2_INDEX_VERSION=TODO_FROZEN_INDEX_VERSION`,
so "everything else held constant" is not yet demonstrable either.

So this run does two honest things instead of one dishonest one:

  1. It measures the **real** control arm: the Лекын dossier as v1 retrieval
     left it, both projections of it, and the decision that follows from having
     no second arm. That decision is `ITERATE`, and it is a real decision, not a
     placeholder: there is no evidence on which to promote anything.

  2. It runs the harness against **derived** arms, each one the control dossier
     with a single named mutation standing in for a way a v2 retriever could
     differ. Every derived arm is marked `synthetic: true` and carries the
     mutation that produced it. They demonstrate the rules; they are not
     measurements of any retriever.

The four measured axes of action 2 -- confirmed requirements, accepted claims
with exact locators, conflicts found, WEB share -- are real for the control arm.
Latency is not: `rag_ab.read_retrieval_trace` reads it from the shadow trace,
and there is no trace here, so it is recorded as unmeasured and blocks promotion
rather than being assumed good.

Usage:
    PYTHONPATH=backend python scripts/run_rag_ab_evaluation.py [--output PATH]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402
from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402
from open_webui.services.evaluation import rag_ab  # noqa: E402

DOSSIER = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
DEFAULT_OUTPUT = REPO_ROOT / 'backend/tests/data/lekyn-rag-ab-evidence.json'

CONTROL_ARM = 'v1'
SHADOW_ARM = 'v2-derived'

# A claim a shadow retriever could plausibly find that v1 did not: the regional
# geology section of the project report, which CPR-2.1.1 asks for and which the
# dossier currently reports as missing.
NEW_CLAIM = {
    'claim_id': 'clm-regional-geology',
    'subject_entity_id': 'ent-lekyn',
    'fact_kind': 'geology',
    'predicate': 'regional_geology',
    'value': 'Лекынская площадь в пределах Полярноуральской структурно-формационной зоны',
    'temporal_scope': {'kind': 'as_of', 'as_of': '2024-11-15'},
    'value_origin': {'kind': 'document', 'method': 'extraction'},
    'source_refs': ['src-project'],
    'source_locator': {
        'kind': 'document_span',
        'document_id': 'doc-project-2024',
        'document_version': '1',
        'page': 12,
        'section_path': '2.1',
        'quoted_text': 'Полярноуральская структурно-формационная зона',
    },
    'resolution_outcome': 'supported',
    'state': 'active',
}


def _projections(dossier: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return cpr_project.build_projection(dossier), gt_project.build_projection(dossier)


def _arm(name: str, dossier: Mapping[str, Any], *, latency_ms: int | None = None) -> rag_ab.Arm:
    cpr, geotizer = _projections(dossier)
    return rag_ab.measure(name, dossier, cpr, geotizer, latency_ms=latency_ms)


# -- the derived arms ------------------------------------------------------
#
# Each takes the control dossier and returns it changed in exactly one way.


def _drop_a_claim(dossier: dict[str, Any]) -> dict[str, Any]:
    dossier['claims'] = [c for c in dossier['claims'] if c['claim_id'] != 'clm-distance-road']
    return dossier


def _coarsen_a_locator(dossier: dict[str, Any]) -> dict[str, Any]:
    claim = next(c for c in dossier['claims'] if c['claim_id'] == 'clm-stage')
    claim['source_locator']['page'] = None
    return dossier


def _add_a_web_source(dossier: dict[str, Any]) -> dict[str, Any]:
    dossier['sources'].append(
        {
            'source_id': 'src-web',
            'project_id': dossier['project_scope']['project_id'],
            'title': 'Отраслевой веб-обзор',
            'source_type': 'web_page',
            'source_version': '2025-06-01',
            'authority_kind': 'approved_report',
            'acl_decision': 'granted',
            'state': 'active',
        }
    )
    claim = next(c for c in dossier['claims'] if c['claim_id'] == 'clm-stage')
    claim['source_refs'] = ['src-web']
    return dossier


def _find_new_evidence(dossier: dict[str, Any]) -> dict[str, Any]:
    dossier['claims'].append(copy.deepcopy(NEW_CLAIM))
    return dossier


def _unchanged(dossier: dict[str, Any]) -> dict[str, Any]:
    return dossier


SCENARIOS: tuple[tuple[str, str, Any, int | None, str], ...] = (
    (
        'a_claim_is_no_longer_retrieved',
        'v2 does not return clm-distance-road',
        _drop_a_claim,
        900,
        rag_ab.NO_GO,
    ),
    (
        'a_locator_is_coarsened',
        'v2 returns clm-stage without a page',
        _coarsen_a_locator,
        900,
        rag_ab.NO_GO,
    ),
    (
        'the_web_share_rises_for_nothing',
        'v2 re-sources clm-stage to a web page and confirms no more requirements',
        _add_a_web_source,
        900,
        rag_ab.NO_GO,
    ),
    (
        'absences_are_not_counted_as_misses',
        'v2 is identical to v1; the 69 recorded absences and 4 expert gaps are left standing',
        _unchanged,
        900,
        rag_ab.ITERATE,
    ),
    (
        'new_evidence_with_an_exact_locator',
        'v2 finds the regional geology section CPR-2.1.1 asks for',
        _find_new_evidence,
        900,
        rag_ab.GO_SHADOW_EXPANSION,
    ),
    (
        'the_same_gain_with_latency_unmeasured',
        'the same new evidence, with no latency figure for v2',
        _find_new_evidence,
        None,
        rag_ab.ITERATE,
    ),
)


def _cells_without_evidence(control: rag_ab.Arm, dossier: Mapping[str, Any]) -> dict[str, Any]:
    """The seventh case, which cannot be produced by changing the dossier.

    Filling a cell the evidence does not support is a projection defect, not a
    retrieval one, so it is made here by editing the workbook projection
    directly -- which is also the only way a cell-count-driven change could
    reach the artefact at all.
    """
    cpr, geotizer = _projections(dossier)
    mutated = copy.deepcopy(geotizer)
    row = next(r for r in mutated['fields'] if r['state'] == 'missing')
    row['state'] = 'supported'
    row['supporting_claim_ids'] = ['clm-stage']
    row['if_not_why_not'] = None

    shadow = rag_ab.measure(SHADOW_ARM, dossier, cpr, mutated, latency_ms=900)
    comparison = rag_ab.compare(control, shadow)
    return {
        'id': 'more_cells_without_more_evidence',
        'mutation': f'the workbook fills {row["field_key"]} without a new accepted claim',
        'synthetic': True,
        'expected_decision': rag_ab.NO_GO,
        'decision': comparison.decision,
        'harms': list(comparison.harms),
        'blockers': list(comparison.blockers),
        'gains': list(comparison.gains),
    }


def run(dossier_path: Path = DOSSIER) -> dict[str, Any]:
    dossier = json.loads(dossier_path.read_text(encoding='utf-8'))

    # The one real measurement in this file.
    control = _arm(CONTROL_ARM, dossier)
    live = rag_ab.compare(control, None)
    record = rag_ab.report(live)

    # The scenarios' control arm is given a latency so each one exercises the
    # rule it is about rather than all of them stopping on the same gap.
    measured_control = _arm(CONTROL_ARM, dossier, latency_ms=800)

    checks: list[dict[str, Any]] = []
    for name, mutation, mutate, latency, expected in SCENARIOS:
        shadow = _arm(SHADOW_ARM, mutate(copy.deepcopy(dossier)), latency_ms=latency)
        comparison = rag_ab.compare(measured_control, shadow)
        checks.append(
            {
                'id': name,
                'mutation': mutation,
                'synthetic': True,
                'expected_decision': expected,
                'decision': comparison.decision,
                'harms': list(comparison.harms),
                'blockers': list(comparison.blockers),
                'gains': list(comparison.gains),
            }
        )
    checks.append(_cells_without_evidence(measured_control, dossier))

    record.update(
        {
            'dossier_run_id': dossier['dossier_run_id'],
            'frozen_inputs_hash': dossier['frozen_inputs_hash'],
            'control_arm_is_a_real_measurement': True,
            'shadow_arm_was_run': False,
            'shadow_dispatcher_exists': True,
            'shadow_arm_absent_because': (
                'ENABLE_GEOMAS_RAG_V2_SHADOW shadows queries, not dossiers: it persists its '
                'result without exposing it to the evidence, so it produces no second dossier '
                'to compare. Building one needs the isolated canary contour, which is '
                'unrecoverable (attention register A-30), and a pinned index -- '
                'GEOMAS_RAG_V2_INDEX_VERSION is still TODO_FROZEN_INDEX_VERSION in .env.example'
            ),
            'latency_is_unmeasured_because': (
                'latency is read from the shadow dispatcher trace and no trace was produced '
                'here; an unmeasured axis blocks promotion rather than counting as good'
            ),
            'harness_checks': checks,
            'expert_review_matrix': [
                {
                    'id': 'shadow_run',
                    'owner': 'Runtime Owner',
                    'question': (
                        'Теневой диспетчер пишет трассу запросов, но не строит второе досье; '
                        'прогнать v2 на контуре и подать сюда второй рукав'
                    ),
                    'verdict': None,
                },
                {
                    'id': 'index_version',
                    'owner': 'Runtime Owner',
                    'question': (
                        'GEOMAS_RAG_V2_INDEX_VERSION = TODO_FROZEN_INDEX_VERSION: '
                        'зафиксировать версию индекса, иначе «всё прочее неизменно» недоказуемо'
                    ),
                    'verdict': None,
                },
                {
                    'id': 'web_source_recognition',
                    'owner': 'Ontology Approver',
                    'question': (
                        'В `authority_kind` нет значения для веб-источника; утвердить способ его распознавания'
                    ),
                    'verdict': None,
                },
                {
                    'id': 'promotion',
                    'owner': 'Runtime Owner',
                    'question': 'Перевод теневого поиска на живой трафик — решение человека',
                    'verdict': None,
                },
            ],
        }
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evidence = run()
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1, sort_keys=False) + '\n',
        encoding='utf-8',
    )

    mismatched = [
        check['id'] for check in evidence['harness_checks'] if check['decision'] != check['expected_decision']
    ]
    control = evidence['control']
    print(
        f'{args.output.relative_to(REPO_ROOT)}: decision {evidence["decision"]}, '
        f'{control["requirements"]["confirmed"]} confirmed requirement(s), '
        f'{control["claims"]["accepted"]} accepted claim(s), '
        f'locator precision {control["claims"]["locator_precision"]}, '
        f'WEB share {control["web"]["share"]}, '
        f'{len(evidence["harness_checks"])} harness check(s), '
        f'{len(mismatched)} mismatched'
    )
    return 1 if mismatched or evidence['decision'] not in rag_ab.DECISIONS else 0


if __name__ == '__main__':
    raise SystemExit(main())
