"""Project a dossier onto the 351 GeoTeaser fields.

GT-PROJ-01. The workbook stops being a second study and becomes a view of the
same evidence the CPR reads: every filled cell traces to a dossier claim or to
a calculation that was returned to the dossier as a typed claim, and there is
no third way into a cell.

`assets/cpr_to_geotizer_mapping.v1.json` holds the projection expression for
each field. The row is the unit of meaning -- one estimate fills a resource
row's six facets -- so matching happens per row and the facet only decides
which part of the fact the cell shows.

Action 4 forbids CPR narrative text as a source. Nothing here reads narrative:
the projection addresses claims, estimates and conflicts by id, and a field
with no matching fact is reported absent rather than filled from prose.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...geotizer.errors import GeotizerOrchestrationError

ASSETS = Path(__file__).resolve().parent / 'assets'
MAPPING_FILE = 'cpr_to_geotizer_mapping.v1.json'
PROVENANCE_FILE = 'provenance.json'

FROM_CLAIM = 'from_dossier_claim'
CALCULATED = 'artifact_specific_calculated'
ADVISORY = 'artifact_specific_advisory'
ARTIFACT_ONLY = 'ARTIFACT_SPECIFIC'

# A withdrawn source version leaves its claims here. Filling a cell from one
# would put a number in the workbook that the dossier no longer stands behind.
LIVE_CLAIM_STATES = frozenset({'active', 'conflict'})


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


def _predicates_for(field: Mapping[str, Any]) -> set[str]:
    return {field['predicate'], *(field.get('also_accepts') or ())}


def _answers_facet(claim: Mapping[str, Any], field: Mapping[str, Any], primary: str) -> bool:
    """Whether this claim answers *this cell*, not merely this row.

    A row is one fact with several facets, and a claim carries one value. If
    that value is a mapping, it answers the facets it names. If it is a scalar
    it answers the row's first facet and nothing else -- otherwise a claim
    holding only a stage would also fill the stage's start and end dates, and
    the workbook would report three answers where the dossier has one.

    A predicate registered under `also_accepts` answers the facet it was
    registered for, which is the whole reason it is listed on that field.
    """
    if claim['predicate'] in (field.get('also_accepts') or ()):
        return True
    value = claim.get('value')
    if isinstance(value, Mapping):
        return field['facet'] in value
    return field['facet'] == primary


def _matching_claims(dossier: Mapping[str, Any], field: Mapping[str, Any], primary: str) -> list[Mapping[str, Any]]:
    predicates = _predicates_for(field)
    analogy_forbidden = field['analogy_policy'] == 'forbidden'
    matched = []
    for claim in dossier.get('claims') or ():
        if claim.get('predicate') not in predicates:
            continue
        if claim.get('state') not in LIVE_CLAIM_STATES:
            continue
        if analogy_forbidden and claim['value_origin']['kind'] == 'analogy':
            continue
        if not _answers_facet(claim, field, primary):
            continue
        matched.append(claim)
    return matched


def _conflicts_over(dossier: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> list[str]:
    claim_ids = {claim['claim_id'] for claim in claims}
    return sorted(
        conflict['conflict_id']
        for conflict in dossier.get('conflicts') or ()
        if len(claim_ids & set(conflict.get('claim_ids') or ())) >= 2
    )


def _reviewed_gap(dossier: Mapping[str, Any], field: Mapping[str, Any]) -> Mapping[str, Any] | None:
    predicates = _predicates_for(field)
    for gap in dossier.get('gaps') or ():
        if predicates & set(gap.get('missing_predicates') or ()):
            return gap
    return None


def _approved_gap_ids(dossier: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        subject
        for decision in dossier.get('review_decisions') or ()
        if decision.get('decision') == 'marked_not_applicable'
        for subject in decision.get('subject_ids') or ()
    )


def _granted_source_ids(dossier: Mapping[str, Any]) -> list[str]:
    return sorted(
        source['source_id']
        for source in dossier.get('sources') or ()
        if source.get('acl_decision') == 'granted' and source.get('state') == 'active'
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
        elif len(claims) > 1 and all(claim['resolution_outcome'] == 'corroborated' for claim in claims):
            row['state'] = 'corroborated'
        else:
            row['state'] = 'supported'
        if field['projection_kind'] in {CALCULATED, ADVISORY}:
            # Action 3: an artefact-specific extra is computed once and comes
            # back as a typed claim. The cell reads that claim, so the value
            # exists in one place and can be audited.
            row['returned_claim_id'] = row['supporting_claim_ids'][0]
        return row

    gap = _reviewed_gap(dossier, field)
    if gap is not None:
        row['state'] = gap['if_not_why_not']['state']
        row['gap_ids'] = [gap['gap_id']]
        row['if_not_why_not'] = json.loads(json.dumps(gap['if_not_why_not']))
        if row['state'] == 'not_applicable':
            row['expert_approved_not_applicable'] = gap['gap_id'] in approved
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
        # The contract requires a returned claim for these kinds. Nothing was
        # computed, so the honest answer is that the cell is empty -- and the
        # projection says which claim it would have read.
        row['returned_claim_id'] = None
    return row


def build_projection(
    dossier: Mapping[str, Any],
    *,
    assets: Path | None = None,
    scope: str = 'complete',
) -> dict[str, Any]:
    """The GeoTeaser field projection for this dossier."""
    document = load_mapping(assets)
    approved = _approved_gap_ids(dossier)
    # The first attribute of a row carries the row's primary facet: a scalar
    # claim answers that cell and no other.
    primary = {field['row_id']: field['facet'] for field in document['fields'] if field['attribute_index'] == 1}
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
        # §9's denominator: 351 less only the expert-approved not_applicable.
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
    """Action 5: the run id, the projection version and the claim ids behind
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
    """Filled cells with no path back to a claim. The completion criterion says
    there are none, so this is what makes that checkable."""
    return tuple(
        row['field_key']
        for row in projection['fields']
        if row['state'] in {'supported', 'corroborated', 'conflicted'} and not row['supporting_claim_ids']
    )


__all__ = [
    'ASSETS',
    'LIVE_CLAIM_STATES',
    'MAPPING_FILE',
    'build_projection',
    'field_keys',
    'load_mapping',
    'projection_trace',
    'unsourced_fields',
]
