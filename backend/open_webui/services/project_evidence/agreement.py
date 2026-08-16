"""Whether independent source domains agreed on a claim.

Ported from the deployed Workspace Tool `geoteaser 2.2.0`
(`GMM/operations/workspace-exports/geoteaser.py`, `normalize_value` at 3092,
`FieldAgreement` at 3108, `score_field_agreement` at 3125). It is the first port
of the merge because eleven of the fourteen behaviours the Tool has and this
repository does not read its verdict: the divergent-field list on the card, and
every confidence band.

The GIS, KB, WEB and vision contributors already read the same object
independently, so whether they agreed is the one confidence signal the pipeline
gets for free. Collapsing their proposals without recording it throws that away.

One deliberate difference from the reference, and it is a rename, not a
behaviour change. The Tool keys on the GeoTeaser cell. This package is the
evidence core and may not know about GeoTeaser cells, so the unit here is a
`claim_key`: an opaque string the caller chooses. The projection passes its own
cell identifiers and gets the same verdicts back. Values are compared, never
interpreted, so nothing in this module needs to know what a claim is about --
and this file deliberately contains none of the artefact's vocabulary, which is
a property `test_services_readme_counts.py` counts rather than trusts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

UNANIMOUS = 'unanimous'
SINGLE_SOURCE = 'single_source'
DIVERGENT = 'divergent'

_WHITESPACE = re.compile(r'\s+')


def normalize_value(value: Any) -> str:
    """Comparison form for agreement scoring. Numbers compare numerically.

    Verbatim from the reference, because the whole point of the function is
    which pairs of values count as the same one. `1000` and `1 000,0` are one
    value; `Да` and `да` are one value; anything that will not parse as a number
    falls back to casefolded text with runs of whitespace collapsed.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return f'{float(value):.6g}'
    text = _WHITESPACE.sub(' ', str(value)).strip().casefold()
    try:
        return f'{float(text.replace(",", ".")):.6g}'
    except ValueError:
        return text


@dataclass(frozen=True)
class ClaimAgreement:
    """How independent source domains compare on one bounded claim."""

    claim_key: str
    verdict: str
    domains: tuple[str, ...]
    values: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            'claim_key': self.claim_key,
            'verdict': self.verdict,
            'domains': list(self.domains),
            'values': list(self.values),
        }


def score_claim_agreement(
    evidence: Sequence[Mapping[str, Any]],
    *,
    claim_key_field: str,
    proposals_field: str,
) -> dict[str, ClaimAgreement]:
    """Compare proposals across source domains, per bounded claim.

    `claim_key_field` and `proposals_field` name where to look in the envelope
    the contributors produce. Required rather than defaulted, because the
    default that would be convenient is the artefact's own spelling -- and
    writing that here would put the artefact's vocabulary in the evidence core
    and grow the residue the split exists to shrink. The projection names its
    vocabulary; this module compares values.

    Two rules are worth stating because they are easy to reverse. The **first**
    proposal a domain makes for a claim wins -- a domain that contradicts itself
    is not thereby divergent, since divergence is a statement about independent
    readers. And an empty normalised value is not a proposal at all: a
    contributor that returned nothing must not make a claim look single-source
    when another domain did answer it.
    """
    by_claim: dict[str, dict[str, str]] = {}
    for item in evidence:
        domain = str(item.get('source_domain') or 'unknown')
        for proposal in item.get(proposals_field) or []:
            if not isinstance(proposal, Mapping):
                continue
            claim_key = str(proposal.get(claim_key_field) or '')
            normalized = normalize_value(proposal.get('value'))
            if claim_key and normalized:
                by_claim.setdefault(claim_key, {}).setdefault(domain, normalized)

    scored: dict[str, ClaimAgreement] = {}
    for claim_key, per_domain in by_claim.items():
        values = tuple(sorted(set(per_domain.values())))
        domains = tuple(sorted(per_domain))
        verdict = (
            SINGLE_SOURCE
            if len(domains) < 2
            else UNANIMOUS
            if len(values) == 1
            else DIVERGENT
        )
        scored[claim_key] = ClaimAgreement(claim_key, verdict, domains, values)
    return scored


def divergent_claim_keys(scored: Mapping[str, ClaimAgreement]) -> tuple[str, ...]:
    """The claims two domains read differently, sorted.

    The card's «Расхождения между источниками» list, and the reason GT-4 tells
    a reader to look there before the completeness figure.
    """
    return tuple(
        sorted(key for key, agreement in scored.items() if agreement.verdict == DIVERGENT)
    )


__all__ = [
    'DIVERGENT',
    'SINGLE_SOURCE',
    'UNANIMOUS',
    'ClaimAgreement',
    'divergent_claim_keys',
    'normalize_value',
    'score_claim_agreement',
]
