"""Tests that GIS proposal rejections from each batch's evidence are collected at run level with their batch and whether
another batch answered the key.
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
    """A deferred key is recorded in the same list with reason `not_this_batch`."""
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
    """Each rejection names the batch that refused it."""
    log: list[dict] = []

    record_gis_proposal_rejections(
        log, [{'deferred_field_keys': ['r037.a01']}], batch_id='GIS-DC'
    )
    record_gis_proposal_rejections(
        log, [{'deferred_field_keys': ['r037.a01']}], batch_id='KB-LIC-LEGAL'
    )

    assert [entry['batch_id'] for entry in log] == ['GIS-DC', 'KB-LIC-LEGAL']


def test_an_evidence_item_with_neither_key_adds_nothing():
    """An evidence item with neither rejection key adds nothing."""
    log: list[dict] = []

    record_gis_proposal_rejections(log, [{'route_id': 'kb-1'}], batch_id='KB-STUDY')

    assert log == []


def test_a_rejection_that_is_not_a_mapping_is_skipped():
    """A rejection entry that is not a mapping is skipped."""
    log: list[dict] = []

    record_gis_proposal_rejections(
        log, [{'unusable_field_proposals': ['r037.a01', None]}], batch_id='KB-STUDY'
    )

    assert log == []


def test_a_refused_key_says_whether_another_batch_answered_it():
    """`mark_rejections_answered_elsewhere` records whether the key's cell was filled and its status."""
    from open_webui.services.artifacts.geotizer.workflow import (
        mark_rejections_answered_elsewhere,
    )

    log = [
        {'field_key': 'geotizer_object.v1.r037.a01', 'reason': 'not_this_batch'},
        {'field_key': 'geotizer_object.v1.r041.a01', 'reason': 'not_this_batch'},
    ]
    mark_rejections_answered_elsewhere(
        log,
        [
            {'field_key': 'geotizer_object.v1.r037.a01', 'status': 'filled'},
            {'field_key': 'geotizer_object.v1.r041.a01', 'status': 'not_found'},
        ],
    )

    assert log[0]['answered_elsewhere'] is True
    assert log[0]['answered_status'] == 'filled'
    assert log[1]['answered_elsewhere'] is False
    assert log[1]['answered_status'] == 'not_found'


def test_a_refused_key_with_no_cell_is_named_as_such():
    """A rejected key matching no cell gets `answered_status` `no_such_cell`."""
    from open_webui.services.artifacts.geotizer.workflow import (
        mark_rejections_answered_elsewhere,
    )

    log = [{'field_key': 'geotizer_object.v1.r999.a99', 'reason': 'no_source_id'}]
    mark_rejections_answered_elsewhere(log, [])

    assert log[0]['answered_elsewhere'] is False
    assert log[0]['answered_status'] == 'no_such_cell'
