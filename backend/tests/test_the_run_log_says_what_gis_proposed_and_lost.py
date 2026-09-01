"""A diagnostic nobody can read has not recorded anything.

`normalize_gis_field_proposals_with_rejections` was written so a computed
proposal could not be dropped in silence, and `_deterministic_infrastructure_evidence`
splits its rejections into `deferred_field_keys` -- this key belongs to another
batch, which routing then delivers -- and `unusable_field_proposals` -- this
batch asked for the key and the proposal could not be used.

Both land on the batch's evidence item, and no artefact carries an evidence
item. Run `1c46b6ca` finalized with neither key anywhere in `run_log.json` or
`state.json`: the question «was a value computed for this empty cell and thrown
away?» read the same nothing it read before the diagnostic existed. So the run
level collects them, beside `gis_execution_trace`, which is where a reader
already goes to ask what GIS did.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.workflow import (
    record_gis_proposal_rejections,
)


def test_an_unusable_proposal_reaches_the_run_level():
    log: list[dict] = []

    record_gis_proposal_rejections(
        log,
        [{'unusable_field_proposals': [{'field_key': 'r037.a03', 'reason': 'no_source_id'}]}],
        batch_id='KB-STUDY',
    )

    assert log == [{'field_key': 'r037.a03', 'reason': 'no_source_id', 'batch_id': 'KB-STUDY'}]


def test_a_deferral_is_recorded_as_a_rejection_with_its_reason():
    """Deferred and unusable are one list because a reader asking «what was
    computed and not used» wants both, and two lists let one be read without
    the other."""
    log: list[dict] = []

    record_gis_proposal_rejections(
        log,
        [{'deferred_field_keys': ['geotizer_object.v1.r037.a01']}],
        batch_id='GIS-DC',
    )

    assert log == [
        {
            'field_key': 'geotizer_object.v1.r037.a01',
            'reason': 'not_this_batch',
            'batch_id': 'GIS-DC',
        }
    ]


def test_the_batch_that_refused_is_named():
    """`not_this_batch` says nothing without it: the same key deferred by
    `GIS-DC` and used by `KB-STUDY` is routing working as designed, and the
    same key deferred by every batch is a key with no owner."""
    log: list[dict] = []

    record_gis_proposal_rejections(
        log, [{'deferred_field_keys': ['r037.a01']}], batch_id='GIS-DC'
    )
    record_gis_proposal_rejections(
        log, [{'deferred_field_keys': ['r037.a01']}], batch_id='KB-LIC-LEGAL'
    )

    assert [entry['batch_id'] for entry in log] == ['GIS-DC', 'KB-LIC-LEGAL']


def test_an_evidence_item_with_neither_key_adds_nothing():
    """Most evidence items are not the deterministic one."""
    log: list[dict] = []

    record_gis_proposal_rejections(log, [{'route_id': 'kb-1'}], batch_id='KB-STUDY')

    assert log == []


def test_a_rejection_that_is_not_a_mapping_is_skipped():
    """The list arrives from a decoded payload and the loop must not raise on
    a shape the decoder did not promise."""
    log: list[dict] = []

    record_gis_proposal_rejections(
        log, [{'unusable_field_proposals': ['r037.a01', None]}], batch_id='KB-STUDY'
    )

    assert log == []
