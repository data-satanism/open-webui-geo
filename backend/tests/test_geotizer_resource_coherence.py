from __future__ import annotations

import copy
import itertools

from open_webui.services.project_evidence.resource_coherence import (
    CALCULATED_VALUE_LABEL,
    ResourceEstimateRecord,
    cohere_resource_estimate_proposals,
)


def proposal(
    field_key,
    estimate_id,
    *,
    relation='direct',
    origin='direct',
    state='author_estimate',
    entity='target',
    site='',
):
    return {
        'field_key': field_key,
        'value': field_key,
        'resource_estimate_id': estimate_id,
        'relation_to_object': relation,
        'value_origin': origin,
        'estimate_state': state,
        'entity_id': entity,
        'site_name': site,
        'source_locator': {'document_id': 'doc-1'},
    }


def test_resource_estimate_record_ignores_non_resource_and_unscoped_values():
    assert ResourceEstimateRecord.from_proposal(proposal('geotizer_object.v1.r058.a01', 'estimate-1')) is None
    assert ResourceEstimateRecord.from_proposal(proposal('geotizer_object.v1.r050.a01', None)) is None


def test_selects_unique_best_estimate_and_drops_mixed_attributes():
    evidence = [
        {
            'route_id': 'KB',
            'field_proposals': [
                proposal('geotizer_object.v1.r050.a01', 'RE-LT-1978-001'),
                proposal('geotizer_object.v1.r050.a05', 'RE-LT-1978-001'),
                proposal('geotizer_object.v1.r050.a06', 'RE-LT-1978-001'),
                proposal('geotizer_object.v1.r050.a02', 'RE-LT-1990-001'),
                proposal('geotizer_object.v1.r050.a03', 'RE-LT-1990-001'),
                proposal('geotizer_object.v1.r050.a04', 'RE-LT-2002-001'),
                proposal('geotizer_object.v1.r058.a01', None),
            ],
        }
    ]
    original = copy.deepcopy(evidence)

    coherent, diagnostics = cohere_resource_estimate_proposals(evidence)

    assert [item['field_key'] for item in coherent[0]['field_proposals']] == [
        'geotizer_object.v1.r050.a01',
        'geotizer_object.v1.r050.a05',
        'geotizer_object.v1.r050.a06',
        'geotizer_object.v1.r058.a01',
    ]
    assert diagnostics[0]['selected_resource_estimate_id'] == 'RE-LT-1978-001'
    assert diagnostics[0]['resolution'] == 'selected_unique_best_estimate'
    assert len(diagnostics[0]['dropped_proposals']) == 3
    assert evidence == original


def test_tied_estimates_fail_closed_for_the_row():
    evidence = [
        {
            'field_proposals': [
                proposal('geotizer_object.v1.r050.a01', 'A'),
                proposal('geotizer_object.v1.r050.a02', 'B'),
                proposal('geotizer_object.v1.r057.a01', None),
            ]
        }
    ]

    coherent, diagnostics = cohere_resource_estimate_proposals(evidence)

    assert coherent[0]['field_proposals'] == [proposal('geotizer_object.v1.r057.a01', None)]
    assert diagnostics[0]['resolution'] == 'ambiguous_tie_fail_closed'
    assert diagnostics[0]['selected_resource_estimate_id'] is None


def test_internally_inconsistent_estimate_fails_closed():
    evidence = [
        {
            'field_proposals': [
                proposal(
                    'geotizer_object.v1.r050.a01',
                    'SAME-ID',
                    origin='direct',
                ),
                proposal(
                    'geotizer_object.v1.r050.a02',
                    'SAME-ID',
                    origin='analogue',
                ),
            ]
        }
    ]

    coherent, diagnostics = cohere_resource_estimate_proposals(evidence)

    assert coherent[0]['field_proposals'] == []
    assert diagnostics[0]['resolution'] == ('no_internally_consistent_estimate_fail_closed')
    assert diagnostics[0]['inconsistent_dimensions'] == {'SAME-ID': ['value_origin']}


def test_single_estimate_is_preserved_and_derived_value_is_marked():
    derived = proposal(
        'geotizer_object.v1.r044.a01',
        'ONLY',
        origin='calculated',
    )
    evidence = [{'field_proposals': [derived]}]

    coherent, diagnostics = cohere_resource_estimate_proposals(evidence)

    assert diagnostics == []
    assert coherent[0]['field_proposals'][0]['calculation_label'] == (CALCULATED_VALUE_LABEL)
    assert coherent[0]['field_proposals'][0]['source_locator']['calculation_label'] == CALCULATED_VALUE_LABEL
    assert 'calculation_label' not in evidence[0]['field_proposals'][0]


def test_decision_is_independent_of_proposal_order():
    values = [
        proposal('geotizer_object.v1.r050.a01', 'BEST'),
        proposal('geotizer_object.v1.r050.a02', 'BEST'),
        proposal('geotizer_object.v1.r050.a03', 'OTHER'),
    ]
    outcomes = set()
    for permutation in itertools.permutations(values):
        coherent, diagnostics = cohere_resource_estimate_proposals([{'field_proposals': list(permutation)}])
        outcomes.add(
            (
                diagnostics[0]['selected_resource_estimate_id'],
                tuple(sorted(item['field_key'] for item in coherent[0]['field_proposals'])),
            )
        )

    assert outcomes == {
        (
            'BEST',
            (
                'geotizer_object.v1.r050.a01',
                'geotizer_object.v1.r050.a02',
            ),
        )
    }
