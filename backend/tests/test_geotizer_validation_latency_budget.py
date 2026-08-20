"""S3.4: the envelope check's worst case, pinned so it cannot grow silently.

The step asks whether replacing the eleven local rule copies with a `validate_batch`
round-trip fits a budget. The arithmetic and the decision live in
`GMM/operations/core-boundary-01/validation-latency-budget.md`; this is the half
that has to stay true as the code changes.

It is not a speed test. The numbers here are bounds with a lot of headroom, and
a failure means the shape of the run changed -- more attempts, smaller chunks, a
bigger template -- so the decision recorded as A-36 has to be taken again with
the new numbers rather than inherited.
"""

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

# The recorded worst case: attempts x chunks, plus one merge check per batch.
RECORDED_MAX_CHECKS = 72


def worst_case_checks() -> int:
    fields = len(load_mapping()['fields'])
    chunks = math.ceil(fields / workflow.MAX_OWNER_FIELDS_PER_CALL)
    return workflow.MAX_OWNER_ATTEMPTS * chunks + workflow.MAX_BATCHES


def test_the_run_shape_still_produces_the_recorded_worst_case():
    """If this fails, the budget document is describing a different run."""
    assert workflow.MAX_OWNER_ATTEMPTS == 3
    assert workflow.MAX_BATCHES == 12
    assert workflow.MAX_OWNER_FIELDS_PER_CALL == 18
    assert worst_case_checks() == RECORDED_MAX_CHECKS


def test_the_local_check_is_cheap_enough_that_the_budget_is_not_the_argument():
    """0.16 ms at p95 over the parity corpus, so 72 of them are ~12 ms. The
    reason the copies stay is salvage under a GIS outage, not the clock -- and
    this test exists so nobody has to take that on trust."""
    cases = json.loads(PARITY.read_text(encoding='utf-8'))['cases']
    empty_batch = {'batch_id': 'BUDGET', 'fields': []}

    samples = []
    for _ in range(50):
        started = time.perf_counter()
        for case in cases:
            validate_owner_envelope(empty_batch, case['envelope'])
        samples.append((time.perf_counter() - started) * 1000 / len(cases))

    # Two orders of magnitude of headroom over the recorded 0.16 ms, so this
    # fails on a change of kind rather than on a slow machine.
    assert statistics.median(samples) < 16.0
    assert worst_case_checks() * statistics.median(samples) < 1000.0


def test_the_invalidation_key_is_a_version_and_a_digest_not_a_promise():
    """S3.4's third option -- a cached copy with an invalidation key rather than
    a hand-maintained mirror -- is what the parity corpus already is."""
    provenance = json.loads((PARITY.parent / 'provenance.json').read_text(encoding='utf-8'))
    recorded = provenance['files'][PARITY.name]

    assert recorded['validation_version'] == 'geotizer_validate_batch.v1'
    assert recorded['source_repository'] == 'data-satanism/gis_service'
    assert len(recorded['sha256']) == 64
    assert recorded['cases'] == len(json.loads(PARITY.read_text(encoding='utf-8'))['cases'])
