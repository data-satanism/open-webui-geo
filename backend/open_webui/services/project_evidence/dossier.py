"""What a dossier must contain before either artefact may be projected from it.

Both projections read the frozen dossier directly and neither checked it first.
A claim missing `value_origin` raised `KeyError: 'value_origin'` out of the
middle of the CPR coverage walk; a dossier missing `project_scope` raised
`KeyError: 'project_scope'` before the CPR had built a single row. Twenty-one
fields behave that way -- some crash, and the rest are worse, because they
change the answer in silence: drop `state` from every claim and both projections
return a smaller, entirely well-formed result in which nothing is live.

The failure is not that the accesses are unguarded. Replacing them with `.get()`
would turn every one of those crashes into the silent case, which is the wrong
direction: a projection built from a dossier that is missing half its claims is
a document that looks finished and is not. The failure is that nothing said
"this is not a dossier" before the projection started.

So this is a precondition, checked once, naming everything that is wrong rather
than the first thing found -- an operator holding a bad export needs the list,
not a guided tour one `KeyError` at a time.

**One check, applied by both.** The dossier is artefact-independent: the CPR
document and the GeoTeaser workbook are two projections of the same evidence,
and the invariant that holds them together is that they never disagree. A
dossier that only one of them can read breaks that before either runs -- it
would produce a workbook and no CPR, which is divergence by another route. So
the requirement set here is the union of what both read, and `project_scope` is
required for the GeoTeaser projection too, even though GeoTeaser never looks at
it.

**Nothing here is invented.** Every field below is `required` in
`GMM/contracts/evidence/project-evidence-dossier.schema.json`, which owns the
contract; this restates the part of it the projections depend on, at the
boundary where its absence would otherwise be a stack trace.
`test_project_evidence_dossier.py` derives the set the other way, by mutation --
it drops each field and asserts that anything which crashes or changes the
answer is named here -- and cross-checks the lists against the schema itself
when a `GMM` checkout is present.

Optional fields are deliberately absent from the lists. `estimate_id`,
`missing_predicates` and `required_expert_action_id` all change the projection
when removed, and all three are optional in the schema: a claim with no estimate
is a claim with no estimate, and projecting it differently is correct.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# `$.required` of the dossier schema, in full. The projections dereference nine
# of these; the rest are listed because the statement being made is "this is a
# Project Evidence Dossier", not "this happens to satisfy today's readers". A
# projection that starts reading `entities` tomorrow should not have to
# rediscover this.
DOSSIER_REQUIRED = (
    'assumptions',
    'claims',
    'conflicts',
    'dossier_run_id',
    'entities',
    'estimates',
    'expert_actions',
    'figures',
    'frozen_at',
    'frozen_inputs_hash',
    'gaps',
    'project_scope',
    'review_decisions',
    'schema_version',
    'sources',
    'state',
    'uncertainties',
)

# `$defs.evidenceClaim.required`.
CLAIM_REQUIRED = (
    'claim_id',
    'fact_kind',
    'predicate',
    'resolution_outcome',
    'source_locator',
    'source_refs',
    'state',
    'subject_entity_id',
    'temporal_scope',
    'value',
    'value_origin',
)

# `$defs.evidenceGap.required`.
GAP_REQUIRED = ('gap_id', 'if_not_why_not', 'missing_fact', 'subject_entity_id')

# `$defs.conflict.required`.
CONFLICT_REQUIRED = ('claim_ids', 'conflict_id', 'kind', 'resolution', 'statement')

# The nested objects the projections reach into. Each is `required` on its own
# `$def`, and each has already been the whole of a crash: `value_origin.kind` is
# read by the eligibility filter both projections share, `if_not_why_not.state`
# decides which of the three absences a gap is, and `project_scope.lifecycle_stage`
# selects the CPR requirement set.
VALUE_ORIGIN_REQUIRED = ('kind',)
IF_NOT_WHY_NOT_REQUIRED = ('reason', 'reason_kind', 'state')
PROJECT_SCOPE_REQUIRED = ('acl_decision', 'lifecycle_stage', 'project_id')

# The dossier members that must be arrays of objects. `claims` arriving as a
# mapping is not a missing field and passes every `in` check above, then fails
# far away as `TypeError: string indices must be integers` -- which is how the
# same shape read in GMM's validator.
LIST_MEMBERS = (
    'assumptions',
    'claims',
    'conflicts',
    'entities',
    'estimates',
    'expert_actions',
    'figures',
    'gaps',
    'review_decisions',
    'sources',
    'uncertainties',
)


class DossierNotProjectable(ValueError):
    """The dossier cannot be projected, and `reasons` says why -- all of it.

    Not a `GeotizerOrchestrationError`: this is raised on the way into the CPR
    projection as often as the GeoTeaser one, and an artefact's error type on an
    artefact-neutral failure would be a small lie about where the fault is.
    """

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        count = len(self.reasons)
        super().__init__(
            f'dossier cannot be projected ({count} problem{"" if count == 1 else "s"}): '
            + '; '.join(self.reasons)
        )


def _missing(where: str, item: Any, required: Sequence[str]) -> list[str]:
    if not isinstance(item, Mapping):
        return [f'{where} must be an object, got {type(item).__name__}']
    return [f'{where}.{name} is required' for name in required if name not in item]


def projection_preconditions(dossier: Any) -> tuple[str, ...]:
    """Everything that stops this dossier being projected, in one pass.

    Returns reasons rather than raising, so a caller that wants to report and
    continue -- a batch validator over many exports, say -- is not forced to use
    exceptions for control flow. `require_projectable` is the raising form.
    """
    if not isinstance(dossier, Mapping):
        return (f'dossier must be an object, got {type(dossier).__name__}',)

    reasons = _missing('dossier', dossier, DOSSIER_REQUIRED)

    wrong_type = set()
    for name in LIST_MEMBERS:
        value = dossier.get(name)
        if name in dossier and not isinstance(value, list):
            reasons.append(f'dossier.{name} must be an array, got {type(value).__name__}')
            wrong_type.add(name)

    scope = dossier.get('project_scope')
    if 'project_scope' in dossier:
        reasons.extend(_missing('dossier.project_scope', scope, PROJECT_SCOPE_REQUIRED))

    def _walk(name: str):
        """The members worth walking: not the ones already refused wholesale.

        Enumerating a mapping given as `claims` yields its keys, and every key
        is then reported as a claim that is not an object. Three reasons for one
        fault reads as three faults.
        """
        return () if name in wrong_type else (dossier.get(name) or ())

    for index, claim in enumerate(_walk('claims')):
        # Indexed, not named: a claim missing `claim_id` cannot be named, and
        # that is exactly the claim most likely to be missing other things too.
        where = f'dossier.claims[{index}]'
        claim_reasons = _missing(where, claim, CLAIM_REQUIRED)
        reasons.extend(claim_reasons)
        if isinstance(claim, Mapping) and 'value_origin' in claim:
            reasons.extend(
                _missing(f'{where}.value_origin', claim['value_origin'], VALUE_ORIGIN_REQUIRED)
            )

    for index, gap in enumerate(_walk('gaps')):
        where = f'dossier.gaps[{index}]'
        reasons.extend(_missing(where, gap, GAP_REQUIRED))
        if isinstance(gap, Mapping) and 'if_not_why_not' in gap:
            reasons.extend(
                _missing(f'{where}.if_not_why_not', gap['if_not_why_not'], IF_NOT_WHY_NOT_REQUIRED)
            )

    for index, conflict in enumerate(_walk('conflicts')):
        reasons.extend(_missing(f'dossier.conflicts[{index}]', conflict, CONFLICT_REQUIRED))

    return tuple(reasons)


def require_projectable(dossier: Any) -> None:
    """Raise `DossierNotProjectable` unless both artefacts can read this dossier."""
    reasons = projection_preconditions(dossier)
    if reasons:
        raise DossierNotProjectable(reasons)


__all__ = [
    'CLAIM_REQUIRED',
    'CONFLICT_REQUIRED',
    'DOSSIER_REQUIRED',
    'DossierNotProjectable',
    'GAP_REQUIRED',
    'IF_NOT_WHY_NOT_REQUIRED',
    'LIST_MEMBERS',
    'PROJECT_SCOPE_REQUIRED',
    'VALUE_ORIGIN_REQUIRED',
    'projection_preconditions',
    'require_projectable',
]
