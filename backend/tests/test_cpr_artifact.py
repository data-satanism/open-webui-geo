"""CORE-BOUNDARY-01 action 3: `services/artifacts/cpr/`.

Requirement planning, section coverage, the narrative plan and the audit,
exercised against the same Лекын reference run that GMM's contracts use.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from open_webui.services.artifacts.cpr import audit, catalog, coverage, narrative, requirements
from open_webui.services.artifacts.cpr.errors import CprContractError

DATA = Path(__file__).resolve().parent / 'data'


@pytest.fixture(scope='module')
def dossier():
    return json.loads((DATA / 'lekyn-dossier.example.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def projection():
    return json.loads((DATA / 'lekyn-cpr-projection.example.json').read_text(encoding='utf-8'))


@pytest.fixture
def mutable_projection(projection):
    return copy.deepcopy(projection)


@pytest.fixture
def scratch_assets(tmp_path):
    """A writable copy of the shipped assets, for the drift tests."""
    target = tmp_path / 'assets'
    shutil.copytree(catalog.ASSETS, target)
    return target


# -- the catalog copy ------------------------------------------------------


def test_the_shipped_catalog_matches_its_recorded_digest():
    assert len(catalog.load_catalog()['requirements']) == 126


def test_the_provenance_names_where_the_catalog_came_from():
    record = catalog.provenance()['files'][catalog.CATALOG_FILE]

    assert record['source_repository'] == 'data-satanism/GMM'
    assert record['source_path'] == 'contracts/cpr/cpr_requirement_catalog.v1.json'
    assert len(record['source_commit']) == 40
    assert record['sha256'] == hashlib.sha256((catalog.ASSETS / catalog.CATALOG_FILE).read_bytes()).hexdigest()


def test_a_drifted_copy_is_refused_rather_than_used(scratch_assets):
    """Two copies of a controlled vocabulary that drift silently would let the
    CPR be planned against one set of applicability rules and audited against
    another, with both looking right."""
    path = scratch_assets / catalog.CATALOG_FILE
    edited = json.loads(path.read_text(encoding='utf-8'))
    edited['requirements'][0]['lifecycle_applicability'] = ['ore_reserves']
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')

    with pytest.raises(CprContractError, match='does not match its recorded digest'):
        catalog.load_catalog(scratch_assets)


def test_a_missing_provenance_record_is_refused(scratch_assets):
    (scratch_assets / 'provenance.json').write_text('{"files": {}}', encoding='utf-8')

    with pytest.raises(CprContractError, match='no provenance record'):
        catalog.load_catalog(scratch_assets)


def test_the_catalog_is_still_a_draft_and_says_so():
    """Planning against a draft is fine. Presenting the output as approved is
    not, so the status travels with the plan."""
    assert catalog.is_draft() is True


# -- requirement planning --------------------------------------------------


def test_the_plan_keeps_inapplicable_requirements_and_marks_them():
    """§10's risk is 119 requirements treated as mandatory at an early stage.
    Dropping them from the plan would hide the judgement instead of recording
    it."""
    plans = requirements.plan_requirements('exploration_results')

    assert len(plans) == 126
    assert len(requirements.applicable_requirements('exploration_results')) == 89
    assert any(not plan.applicable for plan in plans)


@pytest.mark.parametrize(
    'stage,expected',
    [
        ('exploration_results', 89),
        ('mineral_resources', 114),
        ('ore_reserves', 61),
        ('technical_study', 52),
    ],
)
def test_applicability_follows_the_stage(stage, expected):
    assert len(requirements.applicable_requirements(stage)) == expected


def test_an_unknown_stage_is_refused():
    with pytest.raises(CprContractError, match='unknown lifecycle stage'):
        requirements.plan_requirements('drilling')


def test_reserves_are_never_planned_as_applicable_at_exploration():
    for plan in requirements.applicable_requirements('exploration_results'):
        assert plan.section != 6, plan.requirement_id


def test_sections_come_back_in_the_templates_own_order():
    sections = list(requirements.requirements_by_section('exploration_results'))

    assert sections == sorted(sections)
    assert sections[0] == 0


def test_no_requirement_plainly_allows_an_analogy():
    """§2: an analogue may not stand in as a direct object estimate."""
    for plan in requirements.plan_requirements('mineral_resources'):
        assert plan.analogy_policy in {'forbidden', 'allowed_if_labeled'}


def test_the_reviewer_roles_never_include_a_competent_person():
    """The artefact may not sign as one, so no requirement may route to one."""
    workload = requirements.reviewer_workload('exploration_results')

    assert 'Competent Person' not in workload
    assert workload['Domain Reviewer'] > 0
    assert sum(workload.values()) == 89


def test_a_proposed_question_is_a_recorded_gap_not_coverage():
    gaps = requirements.coverage_gaps('exploration_results')

    assert gaps
    plans = {p.requirement_id: p for p in requirements.plan_requirements('exploration_results')}
    for rid in gaps:
        assert not plans[rid].competency_questions
        assert plans[rid].proposed_competency_questions


def test_every_applicable_requirement_states_what_evidence_it_needs():
    expectations = requirements.evidence_expectations('exploration_results')

    assert len(expectations) == 89
    assert all(kinds for kinds in expectations.values())


# -- section coverage ------------------------------------------------------


def test_coverage_reports_every_section_not_only_the_answered_ones(projection, dossier):
    sections = coverage.section_coverage(projection, dossier)

    assert len(sections) == 10
    assert sum(section.planned for section in sections) == 126


def test_an_unaddressed_requirement_is_not_folded_into_missing(projection, dossier):
    """`missing` means the projection looked and recorded why. Saying nothing
    at all is a different state and the six-state vocabulary has no word for
    it."""
    sections = coverage.section_coverage(projection, dossier)
    unaddressed = [rid for section in sections for rid in section.unaddressed]

    assert len(unaddressed) == 79
    covered = {row['requirement_id'] for row in projection['coverage']}
    assert not (set(unaddressed) & covered)


def test_the_denominator_subtracts_only_an_expert_approved_not_applicable(projection, dossier):
    """CPR-6.1.1 is refused on gap-reserves, which rev-001 marked not
    applicable -- but it is out of stage at exploration results and so was
    never in the denominator. Subtracting it there would remove it twice."""
    result = coverage.semantic_completeness(projection, dossier)

    assert result['applicable'] == 89
    assert result['expert_approved_not_applicable'] == 0
    assert result['denominator'] == 89


def test_an_expert_approved_not_applicable_leaves_the_denominator(mutable_projection, dossier):
    """CPR-6.1.1 is refused on a gap the reviewer marked not applicable, but it
    is out of stage at exploration results, so it was never in the denominator.
    Point a reviewed gap at an in-stage requirement and the denominator moves."""
    row = next(r for r in mutable_projection['coverage'] if r['requirement_id'] == 'CPR-3.1.1')
    row['state'] = 'not_applicable'
    row['render_state'] = 'not_rendered'
    row['gap_ids'] = ['gap-mining-method']
    row['if_not_why_not'] = next(
        gap['if_not_why_not'] for gap in dossier['gaps'] if gap['gap_id'] == 'gap-mining-method'
    )

    result = coverage.semantic_completeness(mutable_projection, dossier)

    assert result['expert_approved_not_applicable'] == 1
    assert result['denominator'] == 88


def test_an_unapproved_not_applicable_stays_in_the_denominator(mutable_projection, dossier):
    """Otherwise a missing answer becomes a higher score."""
    row = next(r for r in mutable_projection['coverage'] if r['requirement_id'] == 'CPR-3.1.1')
    row['state'] = 'not_applicable'
    row['render_state'] = 'not_rendered'
    row['gap_ids'] = ['gap-drilling']  # a real gap, but no reviewer marked it n/a
    row['if_not_why_not'] = next(gap['if_not_why_not'] for gap in dossier['gaps'] if gap['gap_id'] == 'gap-drilling')

    result = coverage.semantic_completeness(mutable_projection, dossier)

    assert result['expert_approved_not_applicable'] == 0
    assert result['denominator'] == 89


def test_a_partial_projection_is_not_a_measurement(projection, dossier):
    result = coverage.semantic_completeness(projection, dossier)

    assert result['scope'] == 'reference_slice'
    assert result['measurable'] is False
    assert result['unaddressed']


def test_sections_needing_attention_are_the_ones_with_a_conflict_or_a_hole(projection, dossier):
    sections = coverage.section_coverage(projection, dossier)
    flagged = {s.section for s in coverage.sections_needing_attention(sections)}

    assert flagged
    for section in coverage.section_coverage(projection, dossier):
        if section.section not in flagged:
            assert not section.unaddressed
            assert not section.conflicted
            assert not section.blocked_expert


# -- the narrative plan ----------------------------------------------------


def test_the_narrative_plans_only_what_the_projection_renders(projection, dossier):
    blocks = narrative.plan_narrative(projection, dossier)
    counts = narrative.sentences_by_kind(blocks)

    assert counts == {'statement': 5, 'absence': 4, 'conflict': 1}
    skipped = [rid for block in blocks for rid in block.skipped]
    assert sorted(skipped) == ['CPR-4.1.1', 'CPR-6.1.1']


def test_a_conflict_sentence_keeps_both_sides(projection, dossier):
    blocks = narrative.plan_narrative(projection, dossier)
    conflicts = [sentence for block in blocks for sentence in block.sentences if sentence.kind == narrative.CONFLICT]

    assert [s.requirement_id for s in conflicts] == ['CPR-ADD-11']
    for sentence in conflicts:
        assert len(sentence.claim_ids) >= 2
        assert sentence.conflict_ids


def test_a_statement_with_no_provenance_is_refused(mutable_projection, dossier):
    """This is §2's "no plausible placeholder" made structural: there is no
    sentence kind that asserts something the dossier does not hold."""
    row = next(r for r in mutable_projection['coverage'] if r['state'] == 'supported')
    row['supporting_claim_ids'] = []
    row['supporting_estimate_ids'] = []
    row['supporting_figure_ids'] = []

    with pytest.raises(CprContractError, match='does not hold'):
        narrative.plan_narrative(mutable_projection, dossier)


def test_an_absence_sentence_without_a_reason_is_refused(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r['state'] == 'missing')
    row.pop('if_not_why_not')

    with pytest.raises(CprContractError, match='recorded reason'):
        narrative.plan_narrative(mutable_projection, dossier)


def test_a_conflict_sentence_without_the_record_is_refused(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r['state'] == 'conflicted')
    row['conflict_ids'] = []

    with pytest.raises(CprContractError, match='conflict record'):
        narrative.plan_narrative(mutable_projection, dossier)


def test_a_missing_mandatory_figure_is_refused(mutable_projection, dossier):
    # CPR-1.3.1 cites claims as well as the figure, so removing the figure
    # leaves a sentence that still has provenance -- the figure rule is what
    # has to reject it, not the empty-provenance rule.
    row = next(r for r in mutable_projection['coverage'] if r['requirement_id'] == 'CPR-1.3.1')
    row['supporting_figure_ids'] = []

    with pytest.raises(CprContractError, match='requires a figure'):
        narrative.plan_narrative(mutable_projection, dossier)


def test_the_plan_carries_ids_and_never_text(projection, dossier):
    """Wording belongs to the renderer; provenance belongs to the plan. A
    sentence carrying its own text would be a second copy of the dossier."""
    blocks = narrative.plan_narrative(projection, dossier)

    for block in blocks:
        for sentence in block.sentences:
            for value in vars(sentence).values():
                assert not isinstance(value, str) or ' ' not in value or value.isupper() is False
            assert not hasattr(sentence, 'text')
            assert not hasattr(sentence, 'value')


def test_analogy_sentences_are_identifiable(projection, dossier):
    """They are legitimate -- the template asks about adjacent objects -- but a
    renderer has to label them, so it has to be able to find them."""
    blocks = narrative.plan_narrative(projection, dossier)
    flagged = narrative.analogy_sentences(blocks, dossier)

    assert [s.requirement_id for s in flagged] == ['CPR-1.3.1']
    assert all(s.analogy_allowed for s in flagged)


def test_every_cited_claim_exists_in_the_dossier(projection, dossier):
    blocks = narrative.plan_narrative(projection, dossier)
    known = {claim['claim_id'] for claim in dossier['claims']}

    assert narrative.cited_claim_ids(blocks) <= known


# -- the audit -------------------------------------------------------------


def test_the_reference_run_has_no_blocking_finding(projection, dossier):
    findings = audit.audit_projection(projection, dossier)

    assert audit.blocking(findings) == ()


def test_the_audit_reports_the_unaddressed_requirements(projection, dossier):
    findings = audit.audit_projection(projection, dossier)
    summary = audit.audit_summary(findings)

    assert summary['by_code'] == {'unaddressed': 79}
    assert summary['blocking'] == 0


def test_the_audit_never_signs_conformance(projection, dossier):
    """§2 forbids the artefact claiming JORC/NAEN conformance. A clean audit
    means no rule was broken, not that the report conforms."""
    summary = audit.audit_summary(audit.audit_projection(projection, dossier))

    assert summary['signs_conformance'] is False


def test_an_analogy_answering_a_requirement_that_forbids_it_is_a_finding(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r['requirement_id'] == 'CPR-0.1')
    row['supporting_claim_ids'] = ['clm-analogue-grade']

    codes = {f.code for f in audit.audit_projection(mutable_projection, dossier)}

    assert 'analogy_forbidden' in codes


def test_a_paraphrased_gap_is_a_finding(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r.get('gap_ids'))
    row['if_not_why_not'] = dict(row['if_not_why_not'], reason='по другой причине')

    codes = {f.code for f in audit.audit_projection(mutable_projection, dossier)}

    assert 'reason_diverges_from_gap' in codes


def test_an_expert_absence_the_dossier_never_recorded_is_a_finding(mutable_projection, dossier):
    row = next(
        r
        for r in mutable_projection['coverage']
        if r.get('if_not_why_not', {}).get('reason_kind') == 'no_source_exists' and not r.get('gap_ids')
    )
    row['if_not_why_not'] = dict(row['if_not_why_not'], reason_kind='expert_decision_required')

    codes = {f.code for f in audit.audit_projection(mutable_projection, dossier)}

    assert 'unreviewed_expert_absence' in codes


def test_a_projection_from_another_run_is_a_blocking_finding(mutable_projection, dossier):
    mutable_projection['dossier_run_id'] = '00000000-0000-0000-0000-000000000000'

    codes = {f.code for f in audit.blocking(audit.audit_projection(mutable_projection, dossier))}

    assert 'wrong_dossier_run' in codes


def test_an_unsupported_presence_is_a_blocking_finding(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r['state'] == 'supported')
    row['supporting_claim_ids'] = []
    row['supporting_estimate_ids'] = []
    row['supporting_figure_ids'] = []

    codes = {f.code for f in audit.blocking(audit.audit_projection(mutable_projection, dossier))}

    assert 'unsupported_presence' in codes


def test_an_applicability_that_disagrees_with_the_catalog_is_a_finding(mutable_projection, dossier):
    row = next(r for r in mutable_projection['coverage'] if r['applicability'] == 'not_applicable')
    row['applicability'] = 'exploration_results'

    codes = {f.code for f in audit.audit_projection(mutable_projection, dossier)}

    assert 'applicability' in codes


def test_a_requirement_that_is_not_in_the_catalog_is_a_finding(mutable_projection, dossier):
    mutable_projection['coverage'][0]['requirement_id'] = 'CPR-9.9.9'

    codes = {f.code for f in audit.audit_projection(mutable_projection, dossier)}

    assert 'unknown_requirement' in codes
