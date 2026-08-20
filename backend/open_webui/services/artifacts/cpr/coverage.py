"""Section coverage control and the §9 completeness rate.

CORE-BOUNDARY-01 action 3. Reads a CPR requirement projection -- which
references dossier ids and carries no values -- together with the dossier that
produced it, and reports what each section actually answers.

The denominator is the part worth being careful about. §9 allows exactly one
subtraction from it: a `not_applicable` an expert approved. Anything else that
shrinks the denominator turns a missing answer into a higher score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import requirements_by_id
from .requirements import RequirementPlan, plan_requirements

ANSWERED_STATES = frozenset({'supported', 'corroborated'})
ABSENCE_STATES = frozenset({'missing', 'not_applicable', 'blocked_expert'})


@dataclass(frozen=True)
class SectionCoverage:
    section: int
    planned: int
    applicable: int
    answered: int
    conflicted: int
    missing: int
    not_applicable: int
    blocked_expert: int
    unaddressed: tuple[str, ...]
    expert_approved_not_applicable: tuple[str, ...]

    @property
    def denominator(self) -> int:
        """Applicable requirements, less only the expert-approved
        `not_applicable`."""
        return self.applicable - len(self.expert_approved_not_applicable)

    @property
    def completeness_percent(self) -> float | None:
        if self.denominator <= 0:
            return None
        return round(100.0 * self.answered / self.denominator, 2)


def _expert_approved_gaps(dossier: Mapping[str, Any]) -> frozenset[str]:
    """Gap ids a reviewer explicitly marked not applicable."""
    return frozenset(
        subject
        for decision in dossier.get('review_decisions') or ()
        if decision.get('decision') == 'marked_not_applicable'
        for subject in decision.get('subject_ids') or ()
    )


def _rows_by_requirement(projection: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {row['requirement_id']: row for row in projection.get('coverage') or ()}


def _is_expert_approved(row: Mapping[str, Any], approved: frozenset[str]) -> bool:
    if row.get('state') != 'not_applicable':
        return False
    gap_ids = row.get('gap_ids') or ()
    return bool(gap_ids) and all(gap_id in approved for gap_id in gap_ids)


def section_coverage(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assets: Path | None = None,
) -> tuple[SectionCoverage, ...]:
    """Per-section counts, in the template's own section order."""
    stage = dossier['project_scope']['lifecycle_stage']
    rows = _rows_by_requirement(projection)
    approved = _expert_approved_gaps(dossier)

    grouped: dict[int, list[RequirementPlan]] = {}
    for plan in plan_requirements(stage, assets):
        grouped.setdefault(plan.section, []).append(plan)

    result: list[SectionCoverage] = []
    for section, plans in sorted(grouped.items()):
        counts = {state: 0 for state in ('conflicted', 'missing', 'not_applicable', 'blocked_expert')}
        answered = 0
        unaddressed: list[str] = []
        approved_here: list[str] = []
        applicable = 0

        for plan in plans:
            if plan.applicable:
                applicable += 1
            row = rows.get(plan.requirement_id)
            if row is None:
                # An applicable requirement with no projection row is neither
                # answered nor refused. It is the one state the six-state
                # vocabulary cannot express, so it is reported separately
                # rather than folded into `missing`.
                if plan.applicable:
                    unaddressed.append(plan.requirement_id)
                continue
            state = row.get('state')
            if state in ANSWERED_STATES:
                answered += 1
            elif state in counts:
                counts[state] += 1
            # Only a requirement that was in the denominator can leave it. A
            # requirement out of stage is already outside it, so counting its
            # reviewed gap here would subtract it twice and inflate the rate.
            if plan.applicable and _is_expert_approved(row, approved):
                approved_here.append(plan.requirement_id)

        result.append(
            SectionCoverage(
                section=section,
                planned=len(plans),
                applicable=applicable,
                answered=answered,
                conflicted=counts['conflicted'],
                missing=counts['missing'],
                not_applicable=counts['not_applicable'],
                blocked_expert=counts['blocked_expert'],
                unaddressed=tuple(unaddressed),
                expert_approved_not_applicable=tuple(approved_here),
            )
        )
    return tuple(result)


def semantic_completeness(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assets: Path | None = None,
) -> dict[str, Any]:
    """The §9 rate over the whole catalog, with its denominator shown.

    A projection that covers part of the catalog reports `scope` so the rate is
    not mistaken for a measurement: the same rule the projection contract
    enforces on the GeoTeaser side, where a slice may not publish a percentage
    at all.
    """
    sections = section_coverage(projection, dossier, assets)
    applicable = sum(section.applicable for section in sections)
    approved = sum(len(section.expert_approved_not_applicable) for section in sections)
    answered = sum(section.answered for section in sections)
    unaddressed = tuple(rid for section in sections for rid in section.unaddressed)
    denominator = applicable - approved

    return {
        'scope': projection.get('projection_scope'),
        'applicable': applicable,
        'expert_approved_not_applicable': approved,
        'denominator': denominator,
        'answered': answered,
        'unaddressed': unaddressed,
        'percent': (round(100.0 * answered / denominator, 2) if denominator > 0 else None),
        'measurable': projection.get('projection_scope') == 'complete' and not unaddressed,
    }


def unaddressed_requirements(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assets: Path | None = None,
) -> tuple[str, ...]:
    """Applicable requirements the projection says nothing about at all."""
    stage = dossier['project_scope']['lifecycle_stage']
    rows = _rows_by_requirement(projection)
    return tuple(
        plan.requirement_id
        for plan in plan_requirements(stage, assets)
        if plan.applicable and plan.requirement_id not in rows
    )


def sections_needing_attention(
    coverages: Sequence[SectionCoverage],
) -> tuple[SectionCoverage, ...]:
    """Sections with an unaddressed requirement, a conflict or a blocked
    expert. These are the ones a reviewer has to look at before anything is
    signed -- and nothing here signs anything."""
    return tuple(
        section for section in coverages if section.unaddressed or section.conflicted or section.blocked_expert
    )


def requirement_titles(assets: Path | None = None) -> dict[str, str]:
    return {rid: entry['title'] for rid, entry in requirements_by_id(assets).items()}


__all__ = [
    'ABSENCE_STATES',
    'ANSWERED_STATES',
    'SectionCoverage',
    'requirement_titles',
    'section_coverage',
    'sections_needing_attention',
    'semantic_completeness',
    'unaddressed_requirements',
]
