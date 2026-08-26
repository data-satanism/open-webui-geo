"""RAG-EVAL-01: the retrieval A/B, judged on the dossier rather than the cells.

The completion criterion is two things: attribution survives to the requirement
and to the field, and the run lands on one of `NO_GO | ITERATE |
GO_SHADOW_EXPANSION` without ever producing `GO_ACTIVE`. Both are asserted here.

Action 4 gets its own section. An `if_not_why_not` and an expert-requiring gap
are the pipeline working, and a harness that scored them as retrieval misses
would prefer an invented answer to an honest absence.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402
from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402
from open_webui.services.evaluation import rag_ab  # noqa: E402
from run_rag_ab_evaluation import SCENARIOS, run  # noqa: E402

DATA = Path(__file__).resolve().parent / 'data'


@pytest.fixture(scope='module')
def dossier():
    return json.loads((DATA / 'lekyn-dossier.example.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def evidence():
    return run()


@pytest.fixture(scope='module')
def control(dossier):
    cpr = cpr_project.build_projection(dossier)
    geotizer = gt_project.build_projection(dossier)
    return rag_ab.measure('v1', dossier, cpr, geotizer, latency_ms=800)


def arm(name, dossier, *, latency_ms=800):
    return rag_ab.measure(
        name,
        dossier,
        cpr_project.build_projection(dossier),
        gt_project.build_projection(dossier),
        latency_ms=latency_ms,
    )


# -- the completion criterion ----------------------------------------------


def test_attribution_survives_to_the_requirement_and_the_field(dossier):
    cpr = cpr_project.build_projection(dossier)
    geotizer = gt_project.build_projection(dossier)

    assert rag_ab.attribution_gaps(cpr, geotizer) == ()
    assert rag_ab.attribution_is_preserved(cpr, geotizer)


def test_an_answered_row_that_names_nothing_breaks_attribution(dossier):
    cpr = copy.deepcopy(cpr_project.build_projection(dossier))
    geotizer = gt_project.build_projection(dossier)
    row = next(r for r in cpr['coverage'] if r['state'] in rag_ab.ANSWERED)
    row['supporting_claim_ids'] = []
    row['supporting_estimate_ids'] = []
    row['supporting_figure_ids'] = []

    assert rag_ab.attribution_gaps(cpr, geotizer) == (row['requirement_id'],)
    assert not rag_ab.attribution_is_preserved(cpr, geotizer)


def test_a_shadow_arm_that_loses_attribution_cannot_be_promoted(control, dossier):
    cpr = copy.deepcopy(cpr_project.build_projection(dossier))
    row = next(r for r in cpr['coverage'] if r['state'] in rag_ab.ANSWERED)
    row['supporting_claim_ids'] = []
    row['supporting_estimate_ids'] = []
    row['supporting_figure_ids'] = []
    shadow = rag_ab.measure('v2', dossier, cpr, gt_project.build_projection(dossier), latency_ms=800)

    comparison = rag_ab.compare(control, shadow)

    assert comparison.decision == rag_ab.NO_GO
    assert any('attribution' in harm for harm in comparison.harms)


def test_the_decision_is_always_one_of_the_three(evidence):
    assert evidence['decision'] in rag_ab.DECISIONS
    for check in evidence['harness_checks']:
        assert check['decision'] in rag_ab.DECISIONS


def test_go_active_is_not_in_the_vocabulary():
    """Not merely never produced -- not expressible. Promotion to live traffic
    is a person's decision and this module has no word for it."""
    assert rag_ab.DECISIONS == (rag_ab.NO_GO, rag_ab.ITERATE, rag_ab.GO_SHADOW_EXPANSION)
    assert 'GO_ACTIVE' not in dir(rag_ab)
    source = (REPO_ROOT / 'backend/open_webui/services/evaluation/rag_ab.py').read_text(encoding='utf-8')
    assert "'GO_ACTIVE'" not in source


# -- action 4: absences are not retrieval errors ----------------------------


