"""Tests that the dossier projection preconditions name every field the projections depend on, by single-field removal,
and only fields the GMM dossier schema requires.
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
    DOSSIER_REQUIRED,
    ITEM_REQUIRED,
    LIST_MEMBERS,
    NESTED_REQUIRED,
    PROJECT_SCOPE_REQUIRED,
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
    """Both projections of the good dossier, computed once per module."""
    return _project_all(dossier)


def _project_all(document):
    """Both projections, as one SHA-256 digest of their sorted JSON. Raises what they raise."""
    payload = json.dumps(
        {name: build(document) for name, build in PROJECTIONS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def test_the_reference_dossier_is_projectable(dossier):
    """The reference dossier passes the preconditions."""
    assert projection_preconditions(dossier) == ()
    require_projectable(dossier)


def _removals(dossier):
    """Every single-field removal over the top level and every populated array member, as (label, mutation)."""
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


OPTIONAL_BUT_LOAD_BEARING = {
    'claims[].estimate_id': 'a claim need not cite an estimate',
    'gaps[].missing_predicates': 'a gap need not enumerate the predicates it is missing',
    'gaps[].required_expert_action_id': 'a gap need not require an expert action',
    'figures[].supports_claim_ids': (
        'a figure need not support a claim; the CPR lists only figures a matched '
        'claim points at, so a figure supporting nothing is correctly absent'
    ),
}


CHANGES_NOTHING = (
    'dossier.seeded_from_dossier_run_id',
    'dossier.state_transitions',
)


@pytest.mark.parametrize('label,mutate', _removals(json.loads(DOSSIER_FILE.read_text(encoding='utf-8'))), ids=lambda p: p if isinstance(p, str) else '')
def test_every_field_the_projections_depend_on_is_refused_or_optional(dossier, baseline, label, mutate):
    """Each single-field removal is refused by both projections, or changes nothing, or is listed in
    `OPTIONAL_BUT_LOAD_BEARING`.
    """
    mutated = copy.deepcopy(dossier)
    mutate(mutated)

    reasons = projection_preconditions(mutated)
    if reasons:
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
    """No field in `OPTIONAL_BUT_LOAD_BEARING` or `CHANGES_NOTHING` is also required."""
    named = {f'dossier.{n}' for n in DOSSIER_REQUIRED}
    for member, required in ITEM_REQUIRED.items():
        named |= {f'{member}[].{n}' for n in required}

    assert named.isdisjoint(OPTIONAL_BUT_LOAD_BEARING)
    assert named.isdisjoint(CHANGES_NOTHING)


def test_every_entry_in_the_optional_list_really_does_change_something(dossier, baseline):
    """Every `OPTIONAL_BUT_LOAD_BEARING` removal is reached by the sweep and changes a projection."""
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

    assert sorted(checked) == sorted(OPTIONAL_BUT_LOAD_BEARING)
    assert inert == []


NOT_IN_THE_REFERENCE_DOSSIER = ('state_transitions',)


def test_the_mutation_sweep_reaches_every_array_member_the_dossier_has(dossier):
    """The sweep covers every populated array member, and the unpopulated ones are exactly
    `NOT_IN_THE_REFERENCE_DOSSIER`.
    """
    covered = {label.split('[')[0] for label, _ in _removals(dossier) if '[].' in label}
    absent = {m for m in LIST_MEMBERS if not (dossier.get(m) or [])}

    assert covered == set(LIST_MEMBERS) - absent
    assert absent == set(NOT_IN_THE_REFERENCE_DOSSIER)


def test_no_single_field_removal_escapes_as_a_keyerror(dossier):
    """No single-field removal makes a projection raise anything but `DossierNotProjectable`."""
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
    """A claim missing `claim_id` is reported by its index."""
    broken = copy.deepcopy(dossier)
    broken['claims'][2].pop('claim_id')

    reasons = projection_preconditions(broken)

    assert reasons == ('dossier.claims[2].claim_id is required',)


def test_a_member_of_the_wrong_type_is_refused_rather_than_walked(dossier):
    """A list member of the wrong type is refused by the preconditions and by both projections."""
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


def _gmm_present() -> bool:
    return GMM_SCHEMA.is_file()


@pytest.mark.skipif(not _gmm_present(), reason=f'no GMM checkout beside this one ({GMM_SCHEMA})')
def test_every_required_field_is_required_by_the_contract_that_owns_it():
    """Every requirement list equals the `required` list of its definition in the GMM dossier schema; skipped without a
    GMM checkout beside this repository.
    """
    schema = json.loads(GMM_SCHEMA.read_text(encoding='utf-8'))
    defs = schema['$defs']

    assert set(DOSSIER_REQUIRED) == set(schema['required'])

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
