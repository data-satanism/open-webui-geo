"""The local rule copies must agree with the GIS service.

CORE-BOUNDARY-01 action 4. `validation.py` reimplements the owner-envelope
rules so a bad envelope can be repaired before it costs a batch. `gis_service`
now exposes the real check as `action=validate_batch`, and it publishes the
verdicts it returns for a corpus of envelopes. This is where the copies are
held to them.

The corpus is generated in `gis_service` through its HTTP boundary, because
that is where a caller meets the service: six of the twenty-two cases are
refused by the FastAPI request model rather than by the state machine, and a
corpus built by calling the service directly would record the wrong answer for
those.

What must match is `valid`. The two sides word a rejection differently and
always will; the corpus records the server's violation codes for diagnosis, not
for comparison.

This test is what makes deleting the copies safe, and it is also what caught
the reason they could not be deleted before: four source-inventory shapes were
accepted here and refused there.
"""

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


# -- the corpus copy -------------------------------------------------------


def test_the_corpus_matches_its_recorded_digest(provenance):
    record = provenance['files'][CORPUS_FILE]

    assert record['sha256'] == hashlib.sha256((ASSETS / CORPUS_FILE).read_bytes()).hexdigest()
    assert record['source_repository'] == 'data-satanism/gis_service'
    assert len(record['source_commit']) == 40


def test_the_corpus_names_the_validation_version_it_came_from(corpus, provenance):
    """A pinned version that moved means the server's rules changed and these
    copies are being checked against a verdict it no longer gives."""
    assert corpus['validation_version'] == 'geotizer_validate_batch.v1'
    assert provenance['files'][CORPUS_FILE]['validation_version'] == corpus['validation_version']


def test_the_corpus_has_something_to_prove(corpus):
    verdicts = {case['gis']['valid'] for case in corpus['cases']}

    assert verdicts == {True, False}
    assert len(corpus['cases']) >= 18


# -- the parity claim ------------------------------------------------------


@pytest.mark.parametrize('next_batch,case', cases(), ids=lambda p: p if isinstance(p, str) else None)
def test_the_local_copy_agrees_with_the_service(next_batch, case):
    violations = validation.validate_owner_envelope(next_batch, case['envelope'])
    accepted_here = not violations

    assert accepted_here is case['gis']['valid'], (
        f'{case["case_id"]}: gis says valid={case["gis"]["valid"]} '
        f'({case["gis"]["codes"]}), the local copy says {list(violations) or "accepted"}'
    )


def test_no_case_disagrees(corpus):
    """Stated once over the whole corpus as well as case by case, so a failure
    reads as a count rather than as one arbitrary case."""
    disagreements = [
        case['case_id']
        for case in corpus['cases']
        if bool(validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])) is case['gis']['valid']
    ]

    assert disagreements == []


def test_the_local_copy_is_never_stricter_than_the_service(corpus):
    """The dangerous direction. A copy that refuses what the server accepts
    stops a legitimate batch, and the caller cannot tell it is wrong."""
    stricter = [
        case['case_id']
        for case in corpus['cases']
        if case['gis']['valid'] and validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])
    ]

    assert stricter == []


def test_the_local_copy_is_never_weaker_than_the_service(corpus):
    """The direction that was actually broken: four source-inventory shapes
    were accepted here and refused by the server, which is how an envelope
    reached GIS and came back 422 after a whole batch had been built."""
    weaker = [
        case['case_id']
        for case in corpus['cases']
        if not case['gis']['valid'] and not validation.validate_owner_envelope(corpus['next_batch'], case['envelope'])
    ]

    assert weaker == []


def test_the_source_inventory_cases_are_covered(corpus):
    """These are the four that failed. Named explicitly so a future corpus
    regeneration cannot quietly drop them."""
    covered = {case['case_id'] for case in corpus['cases']}

    assert {
        'source_missing_title',
        'source_missing_type',
        'source_entry_is_a_string',
        'source_without_an_id',
    } <= covered


# -- which of our copies the corpus can actually vouch for ------------------


def test_the_corpus_does_not_cover_every_rule_we_copy():
    """Eleven hand-written copies of the service's rules live in
    `validation.py`; the corpus reaches five of them.

    CORE-BOUNDARY-01 action 4 says a copy may be deleted once it is shown to
    agree with the service. "Shown" means a corpus case. The six below have
    none -- they only bite on resource, plan or assemble batches, and the corpus
    is generated against `KB-LIC-LEGAL` -- so deleting them would remove a check
    nothing has replaced.

    Asserted from both directions so it cannot rot: a new rule copy with no
    case fails here, and a rule that gains a case has to be moved out of the
    list deliberately.
    """
    import ast

    tree = ast.parse(Path(validation.__file__).read_text(encoding='utf-8'))
    # The two public entry points are not rule copies; everything else is.
    entry_points = {'validate_owner_envelope', 'owner_submission'}
    rules = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name not in entry_points
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
        # The data half of the rule above, split out so the degradation in
        # `owner_envelope.refuse_incoherent_resource_rows` can read the
        # conflicting values instead of parsing them back out of a sentence.
        # One rule, two functions, and neither has a corpus case.
        'resource_row_identity_conflicts',
        # And the note predicate `_plan_patch_violations` reads, split out for
        # the same reason: it is testable on a note without an envelope.
        '_note_dates_itself_before_the_plan',
        '_semantic_patch_violations',
        '_resource_patch_violations',
        '_resource_analogue_patch_violations',
        '_plan_patch_violations',
        '_assemble_patch_violations',
        # Not a copy of a service rule: the GIS validator has no subarea check
        # and no object name to run one with. It is a local addition, so it can
        # never gain a corpus case and the service being weaker here is
        # deliberate rather than drift.
        '_subarea_patch_violations',
        '_normalized_site_name',
    }, 'a rule copy gained or lost corpus coverage; update both sides deliberately'