def test_the_recorded_absences_are_counted_and_never_charged(control):
    """69 CPR rows and 347 workbook cells report an absence. Both numbers are
    in the record; neither reaches a harm."""
    assert control.metrics.recorded_absences == 69
    assert control.geotizer.recorded_absences == 347
    assert control.metrics.expert_gaps == 4

    identical = rag_ab.compare(control, control)

    assert identical.harms == ()
    assert identical.decision == rag_ab.ITERATE


def test_an_arm_with_more_absences_is_not_worse_for_that_alone(control, dossier):
    """A v2 that retracts a source honestly reports more absences. That must not
    be what condemns it -- the lost claim is, and the message says so."""
    mutated = copy.deepcopy(dossier)
    claim = next(c for c in mutated['claims'] if c['claim_id'] == 'clm-distance-road')
    claim['state'] = 'retracted'
    shadow = arm('v2', mutated)

    comparison = rag_ab.compare(control, shadow)

    assert shadow.geotizer.recorded_absences > control.geotizer.recorded_absences
    assert comparison.decision == rag_ab.NO_GO
    assert not any('absence' in harm for harm in comparison.harms)
    assert any('clm-distance-road' in harm for harm in comparison.harms)


def test_a_blocked_expert_row_is_not_a_miss(control, dossier):
    cpr = cpr_project.build_projection(dossier)
    blocked = [r for r in cpr['coverage'] if r['state'] == 'blocked_expert']

    assert blocked
    for row in blocked:
        assert row['if_not_why_not']['state'] == 'blocked_expert'
    assert control.metrics.confirmed_requirements + control.metrics.recorded_absences + 2 == len(cpr['coverage'])


# -- action 2: what is measured ---------------------------------------------


def test_the_measured_axes_are_all_present(evidence):
    """Confirmed requirements, accepted claims, exact locators, conflicts, the
    WEB share and latency -- every axis action 2 names."""
    control = evidence['control']

    assert control['requirements']['confirmed'] == 3
    assert control['claims']['accepted'] == 5
    assert control['claims']['exact_locators'] == 8
    assert control['conflicts_found'] == 1
    assert control['web']['share'] == 0.0
    assert control['latency_ms'] is None


def test_an_analogue_is_never_an_accepted_claim(control, dossier):
    """Two of the nine claims are analogies, resolved `advisory_only`. A
    retriever that finds more of them has not found more evidence."""
    advisory = [c for c in dossier['claims'] if c['resolution_outcome'] == 'advisory_only']

    assert len(advisory) == 2
    assert control.metrics.claims == 9
    assert control.metrics.accepted_claims == 5


def test_a_registry_claim_with_no_record_id_is_not_an_exact_locator(control):
    """The one claim the control arm cannot attribute precisely. Reported rather
    than rounded away: 8 of 9, not 'all of them'."""
    assert control.metrics.claims_without_an_exact_locator == ('clm-licence-number',)
    assert control.metrics.locator_precision == 0.8889


def test_a_stale_claim_is_not_evidence_however_it_was_found(dossier):
    mutated = copy.deepcopy(dossier)
    next(c for c in mutated['claims'] if c['claim_id'] == 'clm-stage')['state'] = 'stale'

    assert set(rag_ab.live_claims(mutated)) == set(rag_ab.live_claims(dossier)) - {'clm-stage'}


# -- latency, from the shadow dispatcher's own trace ------------------------


def shadow_record(**overrides):
    record = {
        'schema': rag_ab.SHADOW_RECORD_SCHEMA,
        'arm': rag_ab.SHADOW_ARM_NAME,
        'status': 'ok',
        'latency_ms': 120.0,
    }
    record.update(overrides)
    return record


def test_the_schema_string_still_matches_the_dispatchers():
    """Copied, not imported: the dispatcher sits outside the purity boundary and
    the constant is not ours to rename. A rename there must fail here rather
    than quietly turn every trace into an empty one."""
    from open_webui.utils import geotizer_rag_runtime

    assert rag_ab.SHADOW_RECORD_SCHEMA == geotizer_rag_runtime.SHADOW_RECORD_SCHEMA


