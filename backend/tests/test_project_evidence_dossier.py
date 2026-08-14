"""The precondition both projections share, derived the way it was found.

`build_projection` read the frozen dossier directly and checked nothing. Twenty-one
fields of the reference dossier could be removed; six of them raised a bare
`KeyError` out of the middle of a walk, and the other fifteen were worse -- the
projection returned a complete, well-formed document computed from less evidence
than it was given. Drop `state` from every claim and both artefacts report a
project about which nothing is known.

The tests here are mostly not about the good dossier. They are about the shape
of that failure, and there are two halves to holding it closed:

  the requirement lists must be *complete* -- every field whose removal crashes
  a projection or changes its answer has to be named, and that is checked by
  removing them one at a time rather than by reading the code;

  and they must not be *invented* -- every field named must be `required` in
  `GMM/contracts/evidence/project-evidence-dossier.schema.json`, which owns the
  contract. The first half alone would let this module grow into a second,
  stricter schema that refuses dossiers GMM considers valid.

The second half needs a `GMM` checkout beside this one and skips without it, so
the first half is written to stand on its own: it runs everywhere, and it is the
one that would catch a projection that started reading a new field.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.cpr import project as cpr_project  # noqa: E402
from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402
from open_webui.services.project_evidence.dossier import (  # noqa: E402
    CLAIM_REQUIRED,
    CONFLICT_REQUIRED,
    DOSSIER_REQUIRED,
    GAP_REQUIRED,
    IF_NOT_WHY_NOT_REQUIRED,
    LIST_MEMBERS,
    PROJECT_SCOPE_REQUIRED,
    VALUE_ORIGIN_REQUIRED,
    DossierNotProjectable,
    projection_preconditions,
    require_projectable,
)

DOSSIER_FILE = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
GMM_SCHEMA = (
    REPO_ROOT.parent / 'GMM/contracts/evidence/project-evidence-dossier.schema.json'
)

PROJECTIONS = (('geoteaser', gt_project.build_projection), ('cpr', cpr_project.build_projection))


@pytest.fixture(scope='module')
def dossier():
    return json.loads(DOSSIER_FILE.read_text(encoding='utf-8'))


def _project_all(document):
    """Both projections, as one comparable value. Raises what they raise."""
    return json.dumps(
        {name: build(document) for name, build in PROJECTIONS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


# -- the good dossier ------------------------------------------------------


def test_the_reference_dossier_is_projectable(dossier):
    """Stated first: every refusal below is worthless if the check refuses
    everything."""
    assert projection_preconditions(dossier) == ()
    require_projectable(dossier)


# -- completeness, by mutation ---------------------------------------------


def _removals(dossier):
    """Every single-field removal, as (label, mutation)."""
    cases = [(f'dossier.{name}', lambda d, n=name: d.pop(n, None)) for name in sorted(dossier)]
    cases += [
        (f'claim.{name}', lambda d, n=name: [c.pop(n, None) for c in d['claims']])
        for name in sorted(dossier['claims'][0])
    ]
    cases += [
        (f'gap.{name}', lambda d, n=name: [g.pop(n, None) for g in d['gaps']])
        for name in sorted(dossier['gaps'][0])
    ]
    cases += [
        (f'conflict.{name}', lambda d, n=name: [c.pop(n, None) for c in d['conflicts']])
        for name in sorted(dossier['conflicts'][0])
    ]
    cases += [
        ('claim.value_origin.kind', lambda d: [c['value_origin'].pop('kind', None) for c in d['claims']]),
        ('gap.if_not_why_not.reason', lambda d: [g['if_not_why_not'].pop('reason', None) for g in d['gaps']]),
        ('gap.if_not_why_not.reason_kind', lambda d: [g['if_not_why_not'].pop('reason_kind', None) for g in d['gaps']]),
        ('gap.if_not_why_not.state', lambda d: [g['if_not_why_not'].pop('state', None) for g in d['gaps']]),
        ('project_scope.acl_decision', lambda d: d['project_scope'].pop('acl_decision', None)),
        ('project_scope.lifecycle_stage', lambda d: d['project_scope'].pop('lifecycle_stage', None)),
        ('project_scope.project_id', lambda d: d['project_scope'].pop('project_id', None)),
    ]
    return cases


# The fields whose removal changes a projection and which are nonetheless
# *optional* in the contract. Not a shortfall in the check -- a claim with no
# estimate is a claim with no estimate, and projecting it differently is the
# right answer. Named rather than counted, so a new entry is a decision.
OPTIONAL_BUT_LOAD_BEARING = {
    'claim.estimate_id': 'a claim need not cite an estimate',
    'gap.missing_predicates': 'a gap need not enumerate the predicates it is missing',
    'gap.required_expert_action_id': 'a gap need not require an expert action',
    'dossier.seeded_from_dossier_run_id': 'only a re-freeze has a seed',
    'dossier.state_transitions': 'a dossier frozen once has no transitions',
}


@pytest.mark.parametrize('label,mutate', _removals(json.loads(DOSSIER_FILE.read_text(encoding='utf-8'))), ids=lambda p: p if isinstance(p, str) else '')
def test_every_field_the_projections_depend_on_is_refused_or_optional(dossier, label, mutate):
    """The check that derives the requirement lists instead of trusting them.

    For each single-field removal: either the precondition refuses the dossier,
    or both projections must produce exactly what they produced before. A field
    that quietly changes the answer and is not named is the silent failure this
    whole module exists to stop, and `OPTIONAL_BUT_LOAD_BEARING` is where the
    legitimate cases are argued one by one rather than waved through.
    """
    baseline = _project_all(dossier)
    mutated = copy.deepcopy(dossier)
    mutate(mutated)

    reasons = projection_preconditions(mutated)
    if reasons:
        # Refused. It must also be refused *before* anything is read, in both
        # artefacts -- a precondition only one of them applies is not one.
        for _, build in PROJECTIONS:
            with pytest.raises(DossierNotProjectable):
                build(copy.deepcopy(mutated))
        return

    assert label in OPTIONAL_BUT_LOAD_BEARING or _project_all(mutated) == baseline, (
        f'{label} is not required by the precondition, is not listed as '
        f'legitimately optional, and changes what the projections return'
    )


def test_nothing_in_the_optional_list_is_also_required():
    """Otherwise an entry could be added to both and mean nothing."""
    named = (
        {f'dossier.{n}' for n in DOSSIER_REQUIRED}
        | {f'claim.{n}' for n in CLAIM_REQUIRED}
        | {f'gap.{n}' for n in GAP_REQUIRED}
        | {f'conflict.{n}' for n in CONFLICT_REQUIRED}
    )

    assert named.isdisjoint(OPTIONAL_BUT_LOAD_BEARING)


def test_no_single_field_removal_escapes_as_a_keyerror(dossier):
    """The finding itself, stated over the whole surface rather than per field.

    `KeyError: 'value_origin'` out of a coverage walk tells an operator nothing
    about which export is broken or how. Whatever comes out now must be the
    named refusal.
    """
    escapes = []
    for label, mutate in _removals(dossier):
        mutated = copy.deepcopy(dossier)
        mutate(mutated)
        for name, build in PROJECTIONS:
            try:
                build(copy.deepcopy(mutated))
            except DossierNotProjectable:
                pass
            except Exception as exc:  # noqa: BLE001
                escapes.append(f'{label} -> {name}: {type(exc).__name__}: {exc}')

    assert escapes == []


# -- the refusal reports everything, not the first thing -------------------


def test_a_refusal_names_every_problem(dossier):
    broken = copy.deepcopy(dossier)
    broken.pop('project_scope')
    for claim in broken['claims']:
        claim.pop('value_origin')

    reasons = projection_preconditions(broken)

    assert 'dossier.project_scope is required' in reasons
    assert sum(1 for r in reasons if r.endswith('.value_origin is required')) == len(broken['claims'])
    assert len(reasons) == 1 + len(broken['claims'])


def test_a_claim_that_cannot_be_named_is_reported_by_position(dossier):
    """A claim missing `claim_id` is the one most likely to be missing more."""
    broken = copy.deepcopy(dossier)
    broken['claims'][2].pop('claim_id')

    reasons = projection_preconditions(broken)

    assert reasons == ('dossier.claims[2].claim_id is required',)


def test_a_member_of_the_wrong_type_is_refused_rather_than_walked(dossier):
    """`claims` as a mapping passes every `in` check and then fails far away as
    `TypeError: string indices must be integers` -- which is exactly how GMM's
    validator failed on the same input."""
    broken = copy.deepcopy(dossier)
    broken['claims'] = {'clm-1': {}}

    reasons = projection_preconditions(broken)

    assert reasons == ('dossier.claims must be an array, got dict',)
    for _, build in PROJECTIONS:
        with pytest.raises(DossierNotProjectable):
            build(copy.deepcopy(broken))


def test_something_that_is_not_a_dossier_is_refused_without_a_traceback():
    for value in (None, [], 'a dossier', 7):
        reasons = projection_preconditions(value)
        assert len(reasons) == 1
        assert reasons[0].startswith('dossier must be an object')


def test_the_error_carries_the_reasons_as_data_not_only_as_text(dossier):
    broken = copy.deepcopy(dossier)
    broken.pop('sources')
    broken.pop('gaps')

    with pytest.raises(DossierNotProjectable) as excinfo:
        require_projectable(broken)

    assert set(excinfo.value.reasons) == {
        'dossier.sources is required',
        'dossier.gaps is required',
    }
    assert '2 problems' in str(excinfo.value)


# -- not invented: the lists are the contract's ----------------------------


def _gmm_present() -> bool:
    return GMM_SCHEMA.is_file()


@pytest.mark.skipif(not _gmm_present(), reason=f'no GMM checkout beside this one ({GMM_SCHEMA})')
def test_every_required_field_is_required_by_the_contract_that_owns_it():
    """The half that stops this becoming a second, stricter schema.

    Skipped where `GMM` is not checked out beside this repository, which is the
    single-checkout CI case. Said plainly rather than left to be noticed: in
    that configuration nothing here compares the lists to the contract, and the
    mutation tests above are the whole guarantee.
    """
    schema = json.loads(GMM_SCHEMA.read_text(encoding='utf-8'))
    defs = schema['$defs']

    assert set(DOSSIER_REQUIRED) == set(schema['required'])
    assert set(CLAIM_REQUIRED) == set(defs['evidenceClaim']['required'])
    assert set(GAP_REQUIRED) == set(defs['evidenceGap']['required'])
    assert set(CONFLICT_REQUIRED) == set(defs['conflict']['required'])
    assert set(VALUE_ORIGIN_REQUIRED) == set(defs['valueOrigin']['required'])
    assert set(IF_NOT_WHY_NOT_REQUIRED) == set(defs['ifNotWhyNot']['required'])
    assert set(PROJECT_SCOPE_REQUIRED) == set(defs['projectScope']['required'])


@pytest.mark.skipif(not _gmm_present(), reason='no GMM checkout beside this one')
def test_every_list_member_is_an_array_in_the_contract():
    schema = json.loads(GMM_SCHEMA.read_text(encoding='utf-8'))

    for name in LIST_MEMBERS:
        assert schema['properties'][name]['type'] == 'array', name
