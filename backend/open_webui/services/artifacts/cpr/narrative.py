"""The narrative plan: what the CPR will say, and on whose authority.

CORE-BOUNDARY-01 action 3. Turns a projection into an ordered list of sentences
to render, one section at a time, in the template's own order.

Every sentence carries its provenance or it is not planned. A statement cites
at least one dossier claim; an absence cites a recorded reason; a conflict
cites at least two claims and the conflict record. There is no fourth kind, so
there is no way to plan a sentence that asserts something the dossier does not
hold -- which is what §2 means by forbidding a plausible placeholder.

The plan carries ids, never text. Wording belongs to the renderer; provenance
belongs here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CprContractError
from .requirements import RequirementPlan, plan_requirements

STATEMENT = 'statement'
ABSENCE = 'absence'
CONFLICT = 'conflict'

RENDERED = frozenset({'rendered', 'rendered_with_gap'})


@dataclass(frozen=True)
class NarrativeSentence:
    requirement_id: str
    kind: str
    claim_ids: tuple[str, ...]
    estimate_ids: tuple[str, ...]
    figure_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    reason_kind: str | None
    reviewer_role: str
    analogy_allowed: bool

    @property
    def provenance_ids(self) -> tuple[str, ...]:
        return self.claim_ids + self.estimate_ids + self.figure_ids


@dataclass(frozen=True)
class NarrativeBlock:
    section: int
    sentences: tuple[NarrativeSentence, ...]
    skipped: tuple[str, ...]

    @property
    def renders(self) -> bool:
        return bool(self.sentences)


def _kind_for(row: Mapping[str, Any]) -> str:
    state = row['state']
    if state == 'conflicted':
        return CONFLICT
    if state in {'missing', 'not_applicable', 'blocked_expert'}:
        return ABSENCE
    return STATEMENT


def _sentence(row: Mapping[str, Any], plan: RequirementPlan) -> NarrativeSentence:
    kind = _kind_for(row)
    reason = row.get('if_not_why_not') or {}
    sentence = NarrativeSentence(
        requirement_id=plan.requirement_id,
        kind=kind,
        claim_ids=tuple(row.get('supporting_claim_ids') or ()),
        estimate_ids=tuple(row.get('supporting_estimate_ids') or ()),
        figure_ids=tuple(row.get('supporting_figure_ids') or ()),
        conflict_ids=tuple(row.get('conflict_ids') or ()),
        gap_ids=tuple(row.get('gap_ids') or ()),
        reason_kind=reason.get('reason_kind'),
        reviewer_role=plan.reviewer_role,
        analogy_allowed=plan.analogy_policy != 'forbidden',
    )

    if kind == STATEMENT and not sentence.provenance_ids:
        raise CprContractError(
            f'{plan.requirement_id}: a statement sentence with no claim, estimate '
            f'or figure would assert something the dossier does not hold'
        )
    if kind == ABSENCE and not sentence.reason_kind:
        raise CprContractError(f'{plan.requirement_id}: an absence sentence needs a recorded reason')
    if kind == CONFLICT:
        if not sentence.conflict_ids:
            raise CprContractError(f'{plan.requirement_id}: a conflict sentence needs the conflict record')
        if len(sentence.claim_ids) < 2:
            raise CprContractError(
                f'{plan.requirement_id}: a conflict sentence must keep both sides '
                f'addressable; got {len(sentence.claim_ids)} claim(s)'
            )
    if plan.mandatory_figures and kind == STATEMENT and not sentence.figure_ids:
        raise CprContractError(
            f'{plan.requirement_id}: the template requires a figure for this requirement and none is cited'
        )
    return sentence


def plan_narrative(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assets: Path | None = None,
) -> tuple[NarrativeBlock, ...]:
    """One block per section, in template order."""
    stage = dossier['project_scope']['lifecycle_stage']
    rows = {row['requirement_id']: row for row in projection.get('coverage') or ()}

    grouped: dict[int, list[RequirementPlan]] = {}
    for plan in plan_requirements(stage, assets):
        grouped.setdefault(plan.section, []).append(plan)

    blocks: list[NarrativeBlock] = []
    for section, plans in sorted(grouped.items()):
        sentences: list[NarrativeSentence] = []
        skipped: list[str] = []
        for plan in plans:
            row = rows.get(plan.requirement_id)
            if row is None:
                continue
            if row.get('render_state') not in RENDERED:
                skipped.append(plan.requirement_id)
                continue
            sentences.append(_sentence(row, plan))
        if sentences or skipped:
            blocks.append(
                NarrativeBlock(
                    section=section,
                    sentences=tuple(sentences),
                    skipped=tuple(skipped),
                )
            )
    return tuple(blocks)


def cited_claim_ids(blocks: Sequence[NarrativeBlock]) -> frozenset[str]:
    return frozenset(claim_id for block in blocks for sentence in block.sentences for claim_id in sentence.claim_ids)


def sentences_by_kind(blocks: Sequence[NarrativeBlock]) -> dict[str, int]:
    counts = {STATEMENT: 0, ABSENCE: 0, CONFLICT: 0}
    for block in blocks:
        for sentence in block.sentences:
            counts[sentence.kind] += 1
    return counts


def analogy_sentences(blocks: Sequence[NarrativeBlock], dossier: Mapping[str, Any]) -> tuple[NarrativeSentence, ...]:
    """Sentences resting on an analogy claim. They exist legitimately -- the
    template asks about adjacent objects -- but they must be labelled as
    analogies when rendered, never as object values."""
    origins = {claim['claim_id']: claim['value_origin']['kind'] for claim in dossier.get('claims') or ()}
    return tuple(
        sentence
        for block in blocks
        for sentence in block.sentences
        if any(origins.get(claim_id) == 'analogy' for claim_id in sentence.claim_ids)
    )


__all__ = [
    'ABSENCE',
    'CONFLICT',
    'NarrativeBlock',
    'NarrativeSentence',
    'STATEMENT',
    'analogy_sentences',
    'cited_claim_ids',
    'plan_narrative',
    'sentences_by_kind',
]