def test_latency_comes_from_the_retrieval_trace(dossier):
    trace = rag_ab.read_retrieval_trace([shadow_record(latency_ms=120.0), shadow_record(latency_ms=310.4)])
    measured = arm('v2', dossier, latency_ms=None)

    assert trace.queries == 2
    assert trace.latency_ms == 430
    assert trace.slowest_query_ms == 310
    assert measured.metrics.latency_ms is None

    with_trace = rag_ab.measure(
        'v2',
        dossier,
        cpr_project.build_projection(dossier),
        gt_project.build_projection(dossier),
        retrieval_trace=trace,
    )

    assert with_trace.metrics.latency_ms == 430
    assert with_trace.metrics.retrieval_queries == 2


def test_no_trace_means_no_latency_rather_than_zero():
    assert rag_ab.read_retrieval_trace([]) is None
    assert rag_ab.read_retrieval_trace([{'schema': 'something.else.v1'}]) is None


def test_a_failed_query_is_a_retrieval_error_unlike_an_absence(control, dossier):
    """The distinction action 4 turns on. A query that came back empty is an
    absence; one that never came back is a failure, and only the second counts
    against the arm."""
    clean = rag_ab.read_retrieval_trace([shadow_record(), shadow_record()])
    broken = rag_ab.read_retrieval_trace([shadow_record(), shadow_record(status='timeout')])
    before = rag_ab.measure(
        'v1',
        dossier,
        cpr_project.build_projection(dossier),
        gt_project.build_projection(dossier),
        retrieval_trace=clean,
    )
    after = rag_ab.measure(
        'v2',
        dossier,
        cpr_project.build_projection(dossier),
        gt_project.build_projection(dossier),
        retrieval_trace=broken,
    )

    assert broken.failed == 1
    assert broken.statuses == (('ok', 1), ('timeout', 1))

    comparison = rag_ab.compare(before, after)

    assert comparison.decision == rag_ab.NO_GO
    assert any('failed' in harm for harm in comparison.harms)


# -- action 3: the GeoTeaser side, measured on its own ----------------------


def test_the_geotizer_acceptance_is_reported_separately(evidence):
    acceptance = evidence['control']['geotizer_acceptance']

    assert acceptance['template_fields'] == 351
    assert acceptance['answered_fields'] == 4
    assert acceptance['semantic_completeness_percent'] == 1.14
    assert acceptance['unsourced_filled_fields'] == []
    # And it is not folded into the requirement numbers.
    assert 'answered_fields' not in evidence['control']['requirements']


def test_more_cells_without_more_evidence_is_harm_not_progress(control, dossier):
    """The task's title as an assertion: a retriever cannot buy a verdict with
    cell count."""
    geotizer = copy.deepcopy(gt_project.build_projection(dossier))
    row = next(r for r in geotizer['fields'] if r['state'] == 'missing')
    row['state'] = 'supported'
    row['supporting_claim_ids'] = ['clm-stage']
    shadow = rag_ab.measure('v2', dossier, cpr_project.build_projection(dossier), geotizer, latency_ms=800)

    comparison = rag_ab.compare(control, shadow)

    assert comparison.decision == rag_ab.NO_GO
    assert comparison.harms == ('1 more GeoTeaser cell(s) filled without one more accepted claim',)


def test_a_cell_filled_with_no_path_back_to_a_claim_is_caught(control, dossier):
    geotizer = copy.deepcopy(gt_project.build_projection(dossier))
    row = next(r for r in geotizer['fields'] if r['state'] == 'missing')
    row['state'] = 'conflicted'
    row['supporting_claim_ids'] = []
    shadow = rag_ab.measure('v2', dossier, cpr_project.build_projection(dossier), geotizer, latency_ms=800)

    comparison = rag_ab.compare(control, shadow)

    assert comparison.decision == rag_ab.NO_GO
    assert any('no path back to a claim' in harm for harm in comparison.harms)
    assert shadow.geotizer.unsourced_filled_fields == (row['field_key'],)


# -- the decision rules ------------------------------------------------------


def test_no_shadow_arm_iterates_rather_than_promoting(control):
    comparison = rag_ab.compare(control, None)

    assert comparison.decision == rag_ab.ITERATE
    assert comparison.blockers == ('no shadow arm was run, so there is nothing to promote',)
    assert comparison.harms == ()


