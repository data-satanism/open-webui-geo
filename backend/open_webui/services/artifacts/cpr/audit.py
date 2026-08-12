"""Auditing a CPR projection against the catalog and the dossier.

CORE-BOUNDARY-01 action 3, and the runtime half of the check GMM's
`validate_evidence_dossier.py` runs in CI. CI can refuse a commit; it cannot
refuse a run, and a run assembles a projection from live evidence. The same
rules therefore have to hold at assembly time.

Findings are returned, not raised. An audit that stops at the first problem
tells a reviewer one thing; the artefact needs the list, because the audit
section is part of what gets delivered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import if_not_why_not_states, requirements_by_id
from .coverage import unaddressed_requirements
from .requirements import plan_requirements

PRESENCE_STATES = frozenset({'supported', 'corroborated'})

SEVERITY_BLOCKING = 'blocking'
SEVERITY_REVIEW = 'review'


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    requirement_id: str | None
    detail: str


def _index(items: Sequence[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    return {item[key]: item for item in items or ()}


def audit_projection(  # noqa: C901 - one branch per contract rule, read as a list
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assets: Path | None = None,
) -> tuple[Finding, ...]:
    """Every rule the projection contract states, checked against live data."""
    findings: list[Finding] = []

    if projection.get('dossier_run_id') != dossier.get('dossier_run_id'):
        findings.append(
            Finding(
                'wrong_dossier_run',
                SEVERITY_BLOCKING,
                None,
                'the projection was built from a different dossier run',
            )
        )

    stage = dossier['project_scope']['lifecycle_stage']
    catalog = requirements_by_id(assets)
    plans = {plan.requirement_id: plan for plan in plan_requirements(stage, assets)}
    absence_states = if_not_why_not_states(assets)

    claims = _index(dossier.get('claims'), 'claim_id')
    estimates = _index(dossier.get('estimates'), 'estimate_id')
    figures = _index(dossier.get('figures'), 'figure_id')
    conflicts = _index(dossier.get('conflicts'), 'conflict_id')
    gaps = _index(dossier.get('gaps'), 'gap_id')

    seen: set[str] = set()
    for row in projection.get('coverage') or ():
        rid = row.get('requirement_id')
        if rid in seen:
            findings.append(Finding('duplicate_requirement', SEVERITY_BLOCKING, rid, 'covered twice'))
        seen.add(rid)

        plan = plans.get(rid)
        if plan is None:
            findings.append(
                Finding(
                    'unknown_requirement',
                    SEVERITY_BLOCKING,
                    rid,
                    f'not among the {len(catalog)} requirements in the catalog',
                )
            )
            continue

        expected = stage if plan.applicable else 'not_applicable'
        if row.get('applicability') != expected:
            findings.append(
                Finding(
                    'applicability',
                    SEVERITY_BLOCKING,
                    rid,
                    f'catalog says {expected!r} at {stage}, projection says {row.get("applicability")!r}',
                )
            )

        state = row.get('state')
        support = (
            tuple(row.get('supporting_claim_ids') or ())
            + tuple(row.get('supporting_estimate_ids') or ())
            + tuple(row.get('supporting_figure_ids') or ())
        )

        for claim_id in row.get('supporting_claim_ids') or ():
            if claim_id not in claims:
                findings.append(Finding('unknown_claim', SEVERITY_BLOCKING, rid, claim_id))
        for estimate_id in row.get('supporting_estimate_ids') or ():
            if estimate_id not in estimates:
                findings.append(Finding('unknown_estimate', SEVERITY_BLOCKING, rid, estimate_id))
        for figure_id in row.get('supporting_figure_ids') or ():
            if figure_id not in figures:
                findings.append(Finding('unknown_figure', SEVERITY_BLOCKING, rid, figure_id))

        if state in PRESENCE_STATES and not support:
            findings.append(
                Finding(
                    'unsupported_presence',
                    SEVERITY_BLOCKING,
                    rid,
                    f'state {state!r} with nothing cited',
                )
            )
        if state in absence_states and support:
            findings.append(
                Finding(
                    'absence_with_support',
                    SEVERITY_BLOCKING,
                    rid,
                    f'state {state!r} while citing {len(support)} item(s)',
                )
            )

        if state == 'conflicted' and not row.get('conflict_ids'):
            findings.append(
                Finding(
                    'conflict_without_record',
                    SEVERITY_BLOCKING,
                    rid,
                    'a disagreement must stay addressable on both sides',
                )
            )
        for conflict_id in row.get('conflict_ids') or ():
            if conflict_id not in conflicts:
                findings.append(Finding('unknown_conflict', SEVERITY_BLOCKING, rid, conflict_id))

        reason = row.get('if_not_why_not')
        if state in absence_states and not reason:
            findings.append(
                Finding(
                    'absence_without_reason',
                    SEVERITY_BLOCKING,
                    rid,
                    'if not, why not is required for this state',
                )
            )
        if reason:
            for gap_id in row.get('gap_ids') or ():
                gap = gaps.get(gap_id)
                if gap is None:
                    findings.append(Finding('unknown_gap', SEVERITY_BLOCKING, rid, gap_id))
                elif gap.get('if_not_why_not') != reason:
                    findings.append(
                        Finding(
                            'reason_diverges_from_gap',
                            SEVERITY_BLOCKING,
                            rid,
                            f'the projection restates {gap_id} differently',
                        )
                    )
            if (
                not row.get('gap_ids')
                and reason.get('reason_kind') == 'expert_decision_required'
                # A requirement the catalog types as expert_interpretation
                # needs no reviewer to establish that it needs a reviewer: the
                # statement is read off the catalog, exactly as
                # stage_not_reached is. Every other expert determination is a
                # judgement about this object, and belongs in the dossier where
                # the reviewer who made it can be named.
                and catalog.get(rid, {}).get('fact_kind') != 'expert_interpretation'
            ):
                findings.append(
                    Finding(
                        'unreviewed_expert_absence',
                        SEVERITY_BLOCKING,
                        rid,
                        'an expert determination belongs in the dossier, where a reviewer can be named',
                    )
                )

        if plan.analogy_policy == 'forbidden':
            for claim_id in row.get('supporting_claim_ids') or ():
                claim = claims.get(claim_id)
                if claim and claim['value_origin']['kind'] == 'analogy':
                    findings.append(
                        Finding(
                            'analogy_forbidden',
                            SEVERITY_BLOCKING,
                            rid,
                            f'{claim_id} is an analogy and this requirement forbids one',
                        )
                    )

        if plan.mandatory_figures and state in PRESENCE_STATES:
            if not row.get('supporting_figure_ids'):
                findings.append(
                    Finding(
                        'figure_required',
                        SEVERITY_REVIEW,
                        rid,
                        'the template requires a figure for this requirement',
                    )
                )

    for rid in unaddressed_requirements(projection, dossier, assets):
        findings.append(
            Finding(
                'unaddressed',
                SEVERITY_REVIEW,
                rid,
                'applicable at this stage and the projection says nothing about it',
            )
        )

    return tuple(findings)


def blocking(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    return tuple(finding for finding in findings if finding.severity == SEVERITY_BLOCKING)


def audit_summary(findings: Sequence[Finding]) -> dict[str, Any]:
    by_code: dict[str, int] = {}
    for finding in findings:
        by_code[finding.code] = by_code.get(finding.code, 0) + 1
    return {
        'findings': len(findings),
        'blocking': len(blocking(findings)),
        'by_code': dict(sorted(by_code.items())),
        # Nothing here signs anything. §2 forbids the artefact claiming
        # JORC/NAEN conformance, so a clean audit means "no rule was broken",
        # not "this report conforms".
        'signs_conformance': False,
    }


__all__ = [
    'Finding',
    'SEVERITY_BLOCKING',
    'SEVERITY_REVIEW',
    'audit_projection',
    'audit_summary',
    'blocking',
]
