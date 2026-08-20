"""CPR-SLICE-01 step 2: building the projection from the dossier.

The slice's completion criterion is that every selected requirement has a
state, and every substantive statement has an exact source locator or is marked
an expert interpretation. Both are properties of what this builder produces, so
they are asserted against the Лекын run rather than described.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from open_webui.services.artifacts.cpr import audit, catalog, coverage, narrative, project
from open_webui.services.artifacts.cpr.errors import CprContractError

DATA = Path(__file__).resolve().parent / 'data'


@pytest.fixture(scope='module')
def dossier():
    return json.loads((DATA / 'lekyn-dossier.example.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def projection(dossier):
    return project.build_projection(dossier)


@pytest.fixture
def mutable_dossier(dossier):
    return copy.deepcopy(dossier)


# -- the map ---------------------------------------------------------------


def test_the_map_matches_its_digest_and_the_catalog():
    document = project.load_map()

    assert len(document['entries']) == 74
    assert document['catalog_version'] == catalog.catalog_version()
    assert document['status'] == 'draft_for_domain_review'


def test_a_drifted_map_is_refused(tmp_path):
    import shutil

    assets = tmp_path / 'assets'
    shutil.copytree(catalog.ASSETS, assets)
    path = assets / project.MAP_FILE
    edited = json.loads(path.read_text(encoding='utf-8'))
    edited['entries'][0]['predicates'] = ['anything_at_all']
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')

    with pytest.raises(CprContractError, match='digest'):
        project.load_map(assets)


# -- the completion criterion ----------------------------------------------


def test_every_requirement_in_the_slice_has_a_state(projection):
    """100% of the selected requirements, which is the first half of the
    criterion."""
    states = {row['requirement_id']: row['state'] for row in projection['coverage']}

    assert set(states) == set(project.slice_requirement_ids())
    assert len(states) == 74
    assert all(states.values())


def test_every_substantive_statement_carries_a_locator_or_is_an_expert_reading(projection, dossier):
    """The second half. A rendered statement rests on a claim, and every one of
    those claims carries a source locator; anything that cannot is marked an
    expert interpretation instead of being written anyway."""
    claims = {claim['claim_id']: claim for claim in dossier['claims']}

    for row in projection['coverage']:
        if row['state'] not in {'supported', 'corroborated', 'conflicted'}:
            continue
        assert row['supporting_claim_ids'], row['requirement_id']
        for claim_id in row['supporting_claim_ids']:
            locator = claims[claim_id]['source_locator']
            assert locator['kind'], claim_id
            assert claims[claim_id]['source_refs'], claim_id


def test_the_document_makes_no_conformance_claim(projection, dossier):
    summary = audit.audit_summary(audit.audit_projection(projection, dossier))

    assert summary['signs_conformance'] is False


def test_the_generated_projection_passes_its_own_audit(projection, dossier):
    findings = audit.audit_projection(projection, dossier)

    assert audit.blocking(findings) == ()


def test_the_only_findings_are_requirements_outside_the_slice(projection, dossier):
    summary = audit.audit_summary(audit.audit_projection(projection, dossier))

    assert set(summary['by_code']) == {'unaddressed'}


# -- what the Лекын run actually answers -----------------------------------


def test_the_run_is_content_deep_at_low_formal_completeness(projection, dossier):
    """The expected behaviour the assignment names. Three answers out of 88 is
    a true statement about this object, not a failure of the assembler."""
    result = coverage.semantic_completeness(projection, dossier)

    assert result['answered'] == 3
    assert result['denominator'] == 88
    assert result['measurable'] is False


def test_the_licence_is_corroborated_by_two_independent_sources(projection):
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-1.5.1')

    assert row['state'] == 'corroborated'
    assert row['supporting_claim_ids'] == ['clm-licence-number', 'clm-licence-number-doc']


def test_the_two_resource_figures_stay_a_conflict(projection):
    """§2 forbids resolving a disagreement by picking the more plausible value,
    so both requirements that read the resource keep both sides."""
    rows = [r for r in projection['coverage'] if r['state'] == 'conflicted']

    assert {r['requirement_id'] for r in rows} == {'CPR-ADD-11', 'CPR-GEN-04'}
    for row in rows:
        assert row['conflict_ids'] == ['cft-au-p1']
        assert len(row['supporting_claim_ids']) == 2


def test_the_analogue_answers_only_the_requirement_that_allows_one(projection, dossier):
    """§2: an analogue is never a direct object estimate."""
    using = [
        row['requirement_id'] for row in projection['coverage'] if 'clm-analogue-grade' in row['supporting_claim_ids']
    ]

    assert using == ['CPR-1.3.1']


def test_an_analogy_never_reaches_a_requirement_that_forbids_one(mutable_dossier):
    """Point the analogue claim at a predicate a forbidding requirement reads,
    and it must still not be used."""
    claim = next(c for c in mutable_dossier['claims'] if c['value_origin']['kind'] == 'analogy')
    claim['predicate'] = 'regional_geology'  # CPR-2.1.1, analogy forbidden

    built = project.build_projection(mutable_dossier)
    row = next(r for r in built['coverage'] if r['requirement_id'] == 'CPR-2.1.1')

    assert claim['claim_id'] not in row['supporting_claim_ids']
    assert row['state'] == 'missing'


# -- absence -----------------------------------------------------------------


def test_drilling_absence_carries_the_reviewers_own_reason(projection, dossier):
    """Action 4: drilling, QA/QC and reserves show if_not_why_not and the
    required expert action."""
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-3.1.5')
    gap = next(g for g in dossier['gaps'] if g['gap_id'] == 'gap-drilling')

    assert row['state'] == 'missing'
    assert row['gap_ids'] == ['gap-drilling']
    assert row['if_not_why_not'] == gap['if_not_why_not']
    assert row['expert_action_ids'] == ['act-drilling-programme']


def test_reserves_absence_is_the_reviewers_not_applicable(projection):
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-1.4.4')

    assert row['state'] == 'not_applicable'
    assert row['gap_ids'] == ['gap-reserves']
    assert row['render_state'] == 'not_rendered'


def test_an_absence_with_no_reviewer_record_says_what_was_searched(projection):
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-2.1.1')

    assert row['state'] == 'missing'
    assert row['gap_ids'] == []
    assert row['if_not_why_not']['reason_kind'] == 'no_source_exists'
    assert row['if_not_why_not']['searched_source_ids'] == [
        'src-gis',
        'src-presentation',
        'src-project',
        'src-registry',
    ]
    assert 'regional_geology' in row['if_not_why_not']['reason']


def test_an_expert_reading_is_blocked_rather_than_written(projection):
    """The catalog types these as expert_interpretation. No amount of retrieval
    produces one, so the artefact says so instead of composing something."""
    blocked = {row['requirement_id'] for row in projection['coverage'] if row['state'] == 'blocked_expert'}

    assert blocked == {'CPR-1.4.2', 'CPR-2.1.4', 'CPR-7.1.2', 'CPR-ADD-06'}


def test_every_absence_has_a_recorded_reason(projection):
    for row in projection['coverage']:
        if row['state'] in {'missing', 'not_applicable', 'blocked_expert'}:
            assert row['if_not_why_not']['reason'].strip(), row['requirement_id']
            assert row['if_not_why_not']['state'] == row['state'], row['requirement_id']


def test_out_of_stage_requirements_say_which_stage_they_need(projection):
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-4.2.2')

    assert row['state'] == 'not_applicable'
    assert row['if_not_why_not']['reason_kind'] == 'stage_not_reached'
    assert 'mineral_resources' in row['if_not_why_not']['reason']


# -- evidence hygiene --------------------------------------------------------


def test_a_stale_claim_stops_answering(mutable_dossier):
    """A source version was withdrawn. Answering from the withdrawn claim would
    be worse than reporting the requirement unanswered."""
    for claim in mutable_dossier['claims']:
        if claim['claim_id'] == 'clm-stage':
            claim['state'] = 'stale'

    built = project.build_projection(mutable_dossier)
    row = next(r for r in built['coverage'] if r['requirement_id'] == 'CPR-1.2.1')

    assert row['state'] == 'missing'
    assert row['supporting_claim_ids'] == []


def test_an_estimate_nobody_cited_is_not_evidence(mutable_dossier):
    """§10 forbids sweeping incompatible categories together, so an estimate is
    only cited where a matched claim points at it."""
    built = project.build_projection(mutable_dossier)

    for row in built['coverage']:
        for estimate_id in row['supporting_estimate_ids']:
            cited = {
                claim['estimate_id']
                for claim in mutable_dossier['claims']
                if claim['claim_id'] in row['supporting_claim_ids']
            }
            assert estimate_id in cited, row['requirement_id']


def test_a_figure_counts_only_where_it_supports_a_matched_claim(projection):
    row = next(r for r in projection['coverage'] if r['requirement_id'] == 'CPR-1.3.1')

    assert row['supporting_figure_ids'] == ['fig-adjacent']


def test_the_projection_carries_no_value_and_no_locator(projection):
    """The dossier owns those. Two copies of a number are two numbers."""
    text = json.dumps(projection, ensure_ascii=False)

    for marker in ('"value"', '"unit"', '"source_locator"', '"quoted_text"', '"page"'):
        assert marker not in text


def test_the_projection_is_marked_a_slice(projection):
    """74 of 126 requirements. Its totals are not a coverage measurement."""
    assert projection['projection_scope'] == 'reference_slice'
    assert projection['catalog_requirement_count'] == 126


def test_the_narrative_plans_from_the_generated_projection(projection, dossier):
    blocks = narrative.plan_narrative(projection, dossier)
    counts = narrative.sentences_by_kind(blocks)

    assert counts['statement'] == 3
    assert counts['conflict'] == 2
    assert counts['absence'] == 42


def test_totals_agree_with_the_rows(projection):
    totals = projection['totals']
    rows = projection['coverage']

    for state in ('supported', 'corroborated', 'conflicted', 'missing', 'not_applicable', 'blocked_expert'):
        assert totals[state] == sum(1 for row in rows if row['state'] == state), state
    assert (
        sum(
            totals[s]
            for s in ('supported', 'corroborated', 'conflicted', 'missing', 'not_applicable', 'blocked_expert')
        )
        == 74
    )
