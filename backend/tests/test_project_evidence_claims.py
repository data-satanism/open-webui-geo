"""The one rule both projections have to share, and the one copy that may stay.

`consistency.compare` checks that the CPR and the workbook agree about the facts
they report. It cannot check that they agree about which facts they *looked at*
-- two artefacts silently ignoring the same claim agree perfectly. So claim
eligibility is shared code rather than a convention, and these tests pin that it
stays shared.

The evaluator is the deliberate exception. `rag_ab` imports nothing: a
measurement whose definition moves when the measured code moves is not a
measurement. It therefore keeps its own copy of `LIVE_CLAIM_STATES`, and the
last test here is what makes that copy honest rather than merely separate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from open_webui.services.artifacts.cpr import project as cpr_project
from open_webui.services.artifacts.geotizer import project as gt_project
from open_webui.services.evaluation import rag_ab
from open_webui.services.project_evidence import claims

SERVICES = Path(__file__).resolve().parents[1] / 'open_webui/services'


def _claim(predicate='licence_number', state='active', origin='direct', **extra):
    return {
        'claim_id': extra.pop('claim_id', 'clm-1'),
        'predicate': predicate,
        'state': state,
        'value_origin': {'kind': origin},
        **extra,
    }


# -- the rule itself --------------------------------------------------------


@pytest.mark.parametrize('state', sorted(claims.LIVE_CLAIM_STATES))
def test_a_live_claim_is_eligible(state):
    assert claims.claim_is_eligible(
        _claim(state=state), {'licence_number'}, analogy_forbidden=False
    )


@pytest.mark.parametrize('state', ['stale', 'retracted', 'superseded', ''])
def test_a_withdrawn_claim_is_not_evidence(state):
    """A source version was withdrawn. Answering from it is worse than not
    answering."""
    assert not claims.claim_is_eligible(
        _claim(state=state), {'licence_number'}, analogy_forbidden=False
    )


def test_an_unresolved_conflict_stays_live():
    """Both artefacts must be able to report a disagreement. Dropping the claim
    would hide it instead."""
    assert 'conflict' in claims.LIVE_CLAIM_STATES


def test_an_analogue_is_invisible_where_it_is_forbidden():
    """§2: not ranked lower -- not seen at all."""
    analogue = _claim(origin='analogy')

    assert claims.claim_is_eligible(analogue, {'licence_number'}, analogy_forbidden=False)
    assert not claims.claim_is_eligible(analogue, {'licence_number'}, analogy_forbidden=True)


def test_a_conflict_touching_one_matched_claim_is_not_this_answer_s_conflict():
    """Two sides, or it is somebody else's dispute being attributed here."""
    dossier = {
        'conflicts': [
            {'conflict_id': 'cft-both', 'claim_ids': ['clm-1', 'clm-2']},
            {'conflict_id': 'cft-one-side', 'claim_ids': ['clm-1', 'clm-elsewhere']},
        ]
    }
    matched = [_claim(claim_id='clm-1'), _claim(claim_id='clm-2')]

    assert claims.conflicts_over(dossier, matched) == ['cft-both']


def test_only_granted_and_active_sources_are_readable():
    dossier = {
        'sources': [
            {'source_id': 'src-ok', 'acl_decision': 'granted', 'state': 'active'},
            {'source_id': 'src-denied', 'acl_decision': 'denied', 'state': 'active'},
            {'source_id': 'src-withdrawn', 'acl_decision': 'granted', 'state': 'retracted'},
        ]
    }

    assert claims.granted_source_ids(dossier) == ['src-ok']


def test_a_reviewed_gap_is_found_by_any_of_the_predicates():
    dossier = {'gaps': [{'gap_id': 'gap-1', 'missing_predicates': ['b', 'c']}]}

    assert claims.reviewed_gap(dossier, ['a', 'c'])['gap_id'] == 'gap-1'
    assert claims.reviewed_gap(dossier, ['a']) is None


def test_overlapping_gaps_do_not_depend_on_the_order_of_the_array():
    """A reviewer can record a broad gap and a specific one over the same
    predicate, and the two can carry different states.

    `missing`, `not_applicable` and `blocked_expert` are different answers about
    the deposit. Which one a cell shows may not depend on the order a JSON array
    happens to be in -- that would make the artefact a function of formatting.
    """
    broad = {'gap_id': 'gap-broad', 'missing_predicates': ['drilling_method']}
    specific = {'gap_id': 'gap-a-specific', 'missing_predicates': ['drilling_method']}

    one_way = claims.reviewed_gaps({'gaps': [broad, specific]}, ['drilling_method'])
    other_way = claims.reviewed_gaps({'gaps': [specific, broad]}, ['drilling_method'])

    assert [gap['gap_id'] for gap in one_way] == ['gap-a-specific', 'gap-broad']
    assert one_way == other_way
    # And the caller sees both, so an overlap is visible rather than resolved
    # out of sight.
    assert len(one_way) == 2


# -- that it stays shared ---------------------------------------------------


