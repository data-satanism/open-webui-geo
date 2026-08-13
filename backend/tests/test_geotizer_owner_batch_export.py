"""The handoff from a dossier to the GIS state machine, and what it may not do.

`scripts/export_geotizer_owner_batches.py` turns a frozen Project Evidence
Dossier into the owner envelope `gis_service` accepts. It is the seam between
the two builds, so the rules that hold either side of it have to hold across
it:

  a filled cell carries the claim ids it came from -- otherwise the workbook
  is a set of numbers with no route back to the evidence the CPR reads;

  an absent cell carries the dossier's own `if_not_why_not` reason -- §9
  forbids a bare `not_found`, and a blank reason turns an answer into a
  placeholder;

  a conflicted fact is an absence, not a value. Writing one side of an
  unresolved conflict into a cell is exactly the failure the estimate-identity
  work exists to prevent, and it would be invisible in the workbook.

The exporter is value-carrying and the projection is not; that split is
deliberate and `test_the_projection_itself_stays_value_free` pins it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer import project as gt_project  # noqa: E402

DOSSIER = REPO_ROOT / 'backend/tests/data/lekyn-dossier.example.json'
COMMITTED = REPO_ROOT / 'backend/tests/data/lekyn-owner-batches.json'


def _exporter():
    spec = importlib.util.spec_from_file_location(
        'export_geotizer_owner_batches', REPO_ROOT / 'scripts/export_geotizer_owner_batches.py'
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def exporter():
    return _exporter()


@pytest.fixture(scope='module')
def envelope(exporter):
    return exporter.build()


@pytest.fixture(scope='module')
def dossier():
    return json.loads(DOSSIER.read_text(encoding='utf-8'))


def test_the_envelope_covers_the_whole_template(envelope):
    assert envelope['template_field_count'] == 351
    assert len(envelope['fields']) == 351
    assert envelope['totals']['fields'] == 351
    # Every field key appears once. A duplicate would overwrite a cell.
    keys = [field['field_key'] for field in envelope['fields']]
    assert len(set(keys)) == 351


def test_a_filled_cell_carries_the_claims_it_came_from(envelope):
    filled = [field for field in envelope['fields'] if field['status'] == 'filled']
    assert filled, 'the dossier fills at least one cell'
    assert envelope['totals']['filled_without_a_claim'] == 0
    for field in filled:
        assert field['claim_ids'], field['field_key']
        assert field['value'] is not None, field['field_key']


def test_an_absent_cell_carries_the_dossier_s_reason_not_a_blank(envelope):
    absent = [field for field in envelope['fields'] if field['status'] != 'filled']
    assert envelope['totals']['absences_without_a_reason'] == 0
    for field in absent:
        assert field['reason'].strip(), field['field_key']
        assert field['value'] is None, field['field_key']


def test_the_three_absence_states_stay_three(envelope, exporter):
    """`missing`, `not_applicable` and `blocked_expert` are different answers.

    The state machine has a distinct status for each, so collapsing them to
    `not_found` would throw away a decision rather than satisfy a constraint.
    """
    assert set(exporter.ABSENCE_STATUS.values()) == {
        'not_found',
        'not_applicable',
        'requires_expert_review',
        'conflicted',
    }
    statuses = {field['status'] for field in envelope['fields']}
    assert statuses <= {'filled', *exporter.ABSENCE_STATUS.values()}


def test_a_reviewer_s_not_applicable_is_not_reported_as_not_found(envelope):
    """"Does not apply at this stage, and a Domain Reviewer said so" is a
    different statement about the deposit than "we looked and found nothing"."""
    not_applicable = [f for f in envelope['fields'] if f['status'] == 'not_applicable']
    assert not_applicable, 'the example dossier holds a reviewed not_applicable gap'
    for field in not_applicable:
        assert field['expert_approved_not_applicable'] is True, field['field_key']
        assert field['decided_by_role'], field['field_key']
    assert envelope['totals']['by_status']['not_applicable'] == len(not_applicable)


def test_the_frozen_dossier_is_named_so_the_workbook_can_be_traced_back(envelope, dossier):
    assert envelope['dossier_run_id'] == dossier['dossier_run_id']
    assert envelope['frozen_inputs_hash'] == dossier['frozen_inputs_hash']
    assert envelope['frozen_at'] == dossier['frozen_at']


def test_the_scope_carries_only_what_the_dossier_actually_holds(envelope, dossier):
    """The licence id is in the dossier. The polygon and its area are not, and
    the exporter may not invent them here where they would read as evidence."""
    scope = envelope['scope']
    assert scope['object_name'] == dossier['project_scope']['object_name']
    assert scope['project_id'] == dossier['project_scope']['project_id']
    assert scope['licence_id'] and scope['licence_claim_ids']
    assert 'coordinate_table' not in scope
    assert 'area' not in scope


def test_a_conflicted_estimate_never_becomes_a_value(exporter, dossier, envelope):
    """One side of an unresolved conflict written into a cell would be a fact
    the dossier never asserted, and nothing downstream could tell."""
    projection = gt_project.build_projection(dossier)
    conflicted = [row for row in projection['fields'] if row['state'] == exporter.CONFLICTED]
    if not conflicted:
        pytest.skip('no conflict in the example dossier reaches a template field')

    by_key = {field['field_key']: field for field in envelope['fields']}
    for row in conflicted:
        field = by_key[row['field_key']]
        assert field['status'] == 'conflicted', row['field_key']
        assert field['value'] is None
        assert 'конфликт' in field['reason']


def test_a_conflict_no_field_can_show_is_counted_rather_than_lost(envelope, dossier):
    """The Lekyn dossier's one conflict is on `forecast_resource_quantity`, and
    no template field carries that predicate -- the ten resource rows are each
    specific (авторские, апробированные, текущие …). So the 12 т/20 т dispute
    reaches no cell, and every row it might have touched reads `НЕ НАЙДЕНО`:
    the workbook says there is no fact where the dossier holds two that
    disagree.

    Choosing which specific row each estimate belongs to is the estimate-identity
    call the conflict itself records as unresolved (`both_reported`), so the
    exporter must not make it. Counting the conflict is what it can do.
    """
    stranded = envelope['conflicts_no_field_can_show']
    placed = {
        cid
        for row in gt_project.build_projection(dossier)['fields']
        for cid in row.get('conflict_ids') or ()
    }
    recorded = {conflict['conflict_id'] for conflict in stranded}
    every_conflict = {conflict['conflict_id'] for conflict in dossier.get('conflicts') or ()}

    # Every conflict is either shown in a cell or listed here. None is neither.
    assert recorded | placed == every_conflict
    assert not recorded & placed
    for conflict in stranded:
        assert conflict['claim_ids']
        assert conflict['why_it_cannot_be_shown'].strip()


def test_the_projection_itself_stays_value_free(dossier):
    """The projection decides which cell a fact answers; the envelope carries
    the value. If a value leaked into the projection the two builds would each
    hold half a contract."""
    projection = gt_project.build_projection(dossier)
    for row in projection['fields']:
        assert 'value' not in row, row['field_key']


def test_the_committed_envelope_is_what_the_exporter_produces_today(envelope):
    """`gis_service` renders from a copy of this file. A hand-edit here, or a
    change to the projection that nobody re-exported, would leave the two
    repositories rendering different things from the same dossier."""
    committed = json.loads(COMMITTED.read_text(encoding='utf-8'))
    assert committed == envelope
