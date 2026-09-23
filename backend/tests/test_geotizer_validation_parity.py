"""The local owner-envelope rule copies in `validation.py` give the same
`valid` verdict as the GIS service on its parity corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from open_webui.services.artifacts.geotizer import validation

ASSETS = Path(validation.__file__).resolve().parent / 'assets'
CORPUS_FILE = 'geotizer-validation-parity.v1.json'


@pytest.fixture(scope='module')
def corpus():
    return json.loads((ASSETS / CORPUS_FILE).read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def provenance():
    return json.loads((ASSETS / 'provenance.json').read_text(encoding='utf-8'))


def cases():
    corpus = json.loads((ASSETS / CORPUS_FILE).read_text(encoding='utf-8'))
    return [(corpus['next_batch'], case) for case in corpus['cases']]


def case_id(param):
    return param[1]['case_id'] if isinstance(param, tuple) else ''


def test_the_corpus_matches_its_recorded_digest(provenance):
    record = provenance['files'][CORPUS_FILE]

    assert record['sha256'] == hashlib.sha256((ASSETS / CORPUS_FILE).read_bytes()).hexdigest()
    assert record['source_repository'] == 'data-satanism/gis_service'
    assert len(record['source_commit']) == 40


def test_the_corpus_names_the_validation_version_it_came_from(corpus, provenance):
    """The corpus and its provenance record name validation version `geotizer_validate_batch.v1`."""
    assert corpus['validation_version'] == 'geotizer_validate_batch.v1'
    assert provenance['files'][CORPUS_FILE]['validation_version'] == corpus['validation_version']


def test_the_corpus_has_something_to_prove(corpus):
    verdicts = {case['gis']['valid'] for case in corpus['cases']}

    assert verdicts == {True, False}
    assert len(corpus['cases']) >= 18


@pytest.mark.parametrize('next_batch,case', cases(), ids=lambda p: p if isinstance(p, str) else None)
def test_the_local_copy_agrees_with_the_service(next_batch, case):
    violations = validation.validate_owner_envelope(next_batch, case['envelope'])
    accepted_here = not violations

    assert accepted_here is case['gis']['valid'], (
        f'{case["case_id"]}: gis says valid={case["gis"]["valid"]} '
        f'({case["gis"]["codes"]}), the local copy says {list(violations) or "accepted"}'
    )


def test_no_case_disagrees(corpus):
    """No corpus case gets a different verdict from the local copy than from the service."""
    disagreements = [
        case['case_id']
        for case in corpus['cases']
        if bool(validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])) is case['gis']['valid']
    ]

    assert disagreements == []


def test_the_local_copy_is_never_stricter_than_the_service(corpus):
    """The local copy refuses no envelope the service accepts."""
    stricter = [
        case['case_id']
        for case in corpus['cases']
        if case['gis']['valid'] and validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])
    ]

    assert stricter == []


def test_the_local_copy_is_never_weaker_than_the_service(corpus):
    """The local copy accepts no envelope the service refuses."""
    weaker = [
        case['case_id']
        for case in corpus['cases']
        if not case['gis']['valid'] and not validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])
    ]

    assert weaker == []


def test_the_source_inventory_cases_are_covered(corpus):
    """The corpus includes the four source-inventory cases."""
    covered = {case['case_id'] for case in corpus['cases']}

    assert {
        'source_missing_title',
        'source_missing_type',
        'source_entry_is_a_string',
        'source_without_an_id',
    } <= covered


def test_the_corpus_does_not_cover_every_rule_we_copy():
    """The corpus covers exactly the five listed rule functions of
    `validation.py`; every other rule function is listed as uncovered."""
    import ast

    tree = ast.parse(Path(validation.__file__).read_text(encoding='utf-8'))
    entry_points = {'validate_owner_envelope', 'owner_submission'}
    message_helpers = {'_with_exit'}
    rules = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name not in entry_points
        and node.name not in message_helpers
    }
    document = json.loads((ASSETS / CORPUS_FILE).read_text(encoding='utf-8'))
    covered = {case['targets_rule'] for case in document['cases']} & rules

    assert covered == {
        '_contract_violations',
        '_partition_violations',
        '_patch_violations',
        '_source_inventory',
        '_value_origin_violations',
    }
    assert rules - covered == {
        '_resource_row_consistency_violations',
        'resource_row_identity_conflicts',
        '_note_dates_itself_before_the_plan',
        '_locator_ref_violations',
        'locator_source_refs',
        '_semantic_patch_violations',
        '_resource_patch_violations',
        '_resource_analogue_patch_violations',
        '_plan_patch_violations',
        '_assemble_patch_violations',
        '_subarea_patch_violations',
        '_normalized_site_name',
        '_names_the_whole_area',
        '_resource_unit_violations',
    }, 'a rule copy gained or lost corpus coverage; update both sides deliberately'
