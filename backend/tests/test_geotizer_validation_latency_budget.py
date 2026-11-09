"""Pin the worst-case number of local envelope checks per run and bound their cost."""

from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

from open_webui.services.artifacts.geotizer import workflow
from open_webui.services.artifacts.geotizer.project import load_mapping
from open_webui.services.artifacts.geotizer.validation import validate_owner_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY = REPO_ROOT / 'backend/open_webui/services/artifacts/geotizer/assets/geotizer-validation-parity.v1.json'

RECORDED_MAX_CHECKS = 72


def worst_case_checks() -> int:
    fields = len(load_mapping()['fields'])
    chunks = math.ceil(fields / workflow.MAX_OWNER_FIELDS_PER_CALL)
    return workflow.MAX_OWNER_ATTEMPTS * chunks + workflow.MAX_BATCHES


def test_the_run_shape_still_produces_the_recorded_worst_case():
    """The workflow's attempt, batch and chunk limits still produce the recorded worst-case check count."""
    assert workflow.MAX_OWNER_ATTEMPTS == 3
    assert workflow.MAX_BATCHES == 12
    assert workflow.MAX_OWNER_FIELDS_PER_CALL == 18
    assert worst_case_checks() == RECORDED_MAX_CHECKS


def test_the_local_check_is_cheap_enough_that_the_budget_is_not_the_argument():
    """The median local envelope check over the parity corpus takes under 16
    ms, and a worst-case run of checks under one second."""
    cases = json.loads(PARITY.read_text(encoding='utf-8'))['cases']
    empty_batch = {'batch_id': 'BUDGET', 'fields': []}

    samples = []
    for _ in range(50):
        started = time.perf_counter()
        for case in cases:
            validate_owner_envelope(empty_batch, case['envelope'])
        samples.append((time.perf_counter() - started) * 1000 / len(cases))

    assert statistics.median(samples) < 16.0
    assert worst_case_checks() * statistics.median(samples) < 1000.0


def test_the_invalidation_key_is_a_version_and_a_digest_not_a_promise():
    """The parity corpus's provenance records its validation version, source
    repository, SHA-256 digest and case count."""
    provenance = json.loads((PARITY.parent / 'provenance.json').read_text(encoding='utf-8'))
    recorded = provenance['files'][PARITY.name]

    assert recorded['validation_version'] == 'geotizer_validate_batch.v1'
    assert recorded['source_repository'] == 'data-satanism/gis_service'
    assert len(recorded['sha256']) == 64
    assert recorded['cases'] == len(json.loads(PARITY.read_text(encoding='utf-8'))['cases'])