def test_a_gain_with_an_unmeasured_axis_does_not_promote(control, dossier):
    """Insufficient evidence is not the same as evidence of harm. It iterates."""
    mutated = copy.deepcopy(dossier)
    mutated['claims'].append(_new_claim())
    shadow = arm('v2', mutated, latency_ms=None)

    comparison = rag_ab.compare(control, shadow)

    assert comparison.gains
    assert comparison.decision == rag_ab.ITERATE
    assert comparison.blockers == ('latency was not measured on the v2 arm',)


def test_real_new_evidence_is_the_only_route_to_expansion(control, dossier):
    mutated = copy.deepcopy(dossier)
    mutated['claims'].append(_new_claim())
    shadow = arm('v2', mutated)

    comparison = rag_ab.compare(control, shadow)

    assert comparison.decision == rag_ab.GO_SHADOW_EXPANSION
    assert comparison.gained_claims == ('clm-regional-geology',)
    assert comparison.harms == ()


def test_a_surfaced_conflict_counts_as_a_gain_not_a_defect(control, dossier):
    """A retriever that finds the second, disagreeing source has done its job.
    A harness that scored conflicts as noise would reward the one that stopped
    at the first answer."""
    mutated = copy.deepcopy(dossier)
    # `conflict_kind`, `resolution_state`, `project_id` and `detected_at`: none
    # of those are conflict fields. The dossier contract names `kind`,
    # `resolution` and `statement`, all required, and this fixture had invented
    # a different vocabulary -- so the gain being asserted here was proved by an
    # object no dossier could hold.
    #
    # The first correction renamed the keys and kept `value_disagreement` as the
    # kind, which is not in the enum either (`value`, `estimate_identity`,
    # `temporal`, `spatial_domain`, `authority`, `unit`). The precondition did
    # not catch that and is not supposed to: it checks that required fields are
    # present, not that values are in their vocabularies. That is the schema's
    # job, and this fixture is not validated against it.
    mutated['conflicts'].append(
        {
            'conflict_id': 'cft-extra',
            'claim_ids': ['clm-licence-number', 'clm-licence-number-doc'],
            'kind': 'value',
            'statement': 'Лицензия названа по-разному в двух источниках.',
            'resolution': 'unresolved',
            'resolved_by_review_id': None,
        }
    )
    shadow = arm('v2', mutated)

    comparison = rag_ab.compare(control, shadow)

    assert any('more conflict' in gain for gain in comparison.gains)


def test_the_web_share_may_not_rise_for_nothing(control, dossier):
    mutated = copy.deepcopy(dossier)
    mutated['sources'].append(
        {
            'source_id': 'src-web',
            'project_id': mutated['project_scope']['project_id'],
            'source_type': 'web_page',
            'source_version': '2025-06-01',
            'authority_kind': 'approved_report',
            'acl_decision': 'granted',
            'state': 'active',
        }
    )
    next(c for c in mutated['claims'] if c['claim_id'] == 'clm-stage')['source_refs'] = ['src-web']
    shadow = arm('v2', mutated)

    comparison = rag_ab.compare(control, shadow)

    assert shadow.metrics.web_source_share > 0
    assert comparison.decision == rag_ab.NO_GO
    assert any('WEB source share' in harm for harm in comparison.harms)


def test_a_knowledge_search_is_not_counted_as_a_web_source(dossier):
    """`web_source_share` is a harm criterion, so a value miscounted into it can
    turn an `ITERATE` into a `NO_GO` on evidence that was never web.

    The values below are the complete `source_type` vocabulary observed across
    2078 source records in five real runs. `knowledge_base_search` is the one
    that mattered: the recogniser matched markers as substrings and `search` was
    a marker, so all 18 of its records counted as web-sourced. Every genuinely
    web value carries the `web` token, so the marker bought nothing.

    Two spellings that are not yet in production are pinned alongside, because
    they are the ones a plausible next source_type would use and both are
    non-web: `desk_research` and `research_report` each contain `research`.
    """
    web = {'web', 'web_registry', 'web_search'}
    not_web = {
        'knowledge_base_search', 'knowledge_base', 'kb', 'gis', 'gis_project',
        'linked_gis_project', 'linked_project_gis', 'datacube', 'orchestration',
        'derived', 'desk_research', 'research_report',
    }

    def sourced(source_type):
        return rag_ab._is_web_sourced(
            {'source_refs': ['s']}, {'s': {'source_type': source_type}}
        )

    assert {t for t in web if sourced(t)} == web, 'a real web source stopped counting'
    assert {t for t in not_web if sourced(t)} == set(), 'a non-web source counted as web'
    assert 'search' not in rag_ab.WEB_SOURCE_MARKERS


