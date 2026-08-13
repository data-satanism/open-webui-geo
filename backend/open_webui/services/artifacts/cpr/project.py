"""Build a CPR requirement projection from a dossier.

CPR-SLICE-01 action 2. Every substantive statement keeps the claim ids and the
exact locators it rests on, and the narrative is never itself a source. This is
where that becomes structural: the projection carries ids, the dossier carries
values, and nothing in between invents a fact.

The map (`assets/cpr-slice-projection-map.v1.json`) says in advance what would
answer each of the slice's 74 requirements. Matching is by predicate, not by
text, so a requirement is answered when the dossier holds a claim of the kind
the CPR asked for -- and reported absent when it does not. There is no path
here that writes around a missing fact.

Where a reviewer already recorded the absence as a dossier gap, the projection
attaches *their* reason verbatim rather than composing a second one, and
carries the expert action the gap requires.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...project_evidence.claims import (
    LIVE_CLAIM_STATES,
    conflicts_over as _conflicts_over,
    granted_source_ids as _granted_source_ids,
    matching_claims,
    reviewed_gaps,
)
from .catalog import ASSETS, load_catalog, provenance
from .errors import CprContractError

MAP_FILE = 'cpr-slice-projection-map.v1.json'

RENDER_STATE = {
    'supported': 'rendered',
    'corroborated': 'rendered',
    'conflicted': 'rendered',
    'missing': 'rendered_with_gap',
    'blocked_expert': 'rendered_with_gap',
    'not_applicable': 'not_rendered',
}


@lru_cache(maxsize=4)
def _load_map(assets_key: str) -> dict[str, Any]:
    assets = Path(assets_key)
    recorded = provenance(assets).get('files', {}).get(MAP_FILE)
    if not recorded:
        raise CprContractError(f'{MAP_FILE} has no provenance record')
    path = assets / MAP_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CprContractError(f'CPR asset is missing: {MAP_FILE}') from exc
    if hashlib.sha256(raw).hexdigest() != recorded.get('sha256'):
        raise CprContractError(f'{MAP_FILE} does not match its recorded digest')
    document = json.loads(raw.decode('utf-8'))
    if document.get('catalog_version') != load_catalog(assets)['catalog_version']:
        raise CprContractError(f'{MAP_FILE} was built against a different catalog version')
    return document


def load_map(assets: Path | None = None) -> dict[str, Any]:
    return _load_map(str(assets or ASSETS))


def slice_requirement_ids(assets: Path | None = None) -> tuple[str, ...]:
    return tuple(entry['requirement_id'] for entry in load_map(assets)['entries'])


def _index(items: Sequence[Mapping[str, Any]] | None, key: str) -> dict[str, Mapping[str, Any]]:
    return {item[key]: item for item in items or ()}


def _matching_claims(dossier: Mapping[str, Any], entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return matching_claims(
        dossier,
        entry['predicates'],
        analogy_forbidden=entry['analogy_policy'] == 'forbidden',
    )


def _matching_estimates(
    dossier: Mapping[str, Any], entry: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]
) -> list[str]:
    kinds = set(entry['estimate_kinds'])
    if not kinds:
        return []
    # Only estimates a matched claim actually points at. An estimate nobody
    # cited is not evidence that a requirement was answered, and §10 forbids
    # sweeping incompatible categories together into one answer.
    cited = {claim.get('estimate_id') for claim in claims if claim.get('estimate_id')}
    return sorted(
        estimate['estimate_id']
        for estimate in dossier.get('estimates') or ()
        if estimate['estimate_id'] in cited and estimate.get('estimate_kind') in kinds
    )


def _matching_figures(
    dossier: Mapping[str, Any], entry: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]
) -> list[str]:
    kinds = set(entry['figure_kinds'])
    if not kinds:
        return []
    claim_ids = {claim['claim_id'] for claim in claims}
    return sorted(
        figure['figure_id']
        for figure in dossier.get('figures') or ()
        if figure.get('figure_kind') in kinds and claim_ids & set(figure.get('supports_claim_ids') or ())
    )


def _gaps_for(dossier: Mapping[str, Any], entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The reviewer's own records of this absence, if they made any."""
    return reviewed_gaps(dossier, entry['predicates'])


