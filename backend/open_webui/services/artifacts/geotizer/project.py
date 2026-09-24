"""Project a dossier onto the 351 GeoTeaser fields.

Every filled cell traces to a dossier claim, or to a calculation returned to
the dossier as a typed claim. `assets/cpr_to_geotizer_mapping.v1.json` holds
the projection expression for each field. Matching happens per row, and the
facet decides which part of the fact a cell shows. The projection addresses
claims, estimates and conflicts by id and never reads CPR narrative text; a
field with no matching fact is reported absent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...geotizer.errors import GeotizerOrchestrationError
from ...project_evidence.claims import (
    LIVE_CLAIM_STATES,
    conflicts_over as _conflicts_over,
    granted_source_ids as _granted_source_ids,
    claims_agree_on_a_value,
    matching_claims,
    resolve_gap_state,
    reviewed_gaps,
)
from ...project_evidence.dossier import require_projectable

ASSETS = Path(__file__).resolve().parent / 'assets'
MAPPING_FILE = 'cpr_to_geotizer_mapping.v1.json'
PROVENANCE_FILE = 'provenance.json'

FROM_CLAIM = 'from_dossier_claim'
CALCULATED = 'artifact_specific_calculated'
ADVISORY = 'artifact_specific_advisory'

NO_FACET_VALUE = object()


def _provenance(assets: Path) -> dict[str, Any]:
    return json.loads((assets / PROVENANCE_FILE).read_text(encoding='utf-8'))


@lru_cache(maxsize=4)
def _load(assets_key: str) -> dict[str, Any]:
    assets = Path(assets_key)
    recorded = _provenance(assets).get('files', {}).get(MAPPING_FILE)
    if not recorded:
        raise GeotizerOrchestrationError(f'{MAPPING_FILE} has no provenance record')
    raw = (assets / MAPPING_FILE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != recorded.get('sha256'):
        raise GeotizerOrchestrationError(
            f'{MAPPING_FILE} does not match its recorded digest; the copy has '
            f'drifted from {recorded.get("source_repository")}'
        )
    document = json.loads(raw.decode('utf-8'))
    if len(document['fields']) != recorded.get('fields'):
        raise GeotizerOrchestrationError(f'{MAPPING_FILE} field count disagrees with provenance')
    return document


def load_mapping(assets: Path | None = None) -> dict[str, Any]:
    return _load(str(assets or ASSETS))


def field_keys(assets: Path | None = None) -> tuple[str, ...]:
    return tuple(field['field_key'] for field in load_mapping(assets)['fields'])


def primary_facets(assets: Path | None = None) -> dict[int, str]:
    """row_id -> the facet its first attribute carries.

    A scalar claim answers that cell and no other.
    """
    return {
        field['row_id']: field['facet']
        for field in load_mapping(assets)['fields']
        if field['attribute_index'] == 1
    }


def _predicates_for(field: Mapping[str, Any]) -> set[str]:
    return {field['predicate'], *(field.get('also_accepts') or ())}


def _answers_facet(claim: Mapping[str, Any], field: Mapping[str, Any], primary: str) -> bool:
    """Whether this claim answers *this cell*, not merely this row.

    A claim whose predicate the field lists in `also_accepts` answers it. A
    mapping value answers the facets it names. A scalar value answers the
    row's primary facet and nothing else.
    """
    if claim['predicate'] in (field.get('also_accepts') or ()):
        return True
    value = claim.get('value')
    if isinstance(value, Mapping):
        return field['facet'] in value
    return field['facet'] == primary


def facet_value(claim: Mapping[str, Any], field: Mapping[str, Any], primary: str) -> Any:
    """The part of a claim's value that belongs in *this* cell.

    A non-mapping value is returned whole; a mapping value returns its entry
    for this field's facet. Returns `NO_FACET_VALUE` when the mapping holds
    nothing for this facet, which the caller must report as an absence rather
    than guess at.
    """
    value = claim.get('value')
    if not isinstance(value, Mapping):
        return value
    if field['facet'] in value:
        return value[field['facet']]
    return NO_FACET_VALUE


def _matching_claims(dossier: Mapping[str, Any], field: Mapping[str, Any], primary: str) -> list[Mapping[str, Any]]:
    """Claims eligible for the field's predicates that also answer its facet.

    Eligibility is the shared `matching_claims` rule; `_answers_facet` is the
    GeoTeaser-only filter on top of it.
    """
    return [
        claim
        for claim in matching_claims(
            dossier,
            _predicates_for(field),
            analogy_forbidden=field['analogy_policy'] == 'forbidden',
        )
        if _answers_facet(claim, field, primary)
    ]


def _reviewed_gaps(dossier: Mapping[str, Any], field: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return reviewed_gaps(dossier, _predicates_for(field))


def _approved_gap_ids(dossier: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        subject
        for decision in dossier.get('review_decisions') or ()
        if decision.get('decision') == 'marked_not_applicable'
        for subject in decision.get('subject_ids') or ()
    )


def _field_row(
    field: Mapping[str, Any],
    dossier: Mapping[str, Any],
    approved: frozenset[str],
    primary_facet: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        'field_key': field['field_key'],
        'projection_kind': field['projection_kind'],
        'supporting_claim_ids': [],
        'supporting_estimate_ids': [],
        'conflict_ids': [],
        'gap_ids': [],
        'returned_claim_id': None,
        'fallback_rule': field.get('fallback_rule'),
        'if_not_why_not': None,
        'expert_approved_not_applicable': None,
    }

    claims = _matching_claims(dossier, field, primary_facet)
    if claims:
        row['supporting_claim_ids'] = sorted(claim['claim_id'] for claim in claims)
        if field.get('estimate_backed'):
            row['supporting_estimate_ids'] = sorted(
                {claim['estimate_id'] for claim in claims if claim.get('estimate_id')}
            )
        conflicts = _conflicts_over(dossier, claims)
        if conflicts:
            row['state'] = 'conflicted'
            row['conflict_ids'] = conflicts
        elif (
            len(claims) > 1
            and all(claim['resolution_outcome'] == 'corroborated' for claim in claims)
            and claims_agree_on_a_value(claims)
        ):
            row['state'] = 'corroborated'
        else:
            row['state'] = 'supported'
        if field['projection_kind'] in {CALCULATED, ADVISORY}:
            row['returned_claim_id'] = row['supporting_claim_ids'][0]
        return row

    gaps = _reviewed_gaps(dossier, field)
    gap = gaps[0] if gaps else None
    if gap is not None:
        state, reviewers_disagree = resolve_gap_state(gaps)
        row['state'] = state
        row['gap_ids'] = [item['gap_id'] for item in gaps]
        row['if_not_why_not'] = json.loads(json.dumps(gap['if_not_why_not']))
        if reviewers_disagree:
            row['if_not_why_not']['state'] = state
            row['if_not_why_not']['reason_kind'] = 'expert_decision_required'
            row['if_not_why_not']['reason'] = (
                'Рецензенты записали разные причины отсутствия для этого поля ('
                + ', '.join(f'{g["gap_id"]}: {g["if_not_why_not"]["state"]}' for g in gaps)
                + '); какая из них относится к этой ячейке, решает эксперт.'
            )
        if row['state'] == 'not_applicable':
            row['expert_approved_not_applicable'] = all(
                item['gap_id'] in approved for item in gaps
            )
        return row

    row['state'] = 'missing'
    if field['cpr_derivable'] is False:
        reason = f'{field["outside_cpr_reason"]}. Значение не получено: {field["fallback_rule"]}.'
        reason_kind = 'no_source_exists'
    else:
        reason = (
            'Ни один доступный источник не содержит факта с предикатом '
            + ', '.join(sorted(_predicates_for(field)))
            + '.'
        )
        reason_kind = 'no_source_exists'
    row['if_not_why_not'] = {
        'state': 'missing',
        'reason_kind': reason_kind,
        'reason': reason,
        'searched_source_ids': _granted_source_ids(dossier),
        'decided_by_role': None,
    }
    if field['projection_kind'] in {CALCULATED, ADVISORY}:
        row['returned_claim_id'] = None
    return row


def build_projection(
    dossier: Mapping[str, Any],
    *,
    assets: Path | None = None,
    scope: str = 'complete',
) -> dict[str, Any]:
    """The GeoTeaser field projection for this dossier."""
    require_projectable(dossier)
    document = load_mapping(assets)
    approved = _approved_gap_ids(dossier)
    primary = primary_facets(assets)
    fields = [_field_row(field, dossier, approved, primary[field['row_id']]) for field in document['fields']]

    answered = sum(1 for row in fields if row['state'] in {'supported', 'corroborated'})
    approved_na = sum(1 for row in fields if row['expert_approved_not_applicable'])
    projected = sum(1 for row in fields if row['projection_kind'] == FROM_CLAIM)

    totals: dict[str, Any] = {
        'fields': len(fields),
        'projected': projected,
        'artifact_specific': len(fields) - projected,
        'expert_approved_not_applicable': approved_na,
    }
    if scope == 'complete':
        denominator = len(document['fields']) - approved_na
        totals['semantic_completeness_percent'] = round(100.0 * answered / denominator, 2) if denominator else 0.0

    return {
        'schema_version': 1,
        'dossier_run_id': dossier['dossier_run_id'],
        'projection_version': document['mapping_version'],
        'template_version': document['template_version'],
        'projection_scope': scope,
        'template_field_count': len(document['fields']),
        'fields': fields,
        'totals': totals,
    }


def projection_trace(projection: Mapping[str, Any], dossier: Mapping[str, Any]) -> dict[str, Any]:
    """The run id, the projection version and the claim ids behind
    every filled cell, in one record that travels with the workbook."""
    filled = [row for row in projection['fields'] if row['state'] in {'supported', 'corroborated', 'conflicted'}]
    return {
        'schema_version': 1,
        'dossier_run_id': projection['dossier_run_id'],
        'projection_version': projection['projection_version'],
        'template_version': projection['template_version'],
        'frozen_at': dossier['frozen_at'],
        'frozen_inputs_hash': dossier['frozen_inputs_hash'],
        'filled_fields': len(filled),
        'entries': [
            {
                'field_key': row['field_key'],
                'state': row['state'],
                'claim_ids': row['supporting_claim_ids'],
                'estimate_ids': row['supporting_estimate_ids'],
                'conflict_ids': row['conflict_ids'],
                'returned_claim_id': row['returned_claim_id'],
            }
            for row in filled
        ],
    }


def unsourced_fields(projection: Mapping[str, Any]) -> tuple[str, ...]:
    """Filled cells with no supporting claim id."""
    return tuple(
        row['field_key']
        for row in projection['fields']
        if row['state'] in {'supported', 'corroborated', 'conflicted'} and not row['supporting_claim_ids']
    )


__all__ = [
    'ASSETS',
    'NO_FACET_VALUE',
    'facet_value',
    'primary_facets',
    'LIVE_CLAIM_STATES',
    'MAPPING_FILE',
    'build_projection',
    'field_keys',
    'load_mapping',
    'projection_trace',
    'unsourced_fields',
]
