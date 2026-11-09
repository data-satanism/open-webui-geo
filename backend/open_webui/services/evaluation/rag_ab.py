"""RAG-EVAL-01: score a retrieval change by the dossier it produces.

Two arms -- control v1 and shadow v2 -- over the same sources, the same schemas,
the same models and the same document modules. Only retrieval differs, so any
difference in the dossier is retrieval's doing.

The measure is the evidence, never the cell count. A run that fills more cells
by accepting weaker claims is worse, and the metrics here are arranged so that
shows up rather than reads as progress: accepted claims and locator precision
are counted alongside anything that was answered, and a rise in answered
GeoTeaser cells that buys no new accepted claim is recorded as harm.

**Action 4 is the rule that matters most.** An `if_not_why_not` is not a
retrieval error, and neither is a gap that correctly asks for an expert. Both
are the pipeline working. Counting them as misses would reward a retriever that
invents an answer over one that reports honestly that there is none, which is
the exact failure the whole assignment is written against. Absences are counted
here so they are visible, and they appear in no error term.

Three decisions, and only three. `NO_GO` is evidence of harm. `ITERATE` is
insufficient evidence of gain -- including the case where a measurement was
simply not taken. `GO_SHADOW_EXPANSION` needs a measured gain and no harm.
There is no `GO_ACTIVE`: promoting a shadow retriever to live traffic is a
person's call, and this module cannot make it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

NO_GO = 'NO_GO'
ITERATE = 'ITERATE'
GO_SHADOW_EXPANSION = 'GO_SHADOW_EXPANSION'

DECISIONS = (NO_GO, ITERATE, GO_SHADOW_EXPANSION)

ANSWERED = frozenset({'supported', 'corroborated'})
ABSENT = frozenset({'missing', 'not_applicable', 'blocked_expert'})

# Only these two outcomes are evidence a requirement can rest on. `advisory_only`
# is where an analogue lands, `no_evidence` is where a failed lookup lands, and
# neither becomes an accepted claim by being retrieved more often.
ACCEPTED_OUTCOMES = frozenset({'supported', 'corroborated'})

# A retracted or stale claim is not evidence, whatever retrieval did to find it.
LIVE_CLAIM_STATES = frozenset({'active', 'conflict'})

# What makes a locator exact rather than gestural. A claim that cites a document
# without a page is not attributable, and the completion criterion asks for
# attribution at the field or requirement level. The locator schema has no
# dedicated record identifier, so a registry locator carries the record id in
# `document_id`; a registry claim without one names no record.
EXACT_LOCATOR_FIELDS = {
    'document_span': ('document_id', 'document_version', 'page'),
    'registry_record': ('document_id',),
    'gis_feature': ('layer_id', 'feature_id'),
    'datacube_output': ('run_id',),
    'expert_statement': ('review_id',),
}

# The dossier's `authority_kind` vocabulary has no web value, so a web-sourced
# claim cannot be recognised by authority alone. Recognised by `source_type`
# instead, and the gap recorded in GMM's register rather than papered over.
#
# Matched as whole tokens, never as substrings, and `search` is deliberately not
# a marker. Both rules come from one measurement over 2078 source records in five
# real runs: the complete production vocabulary is `gis`, `web`, `knowledge_base`,
# `linked_gis_project`, `kb`, `orchestration`, `datacube`, `derived`,
# `gis_project`, `web_registry`, `web_search`, `knowledge_base_search` and
# `linked_project_gis`. Substring matching on `search` classifies all 18
# `knowledge_base_search` records as web-sourced -- a knowledge-base search record
# is the opposite of a web source -- while every genuinely web value already
# carries the `web` token. The marker bought nothing and cost that. The same
# substring rule reads `desk_research` and `research_report` as web, because both
# contain `research`.
#
# It matters because `web_source_share` is a harm criterion: a share that rises
# while confirming no more requirements fails the comparison, so miscounted
# knowledge searches can turn an `ITERATE` into a `NO_GO` on evidence that was
# never web.
#
# The false negative remains and is not fixable here: a web source named
# `online_portal` carries no marker and stays invisible. That is A-38, and it
# closes when the dossier vocabulary gains a web authority, not when this set
# grows -- growing it is what produced the false positive.
WEB_SOURCE_MARKERS = frozenset({'web', 'internet'})

_SOURCE_TYPE_TOKENS = re.compile(r'[^0-9a-zA-Zа-яёА-ЯЁ]+')

# The shadow dispatcher's record schema, copied rather than imported: it belongs
# to `utils/geotizer_rag_runtime.py`, which sits outside the purity boundary and
# is not ours to rename. `test_rag_ab_evaluation.py` asserts the two spellings
# still agree, so a rename there is reported here instead of silently read as an
# empty trace.
SHADOW_RECORD_SCHEMA = 'geomas.rag_shadow_dispatch.v2'
SHADOW_ARM_NAME = 'geomas_rag_v2_shadow'


@dataclass(frozen=True)
class RetrievalTrace:
    """Action 2's latency, and where it comes from.

    `ENABLE_GEOMAS_RAG_V2_SHADOW` already writes one JSONL record per dispatched
    query to `GEOMAS_RAG_SHADOW_TRACE_DIR`. That trace is the only place a real
    latency figure for either arm exists, so this reads it rather than inventing
    a number -- and reports nothing when there is no trace to read.
    """

    arm: str
    queries: int
    succeeded: int
    failed: int
    latency_ms: int
    slowest_query_ms: int
    statuses: tuple[tuple[str, int], ...]


def read_retrieval_trace(records: Sequence[Mapping[str, Any]]) -> RetrievalTrace | None:
    """One arm's retrieval trace, from the shadow dispatcher's JSONL records."""
    dispatched = [record for record in records if record.get('schema') == SHADOW_RECORD_SCHEMA]
    if not dispatched:
        return None

    latencies = [int(round(float(record.get('latency_ms') or 0))) for record in dispatched]
    counted: dict[str, int] = {}
    for record in dispatched:
        status = str(record.get('status') or 'unknown')
        counted[status] = counted.get(status, 0) + 1

    return RetrievalTrace(
        arm=str(dispatched[0].get('arm') or SHADOW_ARM_NAME),
        queries=len(dispatched),
        succeeded=counted.get('ok', 0),
        failed=len(dispatched) - counted.get('ok', 0),
        latency_ms=sum(latencies),
        slowest_query_ms=max(latencies),
        statuses=tuple(sorted(counted.items())),
    )


@dataclass(frozen=True)
class ArmMetrics:
    """Action 2, one arm. Nothing here judges anything."""

    arm: str
    confirmed_requirements: int
    applicable_requirements: int
    accepted_claims: int
    claims: int
    exact_locators: int
    claims_without_an_exact_locator: tuple[str, ...]
    conflicts_found: int
    web_sourced_claims: int
    recorded_absences: int
    expert_gaps: int
    latency_ms: int | None = None
    retrieval_queries: int | None = None
    failed_queries: int | None = None

    @property
    def web_source_share(self) -> float:
        return round(self.web_sourced_claims / self.claims, 4) if self.claims else 0.0

    @property
    def locator_precision(self) -> float:
        return round(self.exact_locators / self.claims, 4) if self.claims else 0.0


@dataclass(frozen=True)
class GeotizerAcceptance:
    """Action 3: the downstream GeoTeaser acceptance, measured on its own.

    Kept apart from `ArmMetrics` on purpose. Folding cells into the same score
    as requirements is what lets a retriever look better by filling more of
    them, and the task is named against exactly that.
    """

    arm: str
    template_fields: int
    answered_fields: int
    conflicted_fields: int
    recorded_absences: int
    expert_approved_not_applicable: int
    semantic_completeness_percent: float | None
    unsourced_filled_fields: tuple[str, ...]


@dataclass(frozen=True)
class Arm:
    name: str
    metrics: ArmMetrics
    geotizer: GeotizerAcceptance
    attribution_gaps: tuple[str, ...]
    claims: Mapping[str, Mapping[str, Any]]

    @property
    def attribution_preserved(self) -> bool:
        return not self.attribution_gaps


@dataclass(frozen=True)
class Comparison:
    control: Arm
    shadow: Arm | None
    lost_claims: tuple[str, ...]
    gained_claims: tuple[str, ...]
    locator_regressions: tuple[str, ...]
    harms: tuple[str, ...]
    blockers: tuple[str, ...]
    gains: tuple[str, ...]
    decision: str


def _has_exact_locator(claim: Mapping[str, Any]) -> bool:
    locator = claim.get('source_locator') or {}
    required = EXACT_LOCATOR_FIELDS.get(locator.get('kind'))
    if required is None:
        return False
    return all(locator.get(name) for name in required)


def _is_web_sourced(claim: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> bool:
    for source_id in claim.get('source_refs') or ():
        source_type = str(sources.get(source_id, {}).get('source_type') or '').lower()
        tokens = {token for token in _SOURCE_TYPE_TOKENS.split(source_type) if token}
        if tokens & WEB_SOURCE_MARKERS:
            return True
    return False


def live_claims(dossier: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        claim['claim_id']: claim for claim in dossier.get('claims') or () if claim.get('state') in LIVE_CLAIM_STATES
    }


def measure_requirements(
    arm: str,
    dossier: Mapping[str, Any],
    cpr_projection: Mapping[str, Any],
    *,
    latency_ms: int | None = None,
    retrieval_trace: RetrievalTrace | None = None,
) -> ArmMetrics:
    """Action 2: confirmed requirements, accepted claims, exact locators,
    conflicts found, the WEB share and latency.

    Latency comes from the arm's retrieval trace when there is one. An explicit
    `latency_ms` overrides it, which is what the harness scenarios use; neither
    is invented when both are absent.
    """
    sources = {source['source_id']: source for source in dossier.get('sources') or ()}
    claims = live_claims(dossier)
    coverage = cpr_projection.get('coverage') or ()

    return ArmMetrics(
        arm=arm,
        confirmed_requirements=sum(1 for row in coverage if row['state'] in ANSWERED),
        applicable_requirements=sum(1 for row in coverage if row['applicability'] != 'not_applicable'),
        accepted_claims=sum(1 for claim in claims.values() if claim['resolution_outcome'] in ACCEPTED_OUTCOMES),
        claims=len(claims),
        exact_locators=sum(1 for claim in claims.values() if _has_exact_locator(claim)),
        claims_without_an_exact_locator=tuple(
            sorted(claim_id for claim_id, claim in claims.items() if not _has_exact_locator(claim))
        ),
        conflicts_found=len(dossier.get('conflicts') or ()),
        web_sourced_claims=sum(1 for claim in claims.values() if _is_web_sourced(claim, sources)),
        # Action 4: counted so they are visible, and deliberately absent from
        # every error term in `compare`.
        recorded_absences=sum(1 for row in coverage if row['state'] in ABSENT),
        expert_gaps=len(dossier.get('gaps') or ()),
        latency_ms=latency_ms if latency_ms is not None else _traced_latency(retrieval_trace),
        retrieval_queries=retrieval_trace.queries if retrieval_trace else None,
        failed_queries=retrieval_trace.failed if retrieval_trace else None,
    )


def _traced_latency(trace: RetrievalTrace | None) -> int | None:
    return trace.latency_ms if trace is not None else None


def accept_geotizer(arm: str, geotizer_projection: Mapping[str, Any]) -> GeotizerAcceptance:
    """Action 3: the GeoTeaser side, measured separately from the CPR side."""
    fields = geotizer_projection.get('fields') or ()
    totals = geotizer_projection.get('totals') or {}

    return GeotizerAcceptance(
        arm=arm,
        template_fields=geotizer_projection.get('template_field_count', len(fields)),
        answered_fields=sum(1 for row in fields if row['state'] in ANSWERED),
        conflicted_fields=sum(1 for row in fields if row['state'] == 'conflicted'),
        recorded_absences=sum(1 for row in fields if row['state'] in ABSENT),
        expert_approved_not_applicable=totals.get('expert_approved_not_applicable', 0),
        semantic_completeness_percent=totals.get('semantic_completeness_percent'),
        unsourced_filled_fields=tuple(
            row['field_key']
            for row in fields
            if row['state'] in (ANSWERED | {'conflicted'}) and not row['supporting_claim_ids']
        ),
    )


def attribution_gaps(cpr_projection: Mapping[str, Any], geotizer_projection: Mapping[str, Any]) -> tuple[str, ...]:
    """The completion criterion, as a list of the rows that break it: an
    answered row that names nothing it rests on."""
    gaps = [
        row['requirement_id']
        for row in cpr_projection.get('coverage') or ()
        if row['state'] in ANSWERED
        and not (
            row.get('supporting_claim_ids') or row.get('supporting_estimate_ids') or row.get('supporting_figure_ids')
        )
    ]
    gaps += [
        row['field_key']
        for row in geotizer_projection.get('fields') or ()
        if row['state'] in ANSWERED and not row.get('supporting_claim_ids')
    ]
    return tuple(gaps)


def attribution_is_preserved(cpr_projection: Mapping[str, Any], geotizer_projection: Mapping[str, Any]) -> bool:
    """Attribution survives to the requirement and to the field."""
    return not attribution_gaps(cpr_projection, geotizer_projection)


def measure(
    arm: str,
    dossier: Mapping[str, Any],
    cpr_projection: Mapping[str, Any],
    geotizer_projection: Mapping[str, Any],
    *,
    latency_ms: int | None = None,
    retrieval_trace: RetrievalTrace | None = None,
) -> Arm:
    """One arm, end to end: the dossier it produced and both projections of it."""
    return Arm(
        name=arm,
        metrics=measure_requirements(
            arm,
            dossier,
            cpr_projection,
            latency_ms=latency_ms,
            retrieval_trace=retrieval_trace,
        ),
        geotizer=accept_geotizer(arm, geotizer_projection),
        attribution_gaps=attribution_gaps(cpr_projection, geotizer_projection),
        claims=live_claims(dossier),
    )


def _harms(control: Arm, shadow: Arm) -> list[str]:
    """Evidence the shadow arm is worse. Any one of these is a `NO_GO`."""
    before, after = control.metrics, shadow.metrics
    harms: list[str] = []

    lost = sorted(set(control.claims) - set(shadow.claims))
    if lost:
        harms.append(f'{len(lost)} claim(s) present in v1 are absent in v2: {", ".join(lost)}')

    regressions = _locator_regressions(control, shadow)
    if regressions:
        harms.append(f'{len(regressions)} claim(s) lost an exact locator: {", ".join(regressions)}')

    if after.accepted_claims < before.accepted_claims:
        harms.append(
            f'fewer accepted claims than the control: {after.accepted_claims} against {before.accepted_claims}'
        )
    if after.locator_precision < before.locator_precision:
        harms.append(f'locator precision fell: {after.locator_precision} against {before.locator_precision}')

    # A rise in the WEB share that buys no new confirmed requirement is the
    # WEB-last rule being eroded, not an improvement.
    if (
        after.web_source_share > before.web_source_share
        and after.confirmed_requirements <= before.confirmed_requirements
    ):
        harms.append(f'the WEB source share rose to {after.web_source_share} without confirming more requirements')

    # The task's own title, as a rule: more cells is not the measure.
    if (
        shadow.geotizer.answered_fields > control.geotizer.answered_fields
        and after.accepted_claims <= before.accepted_claims
    ):
        harms.append(
            f'{shadow.geotizer.answered_fields - control.geotizer.answered_fields} more GeoTeaser '
            f'cell(s) filled without one more accepted claim'
        )

    newly_unsourced = sorted(
        set(shadow.geotizer.unsourced_filled_fields) - set(control.geotizer.unsourced_filled_fields)
    )
    if newly_unsourced:
        harms.append(f'{len(newly_unsourced)} GeoTeaser cell(s) filled with no path back to a claim')

    # A query that never came back is a retrieval failure, unlike an absence
    # that came back and said there is nothing there.
    if before.failed_queries is not None and after.failed_queries is not None:
        if after.failed_queries > before.failed_queries:
            harms.append(
                f'{after.failed_queries} retrieval quer(ies) failed against {before.failed_queries} in the control'
            )

    if not shadow.attribution_preserved:
        harms.append(
            f'the shadow arm loses attribution on {len(shadow.attribution_gaps)} row(s): '
            f'{", ".join(shadow.attribution_gaps[:5])}'
        )

    return harms


def _locator_regressions(control: Arm, shadow: Arm) -> tuple[str, ...]:
    return tuple(
        sorted(
            claim_id
            for claim_id in set(control.claims) & set(shadow.claims)
            if _has_exact_locator(control.claims[claim_id]) and not _has_exact_locator(shadow.claims[claim_id])
        )
    )


def _gains(control: Arm, shadow: Arm) -> list[str]:
    before, after = control.metrics, shadow.metrics
    gains: list[str] = []
    if after.confirmed_requirements > before.confirmed_requirements:
        gains.append(
            f'{after.confirmed_requirements - before.confirmed_requirements} more confirmed CPR requirement(s)'
        )
    if after.accepted_claims > before.accepted_claims:
        gains.append(f'{after.accepted_claims - before.accepted_claims} more accepted claim(s)')
    if after.conflicts_found > before.conflicts_found:
        gains.append(
            f'{after.conflicts_found - before.conflicts_found} more conflict(s) found -- a '
            f'disagreement surfaced is evidence gained, not a defect'
        )
    if after.locator_precision > before.locator_precision:
        gains.append(f'locator precision rose to {after.locator_precision} from {before.locator_precision}')
    return gains


def _blockers(control: Arm, shadow: Arm) -> list[str]:
    """Not harm -- absence of the evidence promotion would need."""
    blockers: list[str] = []
    for arm in (control, shadow):
        if arm.metrics.latency_ms is None:
            blockers.append(f'latency was not measured on the {arm.name} arm')
    return blockers


def compare(control: Arm, shadow: Arm | None) -> Comparison:
    """The A/B verdict, and the reasons behind it.

    A shadow arm is promoted to wider shadow traffic only when it is better on
    evidence, worse on nothing, and fully measured. Harm stops it outright; a
    missing measurement does not condemn it, it just leaves nothing to promote
    on -- which is `ITERATE`, the same answer as no shadow arm at all.
    """
    if shadow is None:
        return Comparison(
            control=control,
            shadow=None,
            lost_claims=(),
            gained_claims=(),
            locator_regressions=(),
            harms=(),
            blockers=('no shadow arm was run, so there is nothing to promote',),
            gains=(),
            decision=ITERATE,
        )

    harms = _harms(control, shadow)
    blockers = _blockers(control, shadow)
    gains = _gains(control, shadow)

    if harms:
        decision = NO_GO
    elif gains and not blockers:
        decision = GO_SHADOW_EXPANSION
    else:
        decision = ITERATE
        if not gains:
            blockers.append('no regression and no measurable gain')

    return Comparison(
        control=control,
        shadow=shadow,
        lost_claims=tuple(sorted(set(control.claims) - set(shadow.claims))),
        gained_claims=tuple(sorted(set(shadow.claims) - set(control.claims))),
        locator_regressions=_locator_regressions(control, shadow),
        harms=tuple(harms),
        blockers=tuple(blockers),
        gains=tuple(gains),
        decision=decision,
    )


def arm_record(arm: Arm) -> dict[str, Any]:
    metrics, geotizer = arm.metrics, arm.geotizer
    return {
        'arm': arm.name,
        'requirements': {
            'confirmed': metrics.confirmed_requirements,
            'applicable': metrics.applicable_requirements,
            'recorded_absences': metrics.recorded_absences,
        },
        'claims': {
            'live': metrics.claims,
            'accepted': metrics.accepted_claims,
            'exact_locators': metrics.exact_locators,
            'locator_precision': metrics.locator_precision,
            'without_an_exact_locator': list(metrics.claims_without_an_exact_locator),
        },
        'conflicts_found': metrics.conflicts_found,
        'web': {
            'sourced_claims': metrics.web_sourced_claims,
            'share': metrics.web_source_share,
        },
        'expert_gaps': metrics.expert_gaps,
        'latency_ms': metrics.latency_ms,
        'retrieval_queries': metrics.retrieval_queries,
        'failed_queries': metrics.failed_queries,
        # Action 3: reported under its own key, never added to the numbers above.
        'geotizer_acceptance': {
            'template_fields': geotizer.template_fields,
            'answered_fields': geotizer.answered_fields,
            'conflicted_fields': geotizer.conflicted_fields,
            'recorded_absences': geotizer.recorded_absences,
            'expert_approved_not_applicable': geotizer.expert_approved_not_applicable,
            'semantic_completeness_percent': geotizer.semantic_completeness_percent,
            'unsourced_filled_fields': list(geotizer.unsourced_filled_fields),
        },
        'attribution_preserved': arm.attribution_preserved,
        'attribution_gaps': list(arm.attribution_gaps),
    }


def report(comparison: Comparison) -> dict[str, Any]:
    """The A/B record, in the shape GMM stores."""
    return {
        'schema_version': 1,
        'task': 'RAG-EVAL-01',
        'control': arm_record(comparison.control),
        'shadow': arm_record(comparison.shadow) if comparison.shadow is not None else None,
        'lost_claims': list(comparison.lost_claims),
        'gained_claims': list(comparison.gained_claims),
        'locator_regressions': list(comparison.locator_regressions),
        'harms': list(comparison.harms),
        'blockers': list(comparison.blockers),
        'gains': list(comparison.gains),
        'decision': comparison.decision,
        # Stated in the record itself, not only in the code: promoting a shadow
        # retriever to live traffic is a person's decision.
        'go_active_is_not_an_automatic_outcome': True,
        'absences_are_not_retrieval_errors': True,
    }


__all__ = [
    'ABSENT',
    'ACCEPTED_OUTCOMES',
    'ANSWERED',
    'Arm',
    'ArmMetrics',
    'Comparison',
    'DECISIONS',
    'GO_SHADOW_EXPANSION',
    'GeotizerAcceptance',
    'ITERATE',
    'LIVE_CLAIM_STATES',
    'NO_GO',
    'RetrievalTrace',
    'SHADOW_ARM_NAME',
    'SHADOW_RECORD_SCHEMA',
    'accept_geotizer',
    'arm_record',
    'attribution_gaps',
    'attribution_is_preserved',
    'compare',
    'live_claims',
    'measure',
    'measure_requirements',
    'read_retrieval_trace',
    'report',
]
