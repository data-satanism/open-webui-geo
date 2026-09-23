"""The workbook is a projection of the dossier, and every filled field traces to a
source claim or a calculation."""

from __future__ import annotations

import copy
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from open_webui.services.artifacts.geotizer import project
from open_webui.services.geotizer.errors import GeotizerOrchestrationError

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


def row(projection, field_key):
    return next(r for r in projection['fields'] if r['field_key'] == field_key)


def test_the_mapping_covers_the_whole_template(projection):
    assert len(projection['fields']) == 351
    assert projection['template_field_count'] == 351
    assert len({r['field_key'] for r in projection['fields']}) == 351


def test_a_drifted_mapping_is_refused(tmp_path):
    assets = tmp_path / 'assets'
    shutil.copytree(project.ASSETS, assets)
    path = assets / project.MAPPING_FILE
    edited = json.loads(path.read_text(encoding='utf-8'))
    edited['fields'][0]['predicate'] = 'anything_at_all'
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')

    with pytest.raises(GeotizerOrchestrationError, match='digest'):
        project.load_mapping(assets)


def test_no_filled_field_lacks_a_source_claim(projection):
    """The half of the completion criterion this side owns."""
    assert project.unsourced_fields(projection) == ()


def test_every_filled_cell_names_claims_that_exist(projection, dossier):
    known = {claim['claim_id'] for claim in dossier['claims']}

    for entry in projection['fields']:
        for claim_id in entry['supporting_claim_ids']:
            assert claim_id in known, entry['field_key']


def test_the_projection_carries_no_value_and_no_narrative(projection):
    """The projection addresses claims by id and carries no value, unit, quoted text or
    narrative."""
    text = json.dumps(projection, ensure_ascii=False)

    for marker in ('"value"', '"unit"', '"quoted_text"', '"narrative"', '"text"'):
        assert marker not in text


def test_a_scalar_claim_fills_one_cell_and_not_its_whole_row(projection):
    """A scalar claim fills only the facet it answers, not every cell of its row."""
    assert row(projection, 'geotizer_object.v1.r014.a01')['state'] == 'supported'
    assert row(projection, 'geotizer_object.v1.r014.a02')['state'] == 'missing'
    assert row(projection, 'geotizer_object.v1.r014.a03')['state'] == 'missing'


def test_a_structured_claim_fills_the_facets_it_names(mutable_dossier):
    """A claim whose value is a mapping fills the facets it names."""
    claim = next(c for c in mutable_dossier['claims'] if c['claim_id'] == 'clm-stage')
    claim['value'] = {'stage': 'поисковые работы', 'start_date': '2024-01-01'}

    built = project.build_projection(mutable_dossier)

    assert row(built, 'geotizer_object.v1.r014.a01')['state'] == 'supported'
    assert row(built, 'geotizer_object.v1.r014.a02')['state'] == 'supported'
    assert row(built, 'geotizer_object.v1.r014.a03')['state'] == 'missing'


def test_a_second_predicate_answers_the_facet_it_was_registered_for(projection):
    """`distance_to_nearest_road` fills row 88's distance cell and nothing else in the
    row."""
    entry = row(projection, 'geotizer_object.v1.r088.a03')

    assert entry['state'] == 'supported'
    assert entry['supporting_claim_ids'] == ['clm-distance-road']
    assert row(projection, 'geotizer_object.v1.r088.a01')['state'] == 'missing'


def test_the_licence_number_is_corroborated(projection):
    entry = row(projection, 'geotizer_object.v1.r008.a01')

    assert entry['state'] == 'corroborated'
    assert entry['supporting_claim_ids'] == ['clm-licence-number', 'clm-licence-number-doc']


def test_a_calculated_extra_reads_the_claim_it_returned(projection):
    """A calculated artifact-specific cell reads the claim it returned to the dossier."""
    entry = row(projection, 'geotizer_object.v1.r086.a01')

    assert entry['projection_kind'] == 'artifact_specific_calculated'
    assert entry['returned_claim_id'] == 'clm-licences-50km'
    assert entry['supporting_claim_ids'] == ['clm-licences-50km']


def test_the_reviewed_gap_carries_its_expert_approval(projection):
    entry = row(projection, 'geotizer_object.v1.r064.a01')

    assert entry['state'] == 'not_applicable'
    assert entry['gap_ids'] == ['gap-mining-method']
    assert entry['expert_approved_not_applicable'] is True


