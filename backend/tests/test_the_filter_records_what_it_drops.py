"""Tests that `normalize_gis_field_proposals_with_rejections` reports every refused GIS proposal with a reason, and that
the workflow routes and reports them.
"""

from __future__ import annotations

import json

from open_webui.services.project_evidence.proposals import (
    GIS_PROPOSAL_REJECTIONS,
    normalize_gis_field_proposals,
    normalize_gis_field_proposals_with_rejections,
)

ASKED = [
    'geotizer_object.v1.r037.a01',
    'geotizer_object.v1.r037.a03',
]


def _payload() -> str:
    return json.dumps(
        {
            'field_proposals': [
                {
                    'field_key': 'geotizer_object.v1.r037.a01',
                    'value': 34,
                    'value_origin': 'calculated',
                    'source_id': 'gis:Канавы_ГСК',
                    'source_locator': {'layer_id': 'Канавы_ГСК'},
                    'retrieval_note': 'count over 34 features',
                },
                {
                    'field_key': 'geotizer_object.v1.r037.a03',
                    'value': 118.4,
                    'value_origin': 'calculated',
                    'source_id': '',
                    'source_locator': {'layer_id': 'Канавы_ГСК'},
                    'retrieval_note': 'mean length',
                },
                {
                    'field_key': 'geotizer_object.v1.r078.a01',
                    'value': 95365.64,
                    'value_origin': 'calculated',
                    'source_id': 'gis:PPP_ADM',
                    'source_locator': {'layer_id': 'PPP_ADM'},
                    'retrieval_note': 'distance to settlement',
                },
            ]
        },
        ensure_ascii=False,
    )


def test_a_key_another_batch_owns_is_deferred_not_dropped():
    _, rejected = normalize_gis_field_proposals_with_rejections(
        _payload(), allowed_field_keys=ASKED
    )

    deferred = [r for r in rejected if r['reason'] == 'not_this_batch']
    assert [r['field_key'] for r in deferred] == ['geotizer_object.v1.r078.a01']


def test_a_key_this_batch_asked_for_is_never_dropped_in_silence():
    """A proposal for an asked-for key that is unusable is reported with its reason."""
    accepted, rejected = normalize_gis_field_proposals_with_rejections(
        _payload(), allowed_field_keys=ASKED
    )

    assert [p.field_key for p in accepted] == ['geotizer_object.v1.r037.a01']
    unusable = [r for r in rejected if r['reason'] != 'not_this_batch']
    assert unusable == [
        {'field_key': 'geotizer_object.v1.r037.a03', 'reason': 'no_source_id'}
    ]


def test_every_refusal_names_which_of_the_two_it_is():
    """Every refusal carries its field key and a reason distinguishing another batch's key from an unusable one."""
    _, rejected = normalize_gis_field_proposals_with_rejections(
        _payload(), allowed_field_keys=ASKED
    )

    assert len(rejected) == 2
    assert {r['reason'] for r in rejected} == {'not_this_batch', 'no_source_id'}
    assert all(r['field_key'] for r in rejected)


def test_each_refusal_reason_is_reachable():
    """Each reason in `GIS_PROPOSAL_REJECTIONS` is produced by some proposal."""
    base = {
        'field_key': 'geotizer_object.v1.r037.a01',
        'value': 34,
        'value_origin': 'calculated',
        'source_id': 'gis:Канавы_ГСК',
        'source_locator': {'layer_id': 'Канавы_ГСК'},
        'retrieval_note': 'count',
        'query_id': 'q1',
    }
    cases = {
        'no_value': {'value': None},
        'unknown_value_origin': {'value_origin': 'guessed'},
        'no_source_id': {'source_id': ''},
        'no_source_locator': {'source_locator': {}},
        'derived_value_without_note': {'retrieval_note': ''},
        'foreign_query_id': {'query_id': 'q9'},
    }
    assert set(cases) | {'not_this_batch'} == set(GIS_PROPOSAL_REJECTIONS)
    for reason, override in cases.items():
        payload = json.dumps({'field_proposals': [{**base, **override}]}, ensure_ascii=False)
        _, rejected = normalize_gis_field_proposals_with_rejections(
            payload,
            allowed_field_keys=[base['field_key']],
            allowed_query_ids=['q1'],
        )
        assert [r['reason'] for r in rejected] == [reason], reason


