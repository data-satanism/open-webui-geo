"""The precondition both projections share, derived the way it was found.

`build_projection` read the frozen dossier directly and checked nothing. Removing
a single field from the reference dossier either raised a bare `KeyError` out of
the middle of a walk or -- worse -- returned a complete, well-formed document
computed from less evidence than it was given. Drop `state` from every claim and
both artefacts report a project about which nothing is known.

No count is given here on purpose. The first version said "twenty-one fields ...
six ... fifteen", which was the tally over three of the dossier's twelve array
members, and it stayed in this header after the sweep below grew to cover all of
them. `_removals` is the answer to "how many", and it recomputes.

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
import hashlib
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
    ITEM_REQUIRED,
    LIST_MEMBERS,
    NESTED_REQUIRED,
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


@pytest.fixture(scope='module')
def baseline(dossier):
    """Both projections of the good dossier, computed once.

    Module-scoped because the sweep below is now ~90 parametrised cases over
    every array member, and rebuilding a 351-field projection and a 74-requirement
    one per case took the file from under a second to over two minutes.
    """
    return _project_all(dossier)


def _project_all(document):
    """Both projections, as one comparable value. Raises what they raise.

    A digest, not the JSON. Comparing the strings directly is the same test and
    costs six minutes on a failure: pytest's assertion rewriting builds a
    character diff of the two projections, which serialise to about 264,000
    characters together, and a single failing case in this sweep took 385 of the
    file's 386 seconds. (An earlier version of this note said "four-kilobyte",
    which was a guess at the size and wrong by two orders of magnitude -- the
    number is the reason the diff is slow, so it is worth being right about.)
    Every passing case is milliseconds. The label in the assertion message says
    which field changed, which is the part a reader needs; the diff of a
    351-field projection is not.
    """
    payload = json.dumps(
        {name: build(document) for name, build in PROJECTIONS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# -- the good dossier ------------------------------------------------------


def test_the_reference_dossier_is_projectable(dossier):
    """Stated first: every refusal below is worthless if the check refuses
    everything."""
    assert projection_preconditions(dossier) == ()
    require_projectable(dossier)


# -- completeness, by mutation ---------------------------------------------


def _removals(dossier):
    """Every single-field removal, as (label, mutation).

    Over *every* array member, not a chosen few. The first version enumerated
    the top-level keys plus the keys of `claims[0]`, `gaps[0]` and
    `conflicts[0]`, and nothing else -- so the eight remaining members were
    dropped whole and never malformed from the inside. That is precisely the
    hole that let `estimate['estimate_id']` and `_index()`'s `item[key]` keep
    escaping as bare `KeyError`s while this file reported a clean sweep. A test
    that claims to derive a requirement set by mutation has to mutate
    everything the set covers.
    """
    cases = [(f'dossier.{name}', lambda d, n=name: d.pop(n, None)) for name in sorted(dossier)]
    for member in sorted(LIST_MEMBERS):
        items = dossier.get(member) or []
        if not items:
            continue
        for name in sorted(items[0]):
            cases.append(
                (
                    f'{member}[].{name}',
                    lambda d, m=member, n=name: [item.pop(n, None) for item in d[m]],
                )
            )
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
    'claims[].estimate_id': 'a claim need not cite an estimate',
    'gaps[].missing_predicates': 'a gap need not enumerate the predicates it is missing',
    'gaps[].required_expert_action_id': 'a gap need not require an expert action',
    'figures[].supports_claim_ids': (
        'a figure need not support a claim; the CPR lists only figures a matched '
        'claim points at, so a figure supporting nothing is correctly absent'
    ),
}


# Removals that change nothing at all. Listed because the first version of this
# file put them in `OPTIONAL_BUT_LOAD_BEARING`, whose comment says "the fields
# whose removal changes a projection" -- and neither of them does. A dict that
# quietly accepts entries which do not meet its own stated criterion cannot be
# read as a list of decisions.
CHANGES_NOTHING = (
    'dossier.seeded_from_dossier_run_id',
    'dossier.state_transitions',
)


@pytest.mark.parametrize('label,mutate', _removals(json.loads(DOSSIER_FILE.read_text(encoding='utf-8'))), ids=lambda p: p if isinstance(p, str) else '')
def test_every_field_the_projections_depend_on_is_refused_or_optional(dossier, baseline, label, mutate):
    """The check that derives the requirement lists instead of trusting them.

    For each single-field removal: either the precondition refuses the dossier,
    or both projections must produce exactly what they produced before. A field
    that quietly changes the answer and is not named is the silent failure this
    whole module exists to stop, and `OPTIONAL_BUT_LOAD_BEARING` is where the
    legitimate cases are argued one by one rather than waved through.
    """
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

    if label in CHANGES_NOTHING:
        assert _project_all(mutated) == baseline, f'{label} is listed as inert and is not'
        return

    assert label in OPTIONAL_BUT_LOAD_BEARING or _project_all(mutated) == baseline, (
        f'{label} is not required by the precondition, is not listed as '
        f'legitimately optional, and changes what the projections return'
    )


def test_nothing_in_the_optional_list_is_also_required():
    """Otherwise an entry could be added to both and mean nothing."""
    named = {f'dossier.{n}' for n in DOSSIER_REQUIRED}
    for member, required in ITEM_REQUIRED.items():
        named |= {f'{member}[].{n}' for n in required}

    assert named.isdisjoint(OPTIONAL_BUT_LOAD_BEARING)
    assert named.isdisjoint(CHANGES_NOTHING)


def test_every_entry_in_the_optional_list_really_does_change_something(dossier, baseline):
    """The other direction. An entry that changes nothing belongs in
    `CHANGES_NOTHING`, and leaving it here makes the dict's own comment false."""
    inert = []
    checked = []
    for label, mutate in _removals(dossier):
        if label not in OPTIONAL_BUT_LOAD_BEARING:
            continue
        checked.append(label)
        mutated = copy.deepcopy(dossier)
        mutate(mutated)
        if _project_all(mutated) == baseline:
            inert.append(label)

    # The loop body runs only for labels that appear in both the sweep and the
    # dict, so a renamed label would empty it and the test would pass having
    # verified nothing. Every entry must have been reached.
    assert sorted(checked) == sorted(OPTIONAL_BUT_LOAD_BEARING)
    assert inert == []


