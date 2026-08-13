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