def test_the_web_recogniser_still_cannot_see_an_unmarked_web_source(dossier):
    """The other half of A-38, pinned so the gap is not mistaken for closed.

    Token matching fixes the false positive. It cannot fix the false negative:
    a web source named for its publisher carries no marker and is invisible,
    and no marker tuple closes that -- only a web value in the dossier's
    `authority_kind` vocabulary does.
    """
    assert rag_ab._is_web_sourced(
        {'source_refs': ['s']}, {'s': {'source_type': 'online_portal'}}
    ) is False


@pytest.mark.xfail(
    strict=True,
    reason='the dossier authority_kind enum has no web value, so a web source is '
    'recognised by source_type; Ontology Approver decision, register A-38',
)
def test_a_web_source_is_recognisable_from_its_authority(dossier):
    authorities = {source['authority_kind'] for source in dossier['sources']}

    assert 'web' in authorities or any('web' in a for a in authorities)


# -- the record ---------------------------------------------------------------


def test_the_record_states_what_was_not_measured(evidence):
    assert evidence['shadow'] is None
    assert evidence['shadow_arm_was_run'] is False
    assert 'canary' in evidence['shadow_arm_absent_because']
    assert evidence['control_arm_is_a_real_measurement'] is True
    assert evidence['go_active_is_not_an_automatic_outcome'] is True
    assert evidence['absences_are_not_retrieval_errors'] is True


def test_the_record_is_not_weaker_than_the_contract_before_it(evidence):
    """`geomas.rag_field_counterfactual.v1` requires an index version per arm
    and forbids publishing shadow output. Both carry over: null with a stated
    reason is a report, an absent field is a silence."""
    versions = evidence['index_versions']

    assert set(versions) >= {'v1_index_version', 'v2_index_version'}
    assert versions['v1_index_version'] is None
    assert versions['null_because']
    assert evidence['publish_shadow_output'] is False


def test_the_other_decision_vocabulary_is_reported_not_absorbed(evidence):
    """Two vocabularies answer the same question, and `GO_CONTROLLED_ACTIVE`
    has no counterpart in this task's three values. Renaming either would hide
    that; the record names both and points at the register entry."""
    other = evidence['related_decision_vocabulary']

    assert other['contract'] == 'geomas.rag_field_counterfactual.v1'
    assert set(other['values']) == {'GO_SHADOW_ITERATION', 'NO_GO_ACTIVE', 'GO_CONTROLLED_ACTIVE'}
    assert not set(other['values']) & set(rag_ab.DECISIONS)
    assert 'A-43' in other['note']


def test_every_derived_arm_is_marked_synthetic(evidence):
    """Nothing in this record may read as a measurement of a retriever that was
    never run."""
    assert len(evidence['harness_checks']) == len(SCENARIOS) + 1
    for check in evidence['harness_checks']:
        assert check['synthetic'] is True
        assert check['mutation'].strip()


def test_each_harness_check_lands_where_it_is_supposed_to(evidence):
    for check in evidence['harness_checks']:
        assert check['decision'] == check['expected_decision'], check['id']


def test_the_review_matrix_asks_rather_than_answers(evidence):
    matrix = evidence['expert_review_matrix']

    assert len(matrix) == 5
    assert {item['owner'] for item in matrix} == {'Runtime Owner', 'Ontology Approver'}
    for item in matrix:
        assert item['verdict'] is None
        assert item['question'].strip()


def test_the_committed_evidence_matches_a_fresh_run(evidence):
    committed = json.loads((DATA / 'lekyn-rag-ab-evidence.json').read_text(encoding='utf-8'))

    assert committed == evidence


def _new_claim():
    from run_rag_ab_evaluation import NEW_CLAIM

    return copy.deepcopy(NEW_CLAIM)
