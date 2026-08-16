"""Agreement scoring, against the Workspace Tool it was ported from.

`score_field_agreement` is the first port of the §4 merge because eleven of the
fourteen behaviours the deployed Tool has and this repository does not read its
verdict -- the divergent-field list and every confidence band. So the tests that
matter are the ones a rewrite would quietly get wrong:

  what counts as the same value, which is the whole of `normalize_value` and
  the only thing that decides `unanimous` from `divergent`;

  that one domain contradicting itself is not divergence, because divergence is
  a claim about independent readers;

  and that an empty value is not a proposal, because a contributor returning
  nothing must not make a claim look single-source when another domain answered.

The last two are asserted directly against the reference implementation in
`GMM/operations/workspace-exports/geoteaser.py`, executed here rather than read,
so "the port behaves the same" is a comparison and not an opinion.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.project_evidence.agreement import (  # noqa: E402
    ClaimAgreement,
    divergent_claim_keys,
    normalize_value,
    score_claim_agreement,
)

EXPORT = REPO_ROOT.parent / 'GMM/operations/workspace-exports/geoteaser.py'


def _evidence(*items):
    return [
        {'source_domain': domain, 'field_proposals': list(proposals)}
        for domain, proposals in items
    ]


def _proposal(field_key, value):
    return {'field_key': field_key, 'value': value}


# The vocabulary the projection supplies. It lives in the test, not in the
# module: `project_evidence/` may not name the GeoTeaser cell.
VOCABULARY = {'claim_key_field': 'field_key', 'proposals_field': 'field_proposals'}


# -- what counts as the same value -------------------------------------------


@pytest.mark.parametrize(
    ('left', 'right'),
    [
        (1000, '1000'),
        (1000.0, '1000,0'),
        ('Да', 'да'),
        ('a  b', 'a b'),
        (0.1 + 0.2, 0.3),
    ],
)
def test_two_spellings_of_one_value_agree(left, right):
    """Numbers compare numerically and text compares casefolded, because two
    contributors reading the same document write it differently. `0.1 + 0.2`
    against `0.3` is in the list on purpose: six significant figures is what
    keeps float arithmetic from being reported as a source disagreement."""
    assert normalize_value(left) == normalize_value(right)


@pytest.mark.parametrize(
    ('left', 'right'),
    [(1000, 1001), ('да', 'нет'), ('', 'нет'), (True, 1), (None, 0), (1000, ' 1 000 ')],
)
def test_two_different_values_do_not_agree(left, right):
    """The other direction, which a looser normaliser would fail. `True` and
    `1` are different: a boolean flag and a count are not the same claim.

    The last pair is a limitation, carried over deliberately. A space is the
    Russian thousands separator, and `1 000` does not parse as a float, so it
    falls back to text and reads as a disagreement with `1000`. Two
    contributors quoting the same figure from the same document in different
    conventions therefore produce a divergent claim. That is what the deployed
    Tool does and the port matches it; widening the normaliser is a change to
    what counts as agreement and belongs with the domain reviewer, not smuggled
    in under a port.
    """
    assert normalize_value(left) != normalize_value(right)


def test_nothing_normalises_to_nothing():
    assert normalize_value(None) == ''
    assert normalize_value('   ') == ''


# -- the verdicts -------------------------------------------------------------


def test_two_domains_that_agree_are_unanimous():
    scored = score_claim_agreement(
        _evidence(('kb', [_proposal('r001.a01', '1000')]), ('gis', [_proposal('r001.a01', 1000)])),
        **VOCABULARY,
    )

    assert scored['r001.a01'] == ClaimAgreement('r001.a01', 'unanimous', ('gis', 'kb'), ('1000',))


def test_two_domains_that_disagree_are_divergent():
    scored = score_claim_agreement(
        _evidence(('kb', [_proposal('r001.a01', '1000')]), ('web', [_proposal('r001.a01', '1200')])),
        **VOCABULARY,
    )

    assert scored['r001.a01'].verdict == 'divergent'
    assert scored['r001.a01'].values == ('1000', '1200')
    assert divergent_claim_keys(scored) == ('r001.a01',)


def test_one_domain_alone_is_single_source_not_unanimous():
    """A value nobody corroborated is not agreement. Reporting it as unanimous
    is how a card gets a confidence band it did not earn."""
    scored = score_claim_agreement(
        _evidence(('kb', [_proposal('r001.a01', '1000')])), **VOCABULARY
    )

    assert scored['r001.a01'].verdict == 'single_source'
    assert divergent_claim_keys(scored) == ()


def test_a_domain_contradicting_itself_is_not_divergence():
    """First proposal per domain wins. Divergence is a statement about
    independent readers, and one contributor listing two candidates is one
    reader being unsure -- a different thing, handled elsewhere."""
    scored = score_claim_agreement(
        _evidence(
            ('kb', [_proposal('r001.a01', '1000'), _proposal('r001.a01', '9999')]),
            ('gis', [_proposal('r001.a01', '1000')]),
        ),
        **VOCABULARY,
    )

    assert scored['r001.a01'].verdict == 'unanimous'
    assert scored['r001.a01'].values == ('1000',)


def test_an_empty_value_is_not_a_proposal():
    """A contributor that found nothing must not turn a corroborated claim into
    a single-source one, nor invent a disagreement with the empty string."""
    scored = score_claim_agreement(
        _evidence(
            ('kb', [_proposal('r001.a01', '1000')]),
            ('web', [_proposal('r001.a01', '   ')]),
            ('gis', [_proposal('r001.a01', None)]),
        ),
        **VOCABULARY,
    )

    assert scored['r001.a01'].verdict == 'single_source'
    assert scored['r001.a01'].domains == ('kb',)


def test_a_malformed_proposal_is_skipped_rather_than_crashing():
    scored = score_claim_agreement(
        _evidence(('kb', ['not a mapping', _proposal('r001.a01', '1000')])),
        **VOCABULARY,
    )

    assert set(scored) == {'r001.a01'}


def test_a_contributor_with_no_domain_is_recorded_as_unknown():
    """Not dropped. An unattributed proposal still corroborates or contradicts,
    and dropping it would silently change a verdict."""
    scored = score_claim_agreement(
        [{'field_proposals': [_proposal('r001.a01', '1000')]}]
        + _evidence(('kb', [_proposal('r001.a01', '1200')])),
        **VOCABULARY,
    )

    assert scored['r001.a01'].domains == ('kb', 'unknown')
    assert scored['r001.a01'].verdict == 'divergent'


# -- the port, against the implementation it was ported from ------------------


@pytest.fixture(scope='module')
def reference():
    """`score_field_agreement` from the deployed Tool, executed.

    The export is the reference implementation for the whole merge, so a port
    is checked against what it does rather than against what its source looks
    like. Only the two functions are lifted out: importing the module would pull
    in Open WebUI's runtime, which is the coupling the extraction removed.
    """
    if not EXPORT.is_file():
        pytest.skip(f'no Workspace export at {EXPORT}')
    import ast

    source = EXPORT.read_text(encoding='utf-8')
    tree = ast.parse(source)
    wanted = {'normalize_value', 'FieldAgreement', 'score_field_agreement'}
    kept = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.name in wanted
    ]
    assert {node.name for node in kept} == wanted, 'the export no longer defines these'
    import collections.abc
    import dataclasses

    # One dict for globals *and* locals: `score_field_agreement` resolves
    # `normalize_value` through its own `__globals__`, so splitting them leaves
    # the reference unable to call its own helper.
    namespace: dict = {
        're': re,
        'Any': object,
        'Mapping': collections.abc.Mapping,
        'Sequence': collections.abc.Sequence,
        'dataclass': dataclasses.dataclass,
    }
    exec(  # noqa: S102 - executing the attested export is the point of the test
        compile(ast.Module(body=kept, type_ignores=[]), str(EXPORT), 'exec'),
        namespace,
    )
    return namespace


CASES = [
    _evidence(('kb', [_proposal('a', '1000')]), ('gis', [_proposal('a', 1000)])),
    _evidence(('kb', [_proposal('a', '1000')]), ('web', [_proposal('a', '1200')])),
    _evidence(('kb', [_proposal('a', '1000')])),
    _evidence(('kb', [_proposal('a', '1000'), _proposal('a', '9999')]), ('gis', [_proposal('a', '1000')])),
    _evidence(('kb', [_proposal('a', '1000')]), ('web', [_proposal('a', '  ')])),
    _evidence(('kb', [_proposal('a', 'Да')]), ('web', [_proposal('a', 'да')]), ('gis', [_proposal('b', 7)])),
    [],
]


@pytest.mark.parametrize('evidence', CASES, ids=range(len(CASES)))
def test_the_port_scores_exactly_what_the_deployed_tool_scores(reference, evidence):
    """§5 parity for this definition, at the only level available without a
    contour: same inputs, same verdicts, same domains, same values."""
    theirs = reference['score_field_agreement'](evidence)
    ours = score_claim_agreement(evidence, **VOCABULARY)

    assert set(theirs) == set(ours)
    for key, expected in theirs.items():
        got = ours[key]
        assert (got.verdict, got.domains, got.values) == (
            expected.verdict,
            expected.domains,
            expected.values,
        ), key


@pytest.mark.parametrize(
    'value',
    [None, True, False, 0, 1000, 1000.0, '1000', ' 1 000,5 ', 'Да', '  ', 'текст  с   пробелами'],
)
def test_the_ported_normaliser_is_the_deployed_one(reference, value):
    assert normalize_value(value) == reference['normalize_value'](value)
