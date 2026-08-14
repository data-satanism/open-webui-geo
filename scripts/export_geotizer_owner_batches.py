"""Export the dossier's answers in the shape GIS accepts, so it can render the workbook.

Expected result 9 of the assignment: "GeoTeaser XLSX from the same dossier, and
a projection trace for 351 fields". The trace exists. The workbook is rendered
by `gis_service`, which owns the state machine, the 108-row template and the
XLSX writer -- and which cannot read a dossier, by ADR-0006.

So this is the handoff, and it is the same handoff the live pipeline uses: the
projection decides *which* cell each fact answers and stays value-free; the
owner envelope carries the values. This writes that envelope from the frozen
dossier instead of from a model.

Two rules it keeps, because they are the point of the whole design:

  a filled cell carries the claim ids it came from, so the workbook is
  traceable back to the same evidence the CPR reads;

  an absent cell carries the dossier's own `if_not_why_not` reason, not a
  blank. `not_found` with a reason is a result; `not_found` with nothing is a
  placeholder, and §9 forbids the second.

Usage:
    PYTHONPATH=backend python scripts/export_geotizer_owner_batches.py [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402
from open_webui.services.project_evidence.claims import matching_claims  # noqa: E402

DOSSIER = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
DEFAULT_OUTPUT = REPO_ROOT / 'backend/tests/data/lekyn-owner-batches.json'

FILLED_STATES = ('supported', 'corroborated')
# A disputed fact is not a value. It reaches the workbook as `conflicted` with
# the dispute named, because writing one side of a conflict into a cell is the
# failure the estimate-identity work exists to prevent.
CONFLICTED = 'conflicted'

# The dossier's three absence states and the projection's conflict, each to the
# state machine's own name for the same thing. All four are in
# `ALLOWED_FIELD_STATUSES`, so collapsing them to `not_found` would not be a
# compatibility measure -- it would just throw away what the dossier decided.
# `not_applicable` in particular is a Domain Reviewer's ruling that the field
# does not apply at this stage; reported as `not_found` it becomes "we looked
# and did not find it", which is a different statement about the deposit.
ABSENCE_STATUS = {
    'missing': 'not_found',
    'not_applicable': 'not_applicable',
    'blocked_expert': 'requires_expert_review',
    'conflicted': 'conflicted',
}
DEFAULT_ABSENCE_STATUS = 'not_found'


def _claims(dossier: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {claim['claim_id']: claim for claim in dossier.get('claims') or ()}


def _value(
    claim: Mapping[str, Any], field: Mapping[str, Any], primary: str
) -> tuple[Any, str | None]:
    """This cell's value, not the whole fact the cell belongs to.

    A row is one fact with several facets, and the projection lets a
    mapping-valued claim answer several of them -- that is how one estimate
    fills a resource row's six cells. Returning `claim['value']` unchanged put
    the entire JSON object into every one of those cells and counted each as
    answered. The split is `gt_project.facet_value`, so the envelope and the
    projection cannot disagree about which part of a fact a cell holds.
    """
    return gt_project.facet_value(claim, field, primary), claim.get('unit')


def _scope(dossier: Mapping[str, Any], claims: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """What GIS needs to bind the run's scope, taken from the dossier.

    Only what the dossier actually holds. Anything GIS also needs and the
    dossier does not have is left out and reported by the renderer as stubbed,
    rather than filled in here where it would look like evidence.

    The licence id is load-bearing twice over -- it binds the object scope and
    it is what the state machine looks for in the authoritative source's title
    -- so it is the one value here that must not be guessed. This used to take
    the first `licence_number` claim in dictionary order, which meant a
    retracted claim could be chosen over a live one, and two sources disagreeing
    resolved to whichever came first. With one example dossier neither could
    happen; with customer documents both can.
    """
    live = matching_claims(dossier, ['licence_number'], analogy_forbidden=True)
    values = {json.dumps(claim.get('value'), ensure_ascii=False, sort_keys=True) for claim in live}
    disagreement = len(values) > 1
    return {
        'object_name': dossier['project_scope'].get('object_name'),
        'project_id': dossier['project_scope']['project_id'],
        # Disagreement leaves it absent. Binding a workbook's whole scope to one
        # side of an unresolved dispute is the estimate-identity failure, moved
        # from a cell to the run.
        'licence_id': live[0]['value'] if live and not disagreement else None,
        'licence_claim_ids': sorted(claim['claim_id'] for claim in live),
        'licence_disagreement': (
            sorted(json.loads(value) for value in values) if disagreement else None
        ),
    }


def _conflicts_with_nowhere_to_go(
    dossier: Mapping[str, Any], projection: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Conflicts the workbook cannot show, because no field carries them.

    A conflict the projection places becomes a `conflicted` cell and the reader
    sees the dispute. A conflict whose predicate has no template field becomes
    nothing at all: the rows it would have touched read `НЕ НАЙДЕНО`, which
    says the dossier holds no fact when in truth it holds two that disagree.
    That is a worse failure than an empty cell, so it is counted here rather
    than left to be noticed.
    """
    placed = {cid for row in projection['fields'] for cid in row.get('conflict_ids') or ()}
    stranded = []
    for conflict in dossier.get('conflicts') or ():
        if conflict['conflict_id'] in placed:
            continue
        stranded.append(
            {
                'conflict_id': conflict['conflict_id'],
                'kind': conflict.get('kind'),
                'claim_ids': list(conflict.get('claim_ids') or ()),
                'resolution': conflict.get('resolution'),
                'why_it_cannot_be_shown': (
                    'Ни одно поле шаблона не сопоставлено предикатам этих утверждений, '
                    'поэтому расхождение не попадает ни в одну ячейку.'
                ),
            }
        )
    return stranded


