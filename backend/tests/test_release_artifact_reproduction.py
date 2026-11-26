"""CUST-DEPLOY-01: the artefacts reproduce from the release manifest.

GMM holds the manifest and this repository holds the renderers, so the check
lives here and takes the manifest as an argument. These tests build a manifest
from the local run rather than reaching for GMM's -- CI has no GMM checkout, and
a test that silently skips when a path is missing proves nothing.

What is asserted is the comparison itself: it passes on a faithful manifest and
fails on every way a contour could drift from one.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from verify_release_artifacts import compare, rebuild  # noqa: E402

DATA = Path(__file__).resolve().parent / 'data'


@pytest.fixture(scope='module')
def rebuilt():
    return rebuild()


@pytest.fixture(scope='module')
def manifest(rebuilt):
    return {
        'package_id': 'test-manifest',
        'artifacts': [
            {
                'name': name,
                'content_sha256': hashlib.sha256(payload).hexdigest(),
                'bytes': len(payload),
                'produced_by': 'scripts/run_cpr_geotizer_uat.py',
            }
            for name, payload in sorted(rebuilt.items())
        ],
    }


def test_a_faithful_manifest_reproduces(manifest, rebuilt):
    assert compare(manifest, rebuilt) == []


def test_the_five_artifacts_are_the_ones_the_uat_run_produced(rebuilt):
    """The same renderers, called the same way. If this drifts, the release
    manifest and the UAT evidence are describing different pipelines."""
    evidence = json.loads((DATA / 'lekyn-uat-evidence.json').read_text(encoding='utf-8'))
    recorded = {a['name']: a['content_sha256'] for a in evidence['artifacts']}

    assert {name: hashlib.sha256(p).hexdigest() for name, p in rebuilt.items()} == recorded


def test_a_changed_artifact_is_caught(manifest, rebuilt):
    drifted = dict(rebuilt)
    drifted['audit.md'] = rebuilt['audit.md'] + b'\n'

    problems = compare(manifest, drifted)

    assert len(problems) == 1
    assert problems[0].startswith('audit.md: rebuilt digest ')


def test_an_artifact_the_manifest_never_pinned_is_caught(manifest, rebuilt):
    extra = dict(rebuilt)
    extra['unexpected.txt'] = b'produced by something the manifest does not know about'

    assert compare(manifest, extra) == ['unexpected.txt: rebuilt but not pinned by the manifest']


def test_an_artifact_the_contour_no_longer_produces_is_caught(manifest, rebuilt):
    missing = {name: payload for name, payload in rebuilt.items() if name != 'coverage.json'}

    assert compare(manifest, missing) == ['coverage.json: pinned by the manifest but not rebuilt']


def test_an_empty_manifest_reports_every_artifact(manifest, rebuilt):
    """Not silence. A manifest with no artefacts pins nothing, and a check that
    passed on it would certify a contour nobody described."""
    problems = compare({'artifacts': []}, rebuilt)

    assert len(problems) == len(rebuilt)


def test_the_rebuild_is_deterministic(rebuilt):
    """Same dossier, same bytes -- the property the whole release rests on."""
    again = rebuild()

    assert {k: hashlib.sha256(v).hexdigest() for k, v in again.items()} == {
        k: hashlib.sha256(v).hexdigest() for k, v in rebuilt.items()
    }


@pytest.mark.parametrize('name_ids', [list(range(7)), list(range(256))])
def test_the_pdf_does_not_depend_on_the_subsetter_name_id_default(monkeypatch, name_ids):
    """fontTools 4.69.0 widened `Options.name_IDs` from 0-6 to 0-255, and fpdf2
    sets none, so the embedded font's name table followed the installed
    fontTools. The PDF digest must be the recorded one under either default."""
    from fontTools import subset

    class Options(subset.Options):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.name_IDs = name_ids

    monkeypatch.setattr(subset, 'Options', Options)
    evidence = json.loads((DATA / 'lekyn-uat-evidence.json').read_text(encoding='utf-8'))
    recorded = {a['name']: a['content_sha256'] for a in evidence['artifacts']}

    assert hashlib.sha256(rebuild()['cpr_readiness.pdf']).hexdigest() == recorded['cpr_readiness.pdf']
