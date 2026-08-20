"""Fail-closed coherence guard for structured GeoTeaser resource proposals."""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.vocabulary import _is_empty_finding


RESOURCE_ROW_PATTERN = re.compile(r'^geotizer_object\.v1\.r(04[4-9]|05[0-6])\.a\d+$')
CALCULATED_VALUE_LABEL = 'РАСЧЕТНОЕ ЗНАЧЕНИЕ'


def _resource_row(field_key: str) -> str | None:
    match = RESOURCE_ROW_PATTERN.match(field_key)
    return f'r{match.group(1)}' if match else None


@dataclass(frozen=True)
class ResourceEstimateRecord:
    """Minimum identity needed to keep attributes of one estimate together."""

    field_key: str
    row: str
    estimate_id: str
    relation_to_object: str
    value_origin: str
    estimate_state: str
    entity_id: str
    site_name: str

    @classmethod
    def from_proposal(
        cls,
        proposal: Mapping[str, Any],
    ) -> ResourceEstimateRecord | None:
        field_key = str(proposal.get('field_key') or '')
        row = _resource_row(field_key)
        estimate_id = str(proposal.get('resource_estimate_id') or '').strip()
        # A source reporting that it found no tonnage has not reported a
        # tonnage, so it is not one of the attributes an estimate has to be
        # internally consistent about. Counting it as one would let an empty
        # search fail an estimate closed.
        if row is None or not estimate_id or _is_empty_finding(proposal.get('value')):
            return None
        return cls(
            field_key=field_key,
            row=row,
            estimate_id=estimate_id,
            relation_to_object=str(proposal.get('relation_to_object') or '').strip(),
            value_origin=str(proposal.get('value_origin') or '').strip(),
            estimate_state=str(proposal.get('estimate_state') or '').strip(),
            entity_id=str(proposal.get('entity_id') or '').strip(),
            site_name=str(proposal.get('site_name') or '').strip(),
        )


def _nonempty_values(
    records: Sequence[ResourceEstimateRecord],
    attribute: str,
) -> set[str]:
    return {str(getattr(record, attribute)).strip() for record in records if str(getattr(record, attribute)).strip()}


def _inconsistent_dimensions(
    records: Sequence[ResourceEstimateRecord],
) -> tuple[str, ...]:
    return tuple(
        attribute
        for attribute in (
            'relation_to_object',
            'value_origin',
            'estimate_state',
            'entity_id',
            'site_name',
        )
        if len(_nonempty_values(records, attribute)) > 1
    )


def _mark_calculated_resource_value(proposal: dict[str, Any]) -> None:
    if _resource_row(str(proposal.get('field_key') or '')) is None:
        return
    if str(proposal.get('value_origin') or '').strip() not in {
        'calculated',
        'analogue',
    }:
        return
    proposal['calculation_label'] = CALCULATED_VALUE_LABEL
    locator = proposal.get('source_locator')
    if isinstance(locator, Mapping):
        proposal['source_locator'] = {
            **dict(locator),
            'calculation_label': CALCULATED_VALUE_LABEL,
        }


def cohere_resource_estimate_proposals(
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep at most one internally consistent estimate identity per row.

    The winning estimate has a unique best score by distinct field coverage,
    direct-object coverage and proposal count. A tie or an internally
    inconsistent estimate fails closed. Inputs are not mutated.
    """

    result = [copy.deepcopy(dict(item)) for item in evidence]
    candidates: dict[
        str,
        dict[str, list[ResourceEstimateRecord]],
    ] = defaultdict(lambda: defaultdict(list))
    for item in result:
        for proposal in item.get('field_proposals') or []:
            if not isinstance(proposal, dict):
                continue
            _mark_calculated_resource_value(proposal)
            record = ResourceEstimateRecord.from_proposal(proposal)
            if record is not None:
                candidates[record.row][record.estimate_id].append(record)

    diagnostics: list[dict[str, Any]] = []
    decisions: dict[str, str | None] = {}
    for row, estimates in sorted(candidates.items()):
        inconsistent = {
            estimate_id: list(_inconsistent_dimensions(records))
            for estimate_id, records in estimates.items()
            if _inconsistent_dimensions(records)
        }
        eligible = {
            estimate_id: records for estimate_id, records in estimates.items() if estimate_id not in inconsistent
        }
        if len(estimates) == 1 and not inconsistent:
            continue
        scores = {
            estimate_id: (
                len({record.field_key for record in records}),
                sum(record.relation_to_object == 'direct' for record in records),
                len(records),
            )
            for estimate_id, records in eligible.items()
        }
        best_score = max(scores.values()) if scores else None
        winners = sorted(estimate_id for estimate_id, score in scores.items() if score == best_score)
        selected = winners[0] if len(winners) == 1 else None
        decisions[row] = selected
        if selected:
            resolution = 'selected_unique_best_estimate'
        elif not eligible:
            resolution = 'no_internally_consistent_estimate_fail_closed'
        else:
            resolution = 'ambiguous_tie_fail_closed'
        diagnostics.append(
            {
                'row': row,
                'resolution': resolution,
                'selected_resource_estimate_id': selected,
                'candidate_scores': {estimate_id: list(score) for estimate_id, score in sorted(scores.items())},
                'inconsistent_dimensions': inconsistent,
            }
        )

    if not decisions:
        return result, diagnostics

    dropped_by_row: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in result:
        filtered = []
        for proposal in item.get('field_proposals') or []:
            if not isinstance(proposal, Mapping):
                filtered.append(proposal)
                continue
            field_key = str(proposal.get('field_key') or '')
            row = _resource_row(field_key)
            if row not in decisions:
                filtered.append(proposal)
                continue
            estimate_id = str(proposal.get('resource_estimate_id') or '').strip()
            selected = decisions[row]
            if selected is not None and estimate_id == selected:
                filtered.append(proposal)
                continue
            dropped_by_row[row].append(
                {
                    'field_key': field_key,
                    'resource_estimate_id': estimate_id or None,
                    'value_origin': proposal.get('value_origin'),
                    'relation_to_object': proposal.get('relation_to_object'),
                }
            )
        if 'field_proposals' in item:
            item['field_proposals'] = filtered

    by_row = {diagnostic['row']: diagnostic for diagnostic in diagnostics}
    for row, dropped in dropped_by_row.items():
        by_row[row]['dropped_proposals'] = dropped
    return result, diagnostics
