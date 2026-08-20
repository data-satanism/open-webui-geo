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

import copy
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


def _structured_stage(dossier, value):
    changed = copy.deepcopy(dossier)
    for claim in changed['claims']:
        if claim['claim_id'] == 'clm-stage':
            claim['value'] = value
    return changed


def test_a_structured_claim_fills_each_facet_with_its_own_part(exporter, dossier, tmp_path):
    """A row is one fact with several facets, and the projection deliberately
    lets a mapping-valued claim answer several of them -- that is how one
    estimate fills a resource row's six cells.

    The export used to return `claim['value']` unchanged, so all three cells of
    row 14 received the entire JSON object and each counted as answered. 62 of
    the template's 107 rows have several facets sharing one predicate, so this
    is the ordinary path once dossiers carry structured values, not a corner.
    """
    path = tmp_path / 'structured.json'
    path.write_text(
        json.dumps(
            _structured_stage(
                dossier,
                {'stage': 'поисковые работы', 'start_date': '2023-01-01', 'end_date': '2027-12-31'},
            ),
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    by_key = {f['field_key']: f for f in exporter.build(path)['fields']}

    assert by_key['geotizer_object.v1.r014.a01']['value'] == 'поисковые работы'
    assert by_key['geotizer_object.v1.r014.a02']['value'] == '2023-01-01'
    assert by_key['geotizer_object.v1.r014.a03']['value'] == '2027-12-31'
    for key in ('a01', 'a02', 'a03'):
        assert by_key[f'geotizer_object.v1.r014.{key}']['status'] == 'filled'


def test_a_mapping_that_names_no_facet_for_a_cell_leaves_it_absent(exporter, dossier, tmp_path):
    """A mapping that does not name a facet does not answer that cell.

    The projection settles this: `_answers_facet` is false, so the cell is
    `missing` and carries the projection's own reason. Pinned here because the
    export must not reach past that and fill the cell from the rest of the
    object.
    """
    path = tmp_path / 'partial.json'
    path.write_text(
        json.dumps(
            _structured_stage(dossier, {'stage': 'поисковые работы'}), ensure_ascii=False
        ),
        encoding='utf-8',
    )

    by_key = {f['field_key']: f for f in exporter.build(path)['fields']}
    named = by_key['geotizer_object.v1.r014.a01']
    unnamed = by_key['geotizer_object.v1.r014.a02']

    assert named['status'] == 'filled' and named['value'] == 'поисковые работы'
    assert unnamed['status'] == 'not_found'
    assert unnamed['value'] is None
    assert unnamed['reason'].strip()


def test_an_also_accepts_claim_carrying_a_mapping_without_its_facet_is_absent(
    exporter, dossier, tmp_path
):
    """The one path where a claim answers a cell and still holds nothing for it.

    `also_accepts` says "this predicate answers this facet", so `_answers_facet`
    returns true whatever the value's shape. A mapping that then does not name
    the facet would have been written into the cell whole. It is an absence with
    a reason instead.
    """
    changed = copy.deepcopy(dossier)
    for claim in changed['claims']:
        if claim['claim_id'] == 'clm-distance-road':
            claim['value'] = {'something_else': 12}
    path = tmp_path / 'also-accepts.json'
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')

    cell = {f['field_key']: f for f in exporter.build(path)['fields']}[
        'geotizer_object.v1.r088.a03'
    ]

    assert cell['status'] != 'filled'
    assert cell['value'] is None
    assert 'грани' in cell['reason']


def test_the_licence_carries_every_claim_that_supports_it(envelope):
    """Not the first one found. Both sources that corroborate it are named, so
    the workbook's scope traces to the same evidence the CPR reads."""
    scope = envelope['scope']

    assert scope['licence_claim_ids'] == ['clm-licence-number', 'clm-licence-number-doc']
    assert scope['licence_disagreement'] is None


def test_a_retracted_licence_claim_cannot_bind_the_scope(exporter, dossier, tmp_path):
    """The licence id binds the object scope and is what the state machine
    looks for in the authoritative source's title. Selecting it used to ignore
    claim state entirely, so a withdrawn claim could scope the whole run."""
    withdrawn = copy.deepcopy(dossier)
    for claim in withdrawn['claims']:
        if claim['predicate'] == 'licence_number':
            claim['state'] = 'retracted'
    path = tmp_path / 'retracted.json'
    path.write_text(json.dumps(withdrawn, ensure_ascii=False), encoding='utf-8')

    scope = exporter.build(path)['scope']

    assert scope['licence_id'] is None
    assert scope['licence_claim_ids'] == []


def test_two_sources_disagreeing_about_the_licence_bind_nothing(exporter, dossier, tmp_path):
    """Two customer documents can carry different licence numbers. Picking one
    would move the estimate-identity failure from a cell to the whole run."""
    disputed = copy.deepcopy(dossier)
    for claim in disputed['claims']:
        if claim['claim_id'] == 'clm-licence-number-doc':
            claim['value'] = 'СЫК 99999 БР'
    path = tmp_path / 'disputed.json'
    path.write_text(json.dumps(disputed, ensure_ascii=False), encoding='utf-8')

    scope = exporter.build(path)['scope']

    assert scope['licence_id'] is None
    assert scope['licence_disagreement'] == ['СЫК 00000 БР', 'СЫК 99999 БР']
    # Both claims stay named: the reader needs to know what disagreed.
    assert len(scope['licence_claim_ids']) == 2


def test_the_scope_carries_only_what_the_dossier_actually_holds(envelope, dossier):
    """The licence id is in the dossier. The polygon and its area are not, and
    the exporter may not invent them here where they would read as evidence."""
    scope = envelope['scope']
    assert scope['object_name'] == dossier['project_scope']['object_name']
    assert scope['project_id'] == dossier['project_scope']['project_id']
    assert scope['licence_id'] and scope['licence_claim_ids']
    assert 'coordinate_table' not in scope
    assert 'area' not in scope


def test_a_conflicted_estimate_never_becomes_a_value(exporter, dossier, tmp_path):
    """One side of an unresolved conflict in a cell would be a fact the dossier
    never asserted, and nothing downstream could tell.

    This used to `pytest.skip` on the committed dossier -- no projection row
    reaches state `conflicted`, because the dossier's only conflict is on a
    predicate no template field carries. So the exporter's entire conflict
    branch was unexecuted, and deleting it left the suite green. The conflict is
    moved onto a predicate the template does carry, which is what a customer
    dossier will look like.
    """
    disputed = copy.deepcopy(dossier)
    # `project_stage` fills row 14. Two live claims, in conflict, over it.
    stage = next(c for c in disputed['claims'] if c['claim_id'] == 'clm-stage')
    rival = {
        **copy.deepcopy(stage),
        'claim_id': 'clm-stage-rival',
        'value': 'оценочные работы',
        'state': 'conflict',
    }
    stage['state'] = 'conflict'
    disputed['claims'].append(rival)
    disputed['conflicts'].append(
        {
            'conflict_id': 'cft-stage',
            'claim_ids': ['clm-stage', 'clm-stage-rival'],
            'kind': 'estimate_identity',
            'statement': 'Две стадии по одному объекту.',
            'resolution': 'both_reported',
            'resolved_by_review_id': None,
        }
    )
    path = tmp_path / 'conflicted.json'
    path.write_text(json.dumps(disputed, ensure_ascii=False), encoding='utf-8')

    envelope = exporter.build(path)
    cell = {f['field_key']: f for f in envelope['fields']}['geotizer_object.v1.r014.a01']

    assert cell['status'] == 'conflicted'
    assert cell['value'] is None
    assert 'cft-stage' in cell['reason']
    assert 'конфликт' in cell['reason']
    # And it is not counted as an answered cell anywhere.
    assert envelope['totals']['by_status']['conflicted'] >= 1
    assert cell['field_key'] not in [
        f['field_key'] for f in envelope['fields'] if f['status'] == 'filled'
    ]


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


def test_two_supporting_claims_that_disagree_do_not_fill_the_cell(exporter, dossier, tmp_path):
    """The cell took `supporting[0]`'s value while citing every supporting claim.

    So two claims holding different values put one of them in the workbook
    attributed to both, and which one won was the sorted claim id. A cell whose
    own sources disagree is not a filled cell.
    """
    disputed = copy.deepcopy(dossier)
    for claim in disputed['claims']:
        if claim['claim_id'] == 'clm-licence-number-doc':
            claim['value'] = 'СЫК 11111 XX'
    path = tmp_path / 'disagreeing.json'
    path.write_text(json.dumps(disputed, ensure_ascii=False), encoding='utf-8')

    cell = {f['field_key']: f for f in exporter.build(path)['fields']}[
        'geotizer_object.v1.r008.a01'
    ]

    assert cell['status'] == 'conflicted'
    assert cell['value'] is None
    assert 'СЫК 11111 XX' in cell['reason'] and 'СЫК 00000 БР' in cell['reason']
    assert set(cell['claim_ids']) == {'clm-licence-number', 'clm-licence-number-doc'}


def test_two_supporting_claims_that_agree_still_fill_the_cell(envelope):
    """The guard may not turn corroboration into a refusal."""
    cell = {f['field_key']: f for f in envelope['fields']}['geotizer_object.v1.r008.a01']

    assert cell['status'] == 'filled'
    assert cell['value'] == 'СЫК 00000 БР'
    assert len(cell['claim_ids']) == 2