def build(dossier_path: Path = DOSSIER) -> dict[str, Any]:
    dossier = json.loads(dossier_path.read_text(encoding='utf-8'))
    claims = _claims(dossier)
    projection = gt_project.build_projection(dossier)

    by_key = {field['field_key']: field for field in gt_project.load_mapping()['fields']}
    primary = gt_project.primary_facets()

    fields = []
    for row in projection['fields']:
        supporting = [claims[cid] for cid in row['supporting_claim_ids'] if cid in claims]
        field = by_key[row['field_key']]
        value = unit = None
        if row['state'] in FILLED_STATES and supporting:
            value, unit = _value(supporting[0], field, primary[field['row_id']])
        if value is not gt_project.NO_FACET_VALUE and row['state'] in FILLED_STATES and supporting:
            fields.append(
                {
                    'field_key': row['field_key'],
                    'status': 'filled',
                    'value': value,
                    'unit': unit,
                    'claim_ids': row['supporting_claim_ids'],
                    'reason': None,
                }
            )
            continue

        absence = row.get('if_not_why_not') or {}
        reason = absence.get('reason')
        if value is gt_project.NO_FACET_VALUE:
            # The claim answers the row but names nothing for this facet. A
            # blank is the honest cell; the whole object would be a fabrication.
            reason = (
                f'Утверждение {", ".join(row["supporting_claim_ids"])} относится к строке, '
                f'но не содержит значения для грани «{field["facet"]}».'
            )
        if row['state'] == CONFLICTED:
            reason = f'Оценки расходятся; конфликт {", ".join(row["conflict_ids"])} не разрешён.'
        fields.append(
            {
                'field_key': row['field_key'],
                'status': ABSENCE_STATUS.get(row['state'], DEFAULT_ABSENCE_STATUS),
                'value': None,
                'unit': None,
                'claim_ids': row['supporting_claim_ids'],
                'reason': reason or 'Досье не содержит факта для этого поля.',
                'expert_approved_not_applicable': row.get('expert_approved_not_applicable'),
                'decided_by_role': absence.get('decided_by_role'),
            }
        )

    filled = [field for field in fields if field['status'] == 'filled']
    return {
        'schema_version': 1,
        'task': 'expected result 9: GeoTeaser XLSX from the same dossier',
        'dossier_run_id': dossier['dossier_run_id'],
        'frozen_at': dossier['frozen_at'],
        'frozen_inputs_hash': dossier['frozen_inputs_hash'],
        'projection_version': projection['projection_version'],
        'template_version': projection['template_version'],
        'template_field_count': projection['template_field_count'],
        'scope': _scope(dossier, claims),
        'totals': {
            'fields': len(fields),
            'filled': len(filled),
            'absent': len(fields) - len(filled),
            'by_status': {
                status: sum(1 for field in fields if field['status'] == status)
                for status in sorted({field['status'] for field in fields})
            },
            'filled_without_a_claim': sum(1 for field in filled if not field['claim_ids']),
            'absences_without_a_reason': sum(
                1 for field in fields if field['status'] != 'filled' and not field['reason']
            ),
        },
        'conflicts_no_field_can_show': _conflicts_with_nowhere_to_go(dossier, projection),
        'fields': fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    envelope = build()
    args.output.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=1) + '\n',
        encoding='utf-8',
    )
    totals = envelope['totals']
    by_status = ', '.join(f'{count} {status}' for status, count in totals['by_status'].items())
    print(
        f'{args.output.relative_to(REPO_ROOT)}: {totals["fields"]} field(s) — {by_status}; '
        f'{totals["filled_without_a_claim"]} filled without a claim, '
        f'{totals["absences_without_a_reason"]} absence(s) without a reason'
    )
    for conflict in envelope['conflicts_no_field_can_show']:
        # Loud, because the workbook will be silent about it.
        print(
            f'  WARNING: conflict {conflict["conflict_id"]} ({conflict["kind"]}) '
            f'reaches no cell of the template'
        )
    return 1 if totals['filled_without_a_claim'] or totals['absences_without_a_reason'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
