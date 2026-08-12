"""UAT-CPR-GT-01: both artefacts on one frozen dossier.

The completion criterion, in three parts: the ids and values of facts agree
across both artefacts, there are no hidden contradictions, and re-rendering
changes no hash. All three are reachable from a frozen dossier and are asserted
here. The parts that need the canary contour or a human are listed by the run
itself and are not claimed.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from run_cpr_geotizer_uat import REVIEW_MATRIX, run  # noqa: E402

from open_webui.services.artifacts import consistency  # noqa: E402
from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402
from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402

DATA = Path(__file__).resolve().parent / 'data'


@pytest.fixture(scope='module')
def dossier():
    return json.loads((DATA / 'lekyn-dossier.example.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def evidence():
    return run()


@pytest.fixture(scope='module')
def projections(dossier):
    return cpr_project.build_projection(dossier), gt_project.build_projection(dossier)


@pytest.fixture
def mutable(dossier):
    return copy.deepcopy(dossier)


# -- the completion criterion ----------------------------------------------


def test_the_two_artefacts_do_not_contradict_each_other(projections, dossier):
    cpr, geotizer = projections

    assert consistency.compare(cpr, geotizer, dossier) == ()


def test_neither_artefact_can_disagree_about_a_number(projections):
    """Not because they were checked and agreed — because neither carries a
    value. Both cite claim ids, so the numbers live in one place."""
    cpr, geotizer = projections

    for projection in (cpr, geotizer):
        text = json.dumps(projection, ensure_ascii=False)
        assert '"value"' not in text
        assert '"unit"' not in text


def test_a_shared_fact_is_the_same_claim_on_both_sides(projections):
    cpr, geotizer = projections
    shared = consistency.shared_claims(cpr, geotizer)

    assert set(shared) == {'clm-licence-number', 'clm-licence-number-doc', 'clm-stage'}
    assert shared['clm-stage']['cpr'] == ['CPR-1.2.1']
    assert shared['clm-stage']['geotizer'] == ['geotizer_object.v1.r014.a01']


def test_rerendering_changes_no_hash(evidence):
    assert evidence['rerender']['hashes_changed'] == []
    assert evidence['rerender']['artifacts_compared'] == 5


def test_a_rerender_reaches_no_retrieval_model_or_gis(evidence):
    """The renderers take the projection and the dossier and nothing else, so
    the counters are structurally zero rather than measured and hoped for."""
    rerender = evidence['rerender']

    for counter in ('retrieval_calls', 'model_calls', 'gis_calls', 'web_calls'):
        assert rerender[counter] == 0


# -- the divergences it would catch ----------------------------------------


def test_a_conflict_settled_on_one_side_only_is_caught(projections, dossier):
    """The hidden contradiction the criterion forbids: one artefact treating a
    disputed number as settled."""
    cpr, geotizer = projections
    mutated = copy.deepcopy(cpr)
    row = next(r for r in mutated['coverage'] if r['state'] == 'conflicted')
    row['state'] = 'supported'
    row['conflict_ids'] = []

    findings = consistency.compare(mutated, geotizer, dossier)

    assert findings
    assert findings[0].code == 'conflict_reported_on_one_side_only'
    assert findings[0].cpr_locations


def test_a_conflict_nobody_recorded_is_caught(projections, mutable):
    """The inverse: an artefact calling something a conflict when the dossier
    holds no conflict record for it."""
    cpr, geotizer = projections
    mutable['conflicts'] = []

    findings = consistency.compare(cpr, geotizer, mutable)

    assert {f.code for f in findings} == {'conflict_without_a_dossier_record'}


def test_a_claim_both_cited_and_declared_absent_is_caught(projections, dossier):
    cpr, geotizer = projections
    mutated = copy.deepcopy(geotizer)
    row = next(r for r in mutated['fields'] if r['state'] == 'missing')
    row['supporting_claim_ids'] = ['clm-stage']

    findings = consistency.compare(cpr, mutated, dossier)

    assert 'claim_cited_and_declared_absent' in {f.code for f in findings}


def test_two_different_runs_are_refused_before_anything_else(projections, dossier):
    cpr, geotizer = projections
    mutated = copy.deepcopy(geotizer)
    mutated['dossier_run_id'] = '00000000-0000-0000-0000-000000000000'

    findings = consistency.compare(cpr, mutated, dossier)

    assert [f.code for f in findings] == ['different_dossier_run']


# -- action 2: reuse -------------------------------------------------------


def test_one_evidence_run_feeds_both_documents(evidence):
    """The claim the whole design rests on, as a number rather than an
    assertion. Three of nine claims are used by both; none is unused."""
    reuse = evidence['agreement']['reuse']

    assert reuse['claims_in_dossier'] == 9
    assert reuse['used_by_cpr'] == 7
    assert reuse['used_by_geotizer'] == 5
    assert reuse['used_by_both'] == 3
    assert reuse['used_by_neither'] == []


def test_no_artefact_cites_a_claim_the_dossier_does_not_hold(evidence):
    assert evidence['agreement']['reuse']['cited_but_absent_from_the_dossier'] == []


# -- action 4: the conflicting estimates and sites 1-4 ---------------------


def test_the_project_and_presentation_estimates_stay_unresolved(evidence, projections):
    """12 т on 2024-11-15 against 20 т on 2025-03-01. Different date, author and
    method: two estimates, not one with a discrepancy."""
    cpr, _ = projections
    conflicted = [r for r in cpr['coverage'] if r['state'] == 'conflicted']

    assert {r['requirement_id'] for r in conflicted} == {'CPR-ADD-11', 'CPR-GEN-04'}
    assert evidence['cpr']['totals']['conflicted'] == 2


def test_sites_one_to_four_are_reported_as_the_teasers_own_subdivision(projections):
    _, geotizer = projections
    sites = [
        row
        for row in geotizer['fields']
        if row['field_key'].startswith(
            ('geotizer_object.v1.r050', 'geotizer_object.v1.r051', 'geotizer_object.v1.r052', 'geotizer_object.v1.r053')
        )
    ]

    assert len(sites) == 24
    for row in sites:
        assert row['projection_kind'] == 'ARTIFACT_SPECIFIC'
        assert row['state'] == 'missing'
        assert 'subdivision' in row['if_not_why_not']['reason']


# -- what the run does not claim -------------------------------------------


def test_the_run_names_what_it_could_not_cover(evidence):
    """The contour this task names is the isolated canary, which is
    unrecoverable. Saying so is part of the evidence."""
    uncovered = evidence['not_covered_without_a_contour']

    assert len(uncovered) == 3
    assert any('WEB-last' in item for item in uncovered)
    assert any('stream loss' in item for item in uncovered)


def test_the_review_matrix_asks_rather_than_answers(evidence):
    """Nothing automated may judge whether the coverage is good enough. The
    matrix is emitted with empty verdicts."""
    matrix = evidence['expert_review_matrix']

    assert len(matrix) == len(REVIEW_MATRIX)
    for item in matrix:
        assert item['verdict'] is None
        assert item['owner'] in {'Domain Reviewer', 'Ontology Approver', 'Runtime Owner'}
        assert item['question'].strip()


def test_the_evidence_carries_the_run_identity(evidence, dossier):
    assert evidence['dossier_run_id'] == dossier['dossier_run_id']
    assert evidence['frozen_inputs_hash'] == dossier['frozen_inputs_hash']
    assert len(evidence['idempotency_key_digest']) == 64
    assert evidence['projection_versions'] == {
        'cpr': 'cpr_slice_projection.v1',
        'geotizer': 'cpr_to_geotizer.v1',
    }


def test_the_committed_evidence_matches_a_fresh_run(evidence):
    """The file in the repository is what this code produces today, or it is a
    record of something that no longer happens."""
    committed = json.loads((DATA / 'lekyn-uat-evidence.json').read_text(encoding='utf-8'))

    assert committed == evidence