# Array members the reference dossier does not populate, so the mutation sweep
# cannot reach their items. Their requirement lists rest on the schema
# cross-check alone -- which is skipped in single-checkout CI, so in that
# configuration nothing at all derives them. Named, because "the sweep covers
# every member" would otherwise be false in a way no failure would show.
NOT_IN_THE_REFERENCE_DOSSIER = ('state_transitions',)


def test_the_mutation_sweep_reaches_every_array_member_the_dossier_has(dossier):
    """Guards the sweep itself. It silently skips a member whose array is empty
    in the reference dossier, and a member that stopped being exercised would
    take its requirement list out of the derivation without failing anything."""
    covered = {label.split('[')[0] for label, _ in _removals(dossier) if '[].' in label}
    absent = {m for m in LIST_MEMBERS if not (dossier.get(m) or [])}

    assert covered == set(LIST_MEMBERS) - absent
    # The escape hatch must stay honest in both directions: a member listed as
    # absent that is in fact present would silently excuse itself.
    assert absent == set(NOT_IN_THE_REFERENCE_DOSSIER)


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

    # Every member, resolved through the schema rather than named here. The
    # first version of this check asserted four lists -- the top level plus
    # claim, gap and conflict -- while `ITEM_REQUIRED` had grown to eleven, so
    # forty of the fifty-seven field names actually driving refusal were
    # compared against nothing. That is the half of the guarantee that stops
    # this module becoming a second, stricter schema, and it was the half that
    # silently stopped covering most of it.
    for member, required in sorted(ITEM_REQUIRED.items()):
        ref = schema['properties'][member]['items']['$ref'].rsplit('/', 1)[-1]
        assert set(required) == set(defs[ref]['required']), member

    for member, nested in sorted(NESTED_REQUIRED.items()):
        ref = schema['properties'][member]['items']['$ref'].rsplit('/', 1)[-1]
        for name, fields in sorted(nested.items()):
            nested_ref = defs[ref]['properties'][name]['$ref'].rsplit('/', 1)[-1]
            assert set(fields) == set(defs[nested_ref]['required']), f'{member}.{name}'

    assert set(PROJECT_SCOPE_REQUIRED) == set(defs['projectScope']['required'])



@pytest.mark.skipif(not _gmm_present(), reason='no GMM checkout beside this one')
def test_every_list_member_is_an_array_in_the_contract():
    schema = json.loads(GMM_SCHEMA.read_text(encoding='utf-8'))

    for name in LIST_MEMBERS:
        assert schema['properties'][name]['type'] == 'array', name