def test_only_an_expert_approved_not_applicable_leaves_the_denominator(projection):
    approved = [r for r in projection['fields'] if r['expert_approved_not_applicable']]

    assert len(approved) == 1
    assert projection['totals']['expert_approved_not_applicable'] == 1


def test_the_states_are_what_the_dossier_supports(projection):
    counts = Counter(entry['state'] for entry in projection['fields'])

    assert counts == {'missing': 346, 'supported': 3, 'corroborated': 1, 'not_applicable': 1}


def test_the_eighty_percent_criterion_is_not_met_by_this_dossier(projection):
    """Semantic completeness of the example dossier is 1.14%."""
    assert projection['totals']['semantic_completeness_percent'] == pytest.approx(1.14)


def test_the_denominator_is_351_less_the_approved_not_applicable(projection):
    answered = sum(1 for r in projection['fields'] if r['state'] in {'supported', 'corroborated'})
    approved = projection['totals']['expert_approved_not_applicable']

    assert answered == 4
    assert projection['totals']['semantic_completeness_percent'] == pytest.approx(
        round(100.0 * answered / (351 - approved), 2)
    )


def test_a_slice_publishes_no_completeness_rate(dossier):
    """A `reference_slice` projection publishes no completeness rate."""
    built = project.build_projection(dossier, scope='reference_slice')

    assert 'semantic_completeness_percent' not in built['totals']


def test_every_absent_cell_says_why(projection):
    for entry in projection['fields']:
        if entry['state'] in {'missing', 'not_applicable', 'blocked_expert'}:
            assert entry['if_not_why_not']['reason'].strip(), entry['field_key']


def test_a_row_the_cpr_cannot_yield_says_so_rather_than_blaming_the_sources(projection):
    """An artifact-specific row the dossier cannot yield names that reason rather than a
    missing source."""
    entry = row(projection, 'geotizer_object.v1.r050.a01')

    assert entry['projection_kind'] == 'ARTIFACT_SPECIFIC'
    assert 'subdivision' in entry['if_not_why_not']['reason']
    assert 'no fallback may invent one' in entry['if_not_why_not']['reason']


def test_an_analogue_row_stays_advisory_and_empty(projection):
    entry = row(projection, 'geotizer_object.v1.r054.a01')

    assert entry['projection_kind'] == 'artifact_specific_advisory'
    assert entry['state'] == 'missing'
    assert entry['returned_claim_id'] is None


def test_an_analogy_claim_never_reaches_a_field_that_forbids_one(mutable_dossier):
    claim = next(c for c in mutable_dossier['claims'] if c['value_origin']['kind'] == 'analogy')
    claim['predicate'] = 'licence_number'

    built = project.build_projection(mutable_dossier)

    assert claim['claim_id'] not in row(built, 'geotizer_object.v1.r008.a01')['supporting_claim_ids']


def test_a_stale_claim_stops_filling_its_cell(mutable_dossier):
    for claim in mutable_dossier['claims']:
        if claim['claim_id'] == 'clm-licences-50km':
            claim['state'] = 'stale'

    built = project.build_projection(mutable_dossier)
    entry = row(built, 'geotizer_object.v1.r086.a01')

    assert entry['state'] == 'missing'
    assert entry['returned_claim_id'] is None


def test_the_trace_carries_the_run_the_version_and_the_claims(projection, dossier):
    """The trace carries the dossier run id, the projection version, the frozen inputs
    hash and each entry's claim ids."""
    trace = project.projection_trace(projection, dossier)

    assert trace['dossier_run_id'] == dossier['dossier_run_id']
    assert trace['projection_version'] == 'cpr_to_geotizer.v1'
    assert trace['frozen_inputs_hash'] == dossier['frozen_inputs_hash']
    assert trace['filled_fields'] == 4
    for entry in trace['entries']:
        assert entry['claim_ids']


def test_the_trace_lists_every_filled_cell_and_nothing_else(projection, dossier):
    trace = project.projection_trace(projection, dossier)
    filled = {
        entry['field_key']
        for entry in projection['fields']
        if entry['state'] in {'supported', 'corroborated', 'conflicted'}
    }

    assert {entry['field_key'] for entry in trace['entries']} == filled
