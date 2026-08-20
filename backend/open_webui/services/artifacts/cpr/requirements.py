"""Requirement planning: what the CPR must answer for this object.

CORE-BOUNDARY-01 action 3. The plan is produced from the catalog and the
object's lifecycle stage, before any evidence is looked at, so the denominator
is fixed in advance rather than emerging from whatever happened to be found.

A requirement that does not apply at the object's stage stays in the plan,
marked `applicable=False`. §10 of the assignment names the opposite as the
risk: 119 requirements treated as mandatory at an early stage. Dropping them
from the plan would hide the judgement instead of recording it -- the artefact
should be able to print "not applicable at exploration results" rather than
silently omit a section.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import load_catalog
from .errors import CprContractError

LIFECYCLE_STAGES = (
    'exploration_results',
    'mineral_resources',
    'ore_reserves',
    'technical_study',
)


@dataclass(frozen=True)
class RequirementPlan:
    """One catalog requirement, resolved against a lifecycle stage."""

    requirement_id: str
    kind: str
    section: int
    subsection: str
    title: str
    applicable: bool
    fact_kind: str
    authority_source: str
    required_evidence_kinds: tuple[str, ...]
    locator_precision: str
    calculation_allowed: bool
    analogy_policy: str
    mandatory_figures: bool
    reviewer_role: str
    external_knowledge_policy: str
    competency_questions: tuple[str, ...]
    proposed_competency_questions: tuple[str, ...]

    @property
    def ratified_coverage(self) -> bool:
        """Whether a ratified competency question covers this requirement. A
        proposal is a recorded gap, not coverage."""
        return bool(self.competency_questions)


def _plan(entry: Mapping[str, Any], stage: str) -> RequirementPlan:
    return RequirementPlan(
        requirement_id=entry['id'],
        kind=entry['kind'],
        section=entry['section'],
        subsection=entry['subsection'],
        title=entry['title'],
        applicable=stage in entry['lifecycle_applicability'],
        fact_kind=entry['fact_kind'],
        authority_source=entry['authority_source'],
        required_evidence_kinds=tuple(entry['required_evidence_kinds']),
        locator_precision=entry['locator_precision'],
        calculation_allowed=bool(entry['calculation_allowed']),
        analogy_policy=entry['analogy_policy'],
        mandatory_figures=bool(entry['mandatory_figures']),
        reviewer_role=entry['reviewer_role'],
        external_knowledge_policy=entry['external_knowledge_policy'],
        competency_questions=tuple(entry['competency_questions']),
        proposed_competency_questions=tuple(entry['proposed_competency_questions']),
    )


def plan_requirements(stage: str, assets: Path | None = None) -> tuple[RequirementPlan, ...]:
    """Every catalog requirement, in template order, resolved against `stage`."""
    if stage not in LIFECYCLE_STAGES:
        raise CprContractError(f'unknown lifecycle stage: {stage!r}; expected one of {LIFECYCLE_STAGES}')
    catalog = load_catalog(assets)
    return tuple(_plan(entry, stage) for entry in catalog['requirements'])


def applicable_requirements(stage: str, assets: Path | None = None) -> tuple[RequirementPlan, ...]:
    return tuple(plan for plan in plan_requirements(stage, assets) if plan.applicable)


def requirements_by_section(stage: str, assets: Path | None = None) -> dict[int, tuple[RequirementPlan, ...]]:
    """Template order, grouped. Sections are the CPR's own numbering, so the
    order is the document's order and not a sort of our choosing."""
    grouped: dict[int, list[RequirementPlan]] = {}
    for plan in plan_requirements(stage, assets):
        grouped.setdefault(plan.section, []).append(plan)
    return {section: tuple(plans) for section, plans in sorted(grouped.items())}


def evidence_expectations(stage: str, assets: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Required evidence kinds per applicable requirement -- the retrieval
    plan's input, and the reason a requirement can be declared unanswerable
    before a single source is read."""
    return {plan.requirement_id: plan.required_evidence_kinds for plan in applicable_requirements(stage, assets)}


def requirements_forbidding_analogy(stage: str, assets: Path | None = None) -> frozenset[str]:
    """§2: an analogue may not stand in as a direct object estimate. The
    catalog's strongest permitted value is `allowed_if_labeled`."""
    return frozenset(
        plan.requirement_id for plan in applicable_requirements(stage, assets) if plan.analogy_policy == 'forbidden'
    )


def requirements_needing_a_figure(stage: str, assets: Path | None = None) -> frozenset[str]:
    return frozenset(plan.requirement_id for plan in applicable_requirements(stage, assets) if plan.mandatory_figures)


def reviewer_workload(stage: str, assets: Path | None = None) -> dict[str, int]:
    """Applicable requirements per reviewer role. The roles come from the
    ontology's `decision_owner` vocabulary; `Competent Person` is not among
    them, because §2 forbids the artefact signing as one."""
    workload: dict[str, int] = {}
    for plan in applicable_requirements(stage, assets):
        workload[plan.reviewer_role] = workload.get(plan.reviewer_role, 0) + 1
    return workload


def coverage_gaps(stage: str, assets: Path | None = None) -> tuple[str, ...]:
    """Applicable requirements no ratified competency question covers. Recorded
    rather than closed by invention: §7 asks for the gaps to be written down."""
    return tuple(plan.requirement_id for plan in applicable_requirements(stage, assets) if not plan.ratified_coverage)


def plan_ids(plans: Sequence[RequirementPlan]) -> tuple[str, ...]:
    return tuple(plan.requirement_id for plan in plans)


__all__ = [
    'LIFECYCLE_STAGES',
    'RequirementPlan',
    'applicable_requirements',
    'coverage_gaps',
    'evidence_expectations',
    'plan_ids',
    'plan_requirements',
    'requirements_by_section',
    'requirements_forbidding_analogy',
    'requirements_needing_a_figure',
    'reviewer_workload',
]
