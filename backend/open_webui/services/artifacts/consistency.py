"""Do the two artefacts say the same thing about the same facts?

UAT-CPR-GT-01's completion criterion: the ids and the values of facts agree
across both artefacts, there are no hidden contradictions, and re-rendering
changes no hash.

The first part is nearly free, and saying why is the point of the whole design.
Neither projection carries a value -- both cite dossier claim ids -- so two
artefacts cannot disagree about a number. They can still disagree about a
*fact*: one may treat a claim as evidence while the other reports the same
claim's subject absent, or read a disagreement as settled that the other keeps
open. Those are the contradictions worth hunting, and they are what this
module looks for.

The expected behaviour the task names is that any divergence reduces to a named
mapping or rendering rule rather than to two agents having answered
differently. Every finding here therefore points at the rule that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..project_evidence.claims import LIVE_CLAIM_STATES

PRESENT = frozenset({'supported', 'corroborated', 'conflicted'})
ABSENT = frozenset({'missing', 'not_applicable', 'blocked_expert'})

CPR = 'cpr'
GEOTIZER = 'geotizer'


@dataclass(frozen=True)
class Divergence:
    code: str
    claim_id: str | None
    cpr_locations: tuple[str, ...]
    geotizer_locations: tuple[str, ...]
    detail: str


def _cpr_rows(projection: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    return [(row['requirement_id'], row) for row in projection.get('coverage') or ()]


def _geotizer_rows(projection: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    return [(row['field_key'], row) for row in projection.get('fields') or ()]


def _claims_used(rows: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for location, row in rows:
        for claim_id in row.get('supporting_claim_ids') or ():
            used.setdefault(claim_id, []).append(location)
    return used


def _states_for(rows: Sequence[tuple[str, Mapping[str, Any]]], claim_id: str) -> set[str]:
    return {row['state'] for _, row in rows if claim_id in (row.get('supporting_claim_ids') or ())}


def compare(
    cpr_projection: Mapping[str, Any],
    geotizer_projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
) -> tuple[Divergence, ...]:
    """Every way the two artefacts could disagree about the same evidence."""
    findings: list[Divergence] = []

    run = dossier['dossier_run_id']
    for name, projection in ((CPR, cpr_projection), (GEOTIZER, geotizer_projection)):
        if projection.get('dossier_run_id') != run:
            findings.append(
                Divergence(
                    'different_dossier_run',
                    None,
                    (),
                    (),
                    f'the {name} projection was built from another run',
                )
            )
    if findings:
        # Nothing below means anything if they are not the same run.
        return tuple(findings)

    cpr_rows = _cpr_rows(cpr_projection)
    geotizer_rows = _geotizer_rows(geotizer_projection)
    cpr_used = _claims_used(cpr_rows)
    geotizer_used = _claims_used(geotizer_rows)
    conflicted_claims = {
        claim_id for conflict in dossier.get('conflicts') or () for claim_id in conflict.get('claim_ids') or ()
    }

    # A disputed claim must be reported disputed *wherever* it is used, not
    # only where both artefacts happen to use it. An artefact that settles a
    # disagreement on its own is the hidden contradiction the criterion
    # forbids, and it stays a contradiction when the other artefact is silent.
    for claim_id in sorted(set(cpr_used) | set(geotizer_used)):
        cpr_states = _states_for(cpr_rows, claim_id)
        geotizer_states = _states_for(geotizer_rows, claim_id)
        locations = (tuple(cpr_used.get(claim_id, ())), tuple(geotizer_used.get(claim_id, ())))

        if claim_id in conflicted_claims:
            for name, states in ((CPR, cpr_states), (GEOTIZER, geotizer_states)):
                # Every row citing a disputed claim must report it disputed.
                # "At least one row got it right" is not enough: the row that
                # got it wrong is the one a reader would believe.
                if (states - {'conflicted'}) & PRESENT:
                    findings.append(
                        Divergence(
                            'conflict_reported_on_one_side_only',
                            claim_id,
                            *locations,
                            f'the dossier records this claim as conflicted and the '
                            f'{name} projection reports {sorted(states)}',
                        )
                    )
        elif 'conflicted' in cpr_states | geotizer_states:
            findings.append(
                Divergence(
                    'conflict_without_a_dossier_record',
                    claim_id,
                    *locations,
                    'an artefact calls this a conflict and the dossier has no conflict record for it',
                )
            )

    # A claim used as evidence on one side while the other reports the same
    # claim's absence. Different questions may legitimately reach different
    # states, so this only fires when the very same claim is both cited and
    # declared missing.
    for claim_id in sorted(set(cpr_used) | set(geotizer_used)):
        for rows, used, name in (
            (cpr_rows, geotizer_used, CPR),
            (geotizer_rows, cpr_used, GEOTIZER),
        ):
            if claim_id not in used:
                continue
            absent_here = [
                location
                for location, row in rows
                if row['state'] in ABSENT and claim_id in (row.get('supporting_claim_ids') or ())
            ]
            if absent_here:
                findings.append(
                    Divergence(
                        'claim_cited_and_declared_absent',
                        claim_id,
                        tuple(cpr_used.get(claim_id, ())),
                        tuple(geotizer_used.get(claim_id, ())),
                        f'the {name} projection cites this claim in an absence row',
                    )
                )

    return tuple(findings)


def shared_claims(
    cpr_projection: Mapping[str, Any], geotizer_projection: Mapping[str, Any]
) -> dict[str, dict[str, list[str]]]:
    """Which claims both artefacts stand on, and where each of them uses it."""
    cpr_used = _claims_used(_cpr_rows(cpr_projection))
    geotizer_used = _claims_used(_geotizer_rows(geotizer_projection))
    return {
        claim_id: {
            'cpr': sorted(cpr_used[claim_id]),
            'geotizer': sorted(geotizer_used[claim_id]),
        }
        for claim_id in sorted(set(cpr_used) & set(geotizer_used))
    }


def evidence_reuse(
    cpr_projection: Mapping[str, Any],
    geotizer_projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
) -> dict[str, Any]:
    """Action 2: how much of one evidence run both documents actually used.

    A run that produces two documents from one body of evidence should be
    visible as reuse, not asserted. The number is small here for the same
    reason the completeness numbers are: the dossier is small.
    """
    cpr_used = set(_claims_used(_cpr_rows(cpr_projection)))
    geotizer_used = set(_claims_used(_geotizer_rows(geotizer_projection)))
    every = {claim['claim_id'] for claim in dossier.get('claims') or ()}
    # `used_by_neither` is read as a coverage gap, so it may only hold claims
    # that *could* have been used. A withdrawn claim going unused is the
    # projections working, not evidence they overlooked -- counted separately
    # rather than dropped, because a claim that vanishes from every total is a
    # claim nobody can ask about.
    available = {
        claim['claim_id']
        for claim in dossier.get('claims') or ()
        if claim.get('state') in LIVE_CLAIM_STATES
    }
    return {
        'claims_in_dossier': len(every),
        'live_claims': len(available),
        'withdrawn_claims': sorted(every - available),
        'used_by_cpr': len(cpr_used),
        'used_by_geotizer': len(geotizer_used),
        'used_by_both': len(cpr_used & geotizer_used),
        'used_by_neither': sorted(available - cpr_used - geotizer_used),
        'cited_but_absent_from_the_dossier': sorted((cpr_used | geotizer_used) - every),
    }


__all__ = [
    'ABSENT',
    'CPR',
    'Divergence',
    'GEOTIZER',
    'PRESENT',
    'compare',
    'evidence_reuse',
    'shared_claims',
]