def test_the_plain_call_still_returns_only_proposals():
    """`normalize_gis_field_proposals` returns only the accepted proposals, as a tuple."""
    accepted = normalize_gis_field_proposals(_payload(), allowed_field_keys=ASKED)

    assert isinstance(accepted, tuple)
    assert [p.field_key for p in accepted] == ['geotizer_object.v1.r037.a01']


def test_the_study_rows_reach_the_batch_that_owns_them():
    """A `KB-STUDY` batch receives the deterministic study-row proposals and lists the infrastructure row as deferred.
    """
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    deterministic = {
        'workflow_status': 'ready',
        'layer_manifest': [{'layer_id': 'Канавы_ГСК'}],
        'field_proposals': [
            {
                'field_key': 'geotizer_object.v1.r037.a01',
                'value': 34,
                'value_origin': 'calculated',
                'source_id': 'gis:Канавы_ГСК',
                'source_locator': {'layer_id': 'Канавы_ГСК'},
                'retrieval_note': 'count over 34 features',
            },
            {
                'field_key': 'geotizer_object.v1.r037.a03',
                'value': 118.4,
                'value_origin': 'calculated',
                'source_id': 'gis:Канавы_ГСК',
                'source_locator': {'layer_id': 'Канавы_ГСК'},
                'retrieval_note': 'mean length',
            },
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'value': 95365.64,
                'value_origin': 'calculated',
                'source_id': 'gis:PPP_ADM',
                'source_locator': {'layer_id': 'PPP_ADM'},
                'retrieval_note': 'distance to settlement',
            },
        ],
    }

    async def gis_call(_request):
        return deterministic

    batch = {
        'batch_id': 'KB-STUDY',
        'fields': [{'field_key': key} for key in ASKED],
    }
    evidence = asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch=batch,
            run_id='803ce041',
            allowed_field_keys=ASKED,
            gis_call=gis_call,
            cache={},
        )
    )

    assert len(evidence) == 1
    proposed = {p['field_key']: p['value'] for p in evidence[0]['field_proposals']}
    assert proposed == {
        'geotizer_object.v1.r037.a01': 34,
        'geotizer_object.v1.r037.a03': 118.4,
    }
    assert evidence[0]['deferred_field_keys'] == ['geotizer_object.v1.r078.a01']
    assert evidence[0]['unusable_field_proposals'] == []


def test_an_unusable_proposal_is_named_on_the_evidence():
    """An unusable proposal for an asked-for key is listed in `unusable_field_proposals` on the evidence."""
    import asyncio

    from open_webui.services.artifacts.geotizer.workflow import (
        _deterministic_infrastructure_evidence,
    )

    async def gis_call(_request):
        return {
            'workflow_status': 'ready',
            'field_proposals': [
                {
                    'field_key': 'geotizer_object.v1.r037.a03',
                    'value': 118.4,
                    'value_origin': 'calculated',
                    'source_id': '',
                    'source_locator': {'layer_id': 'Канавы_ГСК'},
                    'retrieval_note': 'mean length',
                }
            ],
        }

    evidence = asyncio.run(
        _deterministic_infrastructure_evidence(
            next_batch={'batch_id': 'KB-STUDY', 'fields': [{'field_key': k} for k in ASKED]},
            run_id='803ce041',
            allowed_field_keys=ASKED,
            gis_call=gis_call,
            cache={},
        )
    )

    assert evidence[0]['field_proposals'] == []
    assert evidence[0]['deferred_field_keys'] == []
    assert evidence[0]['unusable_field_proposals'] == [
        {'field_key': 'geotizer_object.v1.r037.a03', 'reason': 'no_source_id'}
    ]
