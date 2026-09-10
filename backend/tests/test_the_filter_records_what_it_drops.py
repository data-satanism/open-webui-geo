"""`normalize_gis_field_proposals` dropped computed evidence with a bare
`continue`, and nothing downstream could tell which of two very different
things had happened.

One calculation answers eighteen roles across two batches. A proposal outside
the asking batch's `allowed_field_keys` is therefore *another batch's* — a
routing question, answered at the call site by `_receives_deterministic_gis`,
which delivers the six study roles to `KB-STUDY`.

A proposal for a key the batch *did* ask for, refused for a missing
`source_id` or an unknown `value_origin`, is nobody else's. Routing cannot
help it and until now nothing recorded it: run `af707b17` computed
`geotizer_object.v1.r037.a01` and `.a03` over the 34 features of
`Канавы_ГСК` and both cells finalized empty in silence.

So the filter reports its refusals with a reason, and the caller reads them
instead of rebuilding the deferral set from a second copy of the same test.
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
    """The failure that had no record. `r037.a03` is not another batch's —
    this batch asked for it, a value was computed, and it was unusable."""
    accepted, rejected = normalize_gis_field_proposals_with_rejections(
        _payload(), allowed_field_keys=ASKED
    )

    assert [p.field_key for p in accepted] == ['geotizer_object.v1.r037.a01']
    unusable = [r for r in rejected if r['reason'] != 'not_this_batch']
    assert unusable == [
        {'field_key': 'geotizer_object.v1.r037.a03', 'reason': 'no_source_id'}
    ]


def test_every_refusal_names_which_of_the_two_it_is():
    """A count is not enough: the caller routes one kind and reports the
    other, and it cannot do either from a number."""
    _, rejected = normalize_gis_field_proposals_with_rejections(
        _payload(), allowed_field_keys=ASKED
    )

    assert len(rejected) == 2
    assert {r['reason'] for r in rejected} == {'not_this_batch', 'no_source_id'}
    assert all(r['field_key'] for r in rejected)


def test_each_refusal_reason_is_reachable():
    """One case per reason, so the vocabulary is not decoration."""
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
    # Driven off the vocabulary rather than beside it, so a reason added to
    # `GIS_PROPOSAL_REJECTIONS` without a case that produces it fails here
    # instead of sitting in the tuple as decoration.
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
    """Four call sites place values and have nowhere to put a refusal."""
    accepted = normalize_gis_field_proposals(_payload(), allowed_field_keys=ASKED)

    assert isinstance(accepted, tuple)
    assert [p.field_key for p in accepted] == ['geotizer_object.v1.r037.a01']


def test_the_study_rows_reach_the_batch_that_owns_them():
    """The routing half, end to end. `GIS-DC` owns rows 77-88 and `KB-STUDY`
    owns 37-42; one calculation answers both. Before
    `_receives_deterministic_gis`, rows 37-42 were computed on every run and
    delivered to no batch at all, because the only batch that made the call
    filtered them straight back out.
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
    # The infrastructure row is another batch's, and says so.
    assert evidence[0]['deferred_field_keys'] == ['geotizer_object.v1.r078.a01']
    # Nothing this batch asked for was thrown away.
    assert evidence[0]['unusable_field_proposals'] == []


def test_an_unusable_proposal_is_named_on_the_evidence():
    """And when something this batch asked for *is* thrown away, the evidence
    the owner is handed says so rather than staying silent."""
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
