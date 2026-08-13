"""What counts as a live claim, and which of them answer a question.

Both artefacts project the same dossier, and the whole design rests on them
projecting it the *same way*. That makes claim selection the one rule they may
not each own a copy of.

It was two copies, and one constant was three. `LIVE_CLAIM_STATES`,
`_granted_source_ids` and `_conflicts_over` were duplicated verbatim between the
CPR and GeoTeaser projections; `_gap_for` and `_reviewed_gap` were the same
function under two names; and the eligibility filter was reimplemented in each
`_matching_claims`. Nothing had diverged yet -- but `consistency.compare`
compares the two *outputs*, so a divergence in what the two projections were
willing to look at would have passed it. Two artefacts agreeing about claims
neither of them considered is not agreement.

The one filter that is genuinely not shared stays where it belongs: GeoTeaser
also asks whether a claim answers the row's facet, which is a template question
the CPR has no equivalent of. That is a caller's filter applied on top of
eligibility, not a second definition of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# A retracted or superseded claim is not evidence. `conflict` stays live on
# purpose: an unresolved disagreement is a thing both artefacts must be able to
# see and report, not a thing either may quietly drop.
LIVE_CLAIM_STATES = frozenset({'active', 'conflict'})

__all__ = [
    'LIVE_CLAIM_STATES',
    'claim_is_eligible',
    'conflicts_over',
    'granted_source_ids',
    'matching_claims',
    'reviewed_gap',
]


def granted_source_ids(dossier: Mapping[str, Any]) -> list[str]:
    """Sources a projection is allowed to read: granted by ACL and still active."""
    return sorted(
        source['source_id']
        for source in dossier.get('sources') or ()
        if source.get('acl_decision') == 'granted' and source.get('state') == 'active'
    )


def claim_is_eligible(
    claim: Mapping[str, Any],
    predicates: Iterable[str],
    *,
    analogy_forbidden: bool,
) -> bool:
    """Whether a claim may answer a question at all, before any artefact's own rules.

    §2: an analogue may not stand in as a direct object estimate, so a
    requirement or field that forbids one does not see the claim at all -- it is
    not merely ranked lower.
    """
    if claim.get('predicate') not in set(predicates):
        return False
    if claim.get('state') not in LIVE_CLAIM_STATES:
        return False
    return not (analogy_forbidden and claim['value_origin']['kind'] == 'analogy')


def matching_claims(
    dossier: Mapping[str, Any],
    predicates: Iterable[str],
    *,
    analogy_forbidden: bool,
) -> list[Mapping[str, Any]]:
    """Every eligible claim in the dossier, in dossier order."""
    wanted = set(predicates)
    return [
        claim
        for claim in dossier.get('claims') or ()
        if claim_is_eligible(claim, wanted, analogy_forbidden=analogy_forbidden)
    ]


def conflicts_over(
    dossier: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Conflicts where at least two of the given claims are on opposite sides.

    Two, not one: a conflict that touches a single matched claim is a
    disagreement with something this question never considered, and reporting it
    here would attribute someone else's dispute to this answer.
    """
    claim_ids = {claim['claim_id'] for claim in claims}
    return sorted(
        conflict['conflict_id']
        for conflict in dossier.get('conflicts') or ()
        if len(claim_ids & set(conflict.get('claim_ids') or ())) >= 2
    )


def reviewed_gap(
    dossier: Mapping[str, Any], predicates: Iterable[str]
) -> Mapping[str, Any] | None:
    """The reviewer's own record of this absence, if they made one."""
    wanted = set(predicates)
    for gap in dossier.get('gaps') or ():
        if wanted & set(gap.get('missing_predicates') or ()):
            return gap
    return None
