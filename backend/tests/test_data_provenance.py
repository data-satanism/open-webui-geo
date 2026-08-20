"""The test data that belongs to another repository, and the test data that does not.

`backend/tests/data/` holds two kinds of file. Most are produced here by
`scripts/` and are pinned by their own regeneration tests -- the committed file
against a fresh run. Two are byte-identical copies of contracts GMM owns: the
frozen example dossier both artefacts are rendered from, and its expected CPR
projection.

Those two had no provenance record at all. Nothing in any of the three
repositories compared them with GMM's originals, so editing GMM's copy -- for
instance changing both `licence_number` claims to a value the licence registry
never issued -- left every test in every repository green, with the two
repositories then rendering different things from "the same" dossier.

This is the local half: the copy against its own record, which catches a
hand-edit here. The cross-repository half needs both checkouts and lives in
GMM's `validate_evidence_copy_freshness.py`, which now walks all three.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent / 'data'
RECORD = DATA / 'provenance.json'


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding='utf-8'))


def test_the_directory_declares_which_files_are_copies():
    assert RECORD.is_file()
    assert _record()['files']


@pytest.mark.parametrize('name', sorted(_record()['files']))
def test_a_copied_contract_matches_its_recorded_digest(name):
    entry = _record()['files'][name]
    raw = (DATA / name).read_bytes()

    assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    assert len(raw) == entry['bytes']


@pytest.mark.parametrize('name', sorted(_record()['files']))
def test_every_copy_names_where_it_came_from(name):
    """A digest with no source is a number nobody can act on."""
    entry = _record()['files'][name]

    assert entry['source_repository'].count('/') == 1
    assert entry['source_path'].strip()
    assert len(entry['source_commit']) == 40
    # The record has to keep saying what it cannot check, not only what it can.
    assert entry['not_checked_here'].strip()


def test_the_record_does_not_claim_files_this_repository_produces():
    """`lekyn-owner-batches.json` and the UAT evidence are written here, not
    copied. Listing them would assert a source they do not have, and would make
    every regeneration look like drift."""
    produced = {
        'lekyn-owner-batches.json',
        'lekyn-uat-evidence.json',
        'uat-scenario-matrix.json',
        'lekyn-rag-ab-evidence.json',
    }

    assert produced.isdisjoint(_record()['files'])
    for name in produced:
        assert (DATA / name).is_file(), name


def test_no_copied_file_is_missing_from_the_record():
    """The dossier and its expected projection are the two files this directory
    does not own. If a third arrives, it must be recorded rather than blend in.
    """
    assert set(_record()['files']) == {
        'lekyn-dossier.example.json',
        'lekyn-cpr-projection.example.json',
    }