def test_both_projections_take_eligibility_from_the_core():
    assert cpr_project.LIVE_CLAIM_STATES is claims.LIVE_CLAIM_STATES
    assert gt_project.LIVE_CLAIM_STATES is claims.LIVE_CLAIM_STATES


@pytest.mark.parametrize(
    'module',
    ['artifacts/cpr/project.py', 'artifacts/geotizer/project.py'],
)
def test_neither_projection_redefines_the_shared_rule(module):
    """A local re-definition would shadow the import and drift in silence.

    This is the failure the extraction exists to prevent, so it is checked
    structurally rather than trusted: the two projections previously carried
    verbatim copies of these, and nothing would have complained when one
    changed.
    """
    tree = ast.parse((SERVICES / module).read_text(encoding='utf-8'))
    defined = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    } | {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert 'LIVE_CLAIM_STATES' not in defined
    assert '_granted_source_ids' not in defined
    assert '_conflicts_over' not in defined


def test_the_evaluator_s_copy_is_the_core_s_value():
    """`rag_ab` imports nothing on purpose -- a measurement that moves with the
    thing it measures is not a measurement. The copy is allowed; drifting from
    the definition it claims to mirror is not.
    """
    assert rag_ab.LIVE_CLAIM_STATES == claims.LIVE_CLAIM_STATES
    # Separate objects: the point is that it is a copy, checked, not an import.
    assert rag_ab.LIVE_CLAIM_STATES is not claims.LIVE_CLAIM_STATES


def test_the_evaluator_still_imports_nothing_from_the_code_it_measures():
    tree = ast.parse((SERVICES / 'evaluation/rag_ab.py').read_text(encoding='utf-8'))
    internal = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or '').startswith('open_webui'))
    ]

    assert internal == []


# -- the two artefacts must not disagree about a reviewer's ruling ----------


def test_both_artefacts_require_every_overlapping_gap_to_be_approved():
    """One approved gap overlapping an unreviewed one is not an approval.

    The CPR has always required all of them (`_is_expert_approved`). GeoTeaser
    checked only the first gap on the row, which was equivalent while `gap_ids`
    held one entry -- and stopped being equivalent the moment overlapping gaps
    were all recorded. The two artefacts would then have disagreed about
    whether a Domain Reviewer had signed the cell off.
    """
    import json as _json
    from pathlib import Path as _Path

    from open_webui.services.artifacts.cpr import coverage as cpr_coverage

    data = _Path(__file__).resolve().parent / 'data/lekyn-dossier.example.json'
    dossier = _json.loads(data.read_text(encoding='utf-8'))

    # The gap that actually reaches a GeoTeaser cell and is approved there.
    baseline = gt_project.build_projection(dossier)
    approved_row = next(
        row for row in baseline['fields'] if row.get('expert_approved_not_applicable') is True
    )
    approved_gap = approved_row['gap_ids'][0]
    twin = next(gap for gap in dossier['gaps'] if gap['gap_id'] == approved_gap)
    dossier['gaps'].append({**twin, 'gap_id': 'gap-zz-unreviewed'})

    geotizer = gt_project.build_projection(dossier)
    cpr = cpr_project.build_projection(dossier)
    approved = cpr_coverage._expert_approved_gaps(dossier)

    contested = [
        row for row in geotizer['fields'] if 'gap-zz-unreviewed' in (row.get('gap_ids') or ())
    ]
    assert contested, 'the twin gap reaches at least one GeoTeaser field'
    for row in contested:
        assert row['expert_approved_not_applicable'] is False, row['field_key']

    for row in cpr['coverage']:
        if 'gap-zz-unreviewed' in (row.get('gap_ids') or ()):
            assert cpr_coverage._is_expert_approved(row, approved) is False


# -- which entity a cell is allowed to draw on ------------------------------


def test_every_answered_cell_draws_on_the_object_or_a_declared_relation():
    """`subject_entity_id` is required on every claim and gap, and neither
    projection reads it.

    Today that is harmless and not luck: the two cells drawing on another entity
    are `CPR-1.5.1` (legal aspects, answered from `ent-licence`, a child of the
    object) and `CPR-1.3.1` (adjacent objects, answered from `ent-analogue`,
    which is the point of the requirement). Both are right.

    Nothing enforces it. A dossier holding two objects -- ordinary once customer
    documents arrive -- could answer object A's cell from a claim about object
    B, and no check in any of the three repositories would notice. The rule that
    would decide it (which entity types may answer which requirement) is a
    contract nobody has written, so this pins the current draw instead: a new
    cross-entity answer fails here and has to be justified rather than absorbed.
    """
    import json as _json
    from pathlib import Path as _Path

    data = _Path(__file__).resolve().parent / 'data/lekyn-dossier.example.json'
    dossier = _json.loads(data.read_text(encoding='utf-8'))
    subject = {claim['claim_id']: claim['subject_entity_id'] for claim in dossier['claims']}
    parent = {e['entity_id']: e.get('parent_entity_id') for e in dossier['entities']}

    def draws(rows, key):
        found = {}
        for row in rows:
            others = {
                subject[cid] for cid in row.get('supporting_claim_ids') or [] if cid in subject
            } - {'ent-object'}
            if others:
                found[row[key]] = sorted(others)
        return found

    geotizer = draws(gt_project.build_projection(dossier)['fields'], 'field_key')
    cpr = draws(cpr_project.build_projection(dossier)['coverage'], 'requirement_id')

    assert geotizer == {'geotizer_object.v1.r008.a01': ['ent-licence']}
    assert cpr == {
        'CPR-1.3.1': ['ent-analogue'],
        'CPR-1.5.1': ['ent-licence'],
    }
    # The licence draw is a parent/child relation; the analogue draw is not, and
    # is only acceptable because that requirement is *about* adjacent objects.
    assert parent['ent-licence'] == 'ent-object'
    assert parent['ent-analogue'] != 'ent-object'