def _coverage_row(
    entry: Mapping[str, Any],
    requirement: Mapping[str, Any],
    dossier: Mapping[str, Any],
    stage: str,
) -> dict[str, Any]:
    applicable = stage in requirement['lifecycle_applicability']
    row: dict[str, Any] = {
        'requirement_id': entry['requirement_id'],
        'applicability': stage if applicable else 'not_applicable',
        'supporting_claim_ids': [],
        'supporting_estimate_ids': [],
        'supporting_figure_ids': [],
        'conflict_ids': [],
        'gap_ids': [],
        'expert_action_ids': [],
        'narrative_sentence_ids': [],
    }

    if not applicable:
        row['state'] = 'not_applicable'
        row['if_not_why_not'] = {
            'state': 'not_applicable',
            'reason_kind': 'stage_not_reached',
            'reason': (
                f'Требование применимо со стадии '
                f'{", ".join(requirement["lifecycle_applicability"])}; '
                f'объект на стадии {stage}.'
            ),
            'searched_source_ids': [],
            'decided_by_role': None,
        }
        row['render_state'] = RENDER_STATE['not_applicable']
        return row

    claims = _matching_claims(dossier, entry)
    if claims:
        row['supporting_claim_ids'] = sorted(claim['claim_id'] for claim in claims)
        row['supporting_estimate_ids'] = _matching_estimates(dossier, entry, claims)
        row['supporting_figure_ids'] = _matching_figures(dossier, entry, claims)
        conflicts = _conflicts_over(dossier, claims)
        if conflicts:
            row['state'] = 'conflicted'
            row['conflict_ids'] = conflicts
        elif all(claim['resolution_outcome'] == 'corroborated' for claim in claims) and len(claims) > 1:
            row['state'] = 'corroborated'
        else:
            row['state'] = 'supported'
        row['narrative_sentence_ids'] = [f'sent-{entry["requirement_id"]}-01']
        row['render_state'] = RENDER_STATE[row['state']]
        return row

    gaps = _gaps_for(dossier, entry)
    gap = gaps[0] if gaps else None
    if gap is not None:
        # The reviewer already wrote this absence down. Repeat their record
        # rather than composing a second one that could disagree with it.
        row['state'] = gap['if_not_why_not']['state']
        row['gap_ids'] = [item['gap_id'] for item in gaps]
        row['if_not_why_not'] = json.loads(json.dumps(gap['if_not_why_not']))
        if gap.get('required_expert_action_id'):
            row['expert_action_ids'] = [gap['required_expert_action_id']]
    elif entry['expert_interpretation']:
        # The catalog says this answer is a reading, not a source fact. No
        # amount of retrieval produces it.
        row['state'] = 'blocked_expert'
        row['if_not_why_not'] = {
            'state': 'blocked_expert',
            'reason_kind': 'expert_decision_required',
            'reason': (
                'Ответ на это требование является экспертной интерпретацией, '
                'а не фактом источника; автоматический артефакт его не формирует.'
            ),
            'searched_source_ids': _granted_source_ids(dossier),
            'decided_by_role': None,
        }
    else:
        row['state'] = 'missing'
        row['if_not_why_not'] = {
            'state': 'missing',
            'reason_kind': 'no_source_exists',
            'reason': (
                'Ни один доступный источник не содержит факта с предикатом ' + ', '.join(entry['predicates']) + '.'
            ),
            'searched_source_ids': _granted_source_ids(dossier),
            'decided_by_role': None,
        }

    if row['state'] in RENDER_STATE:
        row['render_state'] = RENDER_STATE[row['state']]
    if row['render_state'] != 'not_rendered':
        row['narrative_sentence_ids'] = [f'sent-{entry["requirement_id"]}-01']
    return row


def build_projection(
    dossier: Mapping[str, Any],
    *,
    assets: Path | None = None,
) -> dict[str, Any]:
    """The CPR requirement projection for the slice, from this dossier alone."""
    document = load_map(assets)
    catalog = {entry['id']: entry for entry in load_catalog(assets)['requirements']}
    stage = dossier['project_scope']['lifecycle_stage']

    coverage = []
    for entry in document['entries']:
        requirement = catalog.get(entry['requirement_id'])
        if requirement is None:
            raise CprContractError(f'{entry["requirement_id"]} is in the map and not in the catalog')
        coverage.append(_coverage_row(entry, requirement, dossier, stage))

    counts: dict[str, int] = {}
    for row in coverage:
        counts[row['state']] = counts.get(row['state'], 0) + 1

    return {
        'schema_version': 1,
        'dossier_run_id': dossier['dossier_run_id'],
        'projection_version': document['map_version'],
        'catalog_version': 'cpr_requirements.v1',
        # A slice by construction: it covers the 74 requirements the map names,
        # not the catalog's 126, so its totals are not a coverage measurement.
        'projection_scope': 'reference_slice',
        'catalog_requirement_count': len(catalog),
        'coverage': coverage,
        'totals': {
            'applicable': sum(1 for row in coverage if row['applicability'] != 'not_applicable'),
            'supported': counts.get('supported', 0),
            'corroborated': counts.get('corroborated', 0),
            'conflicted': counts.get('conflicted', 0),
            'missing': counts.get('missing', 0),
            'not_applicable': counts.get('not_applicable', 0),
            'blocked_expert': counts.get('blocked_expert', 0),
        },
    }


__all__ = [
    'LIVE_CLAIM_STATES',
    'MAP_FILE',
    'build_projection',
    'load_map',
    'slice_requirement_ids',
]