# -- corroboration is a claim about agreement -------------------------------


def test_two_claims_that_disagree_are_not_corroborated():
    """`corroborated` is the strongest evidential statement either artefact
    makes -- the CPR renders it as confirmation by two sources.

    It rested entirely on `resolution_outcome`, which is the dossier author's
    account of how the claims were resolved, never a check that they say the
    same thing. Two licence numbers that differ were reported as corroborated
    by both artefacts.
    """
    import copy as _copy
    import json as _json
    from pathlib import Path as _Path

    data = _Path(__file__).resolve().parent / 'data/lekyn-dossier.example.json'
    dossier = _json.loads(data.read_text(encoding='utf-8'))
    baseline = next(
        row for row in gt_project.build_projection(dossier)['fields']
        if row['field_key'] == 'geotizer_object.v1.r008.a01'
    )
    assert baseline['state'] == 'corroborated', 'the agreeing pair is still corroborated'

    disagreeing = _copy.deepcopy(dossier)
    for claim in disagreeing['claims']:
        if claim['claim_id'] == 'clm-licence-number-doc':
            claim['value'] = 'СЫК 11111 XX'

    row = next(
        r for r in gt_project.build_projection(disagreeing)['fields']
        if r['field_key'] == 'geotizer_object.v1.r008.a01'
    )
    cpr_row = next(
        r for r in cpr_project.build_projection(disagreeing)['coverage']
        if r['requirement_id'] == 'CPR-1.5.1'
    )

    assert row['state'] == 'supported'
    assert cpr_row['state'] == 'supported'


def test_a_unit_difference_is_a_disagreement_too():
    """12 t and 12 kg are not two sources confirming each other."""
    same = [{'value': 12, 'unit': 'т'}, {'value': 12, 'unit': 'т'}]
    different_unit = [{'value': 12, 'unit': 'т'}, {'value': 12, 'unit': 'кг'}]

    assert claims.claims_agree_on_a_value(same)
    assert not claims.claims_agree_on_a_value(different_unit)


# -- reviewers who disagree about an absence --------------------------------


def test_overlapping_gaps_that_disagree_go_to_an_expert():
    """Taking `gaps[0]` meant the alphabetically-first gap id decided.

    A reviewer's `blocked_expert` ruling lost to another reviewer's
    `not_applicable` on nothing but a string comparison -- verified before the
    fix: a `blocked_expert` gap added over `mining_method` left the cell
    `not_applicable`, because `gap-mining-method` sorts before `gap-zz-blocked`.
    Which reviewer applies to this cell is itself an expert question.
    """
    approved = {'gap_id': 'gap-a', 'if_not_why_not': {'state': 'not_applicable'}}
    blocked = {'gap_id': 'gap-z', 'if_not_why_not': {'state': 'blocked_expert'}}

    assert claims.resolve_gap_state([approved]) == ('not_applicable', False)
    assert claims.resolve_gap_state([approved, blocked]) == ('blocked_expert', True)
    # Order may not matter, in either direction.
    assert claims.resolve_gap_state([blocked, approved]) == ('blocked_expert', True)


def test_a_disagreeing_pair_of_gaps_reaches_the_cell_as_an_expert_decision():
    import copy as _copy
    import json as _json
    from pathlib import Path as _Path

    data = _Path(__file__).resolve().parent / 'data/lekyn-dossier.example.json'
    dossier = _json.loads(data.read_text(encoding='utf-8'))
    twin = _copy.deepcopy(next(g for g in dossier['gaps'] if g['gap_id'] == 'gap-mining-method'))
    twin['gap_id'] = 'gap-zz-blocked'
    twin['if_not_why_not'] = {**twin['if_not_why_not'], 'state': 'blocked_expert'}
    dossier['gaps'].append(twin)

    row = next(
        r for r in gt_project.build_projection(dossier)['fields']
        if r['field_key'] == 'geotizer_object.v1.r064.a01'
    )

    assert row['state'] == 'blocked_expert'
    assert row['gap_ids'] == ['gap-mining-method', 'gap-zz-blocked']
    assert row['if_not_why_not']['reason_kind'] == 'expert_decision_required'
    assert 'gap-zz-blocked' in row['if_not_why_not']['reason']
