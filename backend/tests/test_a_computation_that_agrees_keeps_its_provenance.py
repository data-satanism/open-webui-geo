"""The same number, and a different account of where it came from.

Run `4ad8fd75` finalized `r037.a01` as `34 direct`. Run `68223b5f` finalized
the same cell as `34 calculated`, over byte-identical GIS output — the same 21
trace entries, the same trench counts, the same 39 rejections. The value
survived and the provenance did not.

`calculated` means the deterministic calculation's proposal reached the cell,
with the operation, the feature count and the CRS that produced it. `direct`
means the owner wrote the number from GIS evidence it was shown: the right
answer for the wrong reason, and indistinguishable from it in the card.

The merge is where it went. `_proposal_may_replace_patch` refuses to let a
`calculated` proposal overwrite a `direct` value already in the cell — correct
when they disagree, and the wrong question when they do not. Where the two are
one claim there is nothing to adjudicate, so the value stays and the better
account of it wins.
"""

from __future__ import annotations

from open_webui.services.project_evidence.proposals import (
    AGREEMENT_NOTE_RU,
    apply_structured_gis_field_proposals,
)

FIELD = 'geotizer_object.v1.r037.a01'


def batch():
    return {
        'batch_id': 'KB-STUDY',
        'fields': [{'field_key': FIELD, 'row_id': 37, 'attribute_name': 'число'}],
    }


def envelope(value, *, unit=None, origin='direct'):
    return {
        'source_inventory': [],
        'patches': [
            {
                'field_key': FIELD,
                'status': 'filled',
                'value': value,
                'unit': unit,
                'value_origin': origin,
                'retrieval_note': 'Количество канав из слоя Канавы_ГСК',
                'source_refs': ['kb-study__part_3__Канавы_ГСК'],
                'source_locator': {'layer_id': 'Канавы_ГСК'},
            }
        ],
    }


def evidence(value, *, unit=None):
    return [
        {
            'route_id': 'gis-1',
            'agent': 'gis',
            'source_domain': 'gis',
            'field_proposals': [
                {
                    'field_key': FIELD,
                    'value': value,
                    'unit': unit,
                    'value_origin': 'calculated',
                    'relation_to_object': 'direct',
                    'source_id': 'gis-study-df0d4d56c2cfe05d',
                    'source_title': 'GIS study aggregate: Канавы_ГСК',
                    'source_locator': {
                        'operation': 'feature_count',
                        'project_id': 'lekyn_new_data',
                        'semantic_role': 'trench',
                        'source_layer_id': 'Канавы_ГСК',
                        'calculation_crs': 'EPSG:32642',
                        'feature_count': 34,
                    },
                    'retrieval_note': 'Calculated over 34 features of Канавы_ГСК',
                }
            ],
        }
    ]


def applied(held, arriving, *, held_unit=None, arriving_unit=None):
    return apply_structured_gis_field_proposals(
        batch(),
        envelope(held, unit=held_unit),
        evidence(arriving, unit=arriving_unit),
    )['patches'][0]


def test_an_agreeing_calculation_takes_the_provenance():
    patch = applied(34, 34)

    assert patch['value'] == 34
    assert patch['value_origin'] == 'calculated'


def test_the_calculation_that_agreed_is_recorded_beside_the_value():
    """Not only the origin word. A reader has to be able to check the claim,
    and that needs the operation, the feature count and the CRS."""
    patch = applied(34, 34)
    confirmed = patch['source_locator']['confirmed_by_calculation']

    assert confirmed['value'] == 34
    assert confirmed['locator']['operation'] == 'feature_count'
    assert confirmed['locator']['calculation_crs'] == 'EPSG:32642'
    assert confirmed['source_ref'] in patch['source_refs']


def test_the_owners_note_is_kept_and_added_to():
    """The owner's account of where it looked is still true. This adds the half
    the owner could not state."""
    patch = applied(34, 34)

    assert 'Количество канав из слоя Канавы_ГСК' in patch['retrieval_note']
    assert AGREEMENT_NOTE_RU in patch['retrieval_note']


def test_a_disagreeing_calculation_does_not_take_the_provenance():
    """The narrowing is to agreement. Where the two differ the existing rules
    decide, and a `calculated` proposal still may not overwrite a `direct`
    value — that is the case `_proposal_may_replace_patch` exists for."""
    patch = applied(34, 41)

    assert patch['value'] == 34
    assert patch['value_origin'] == 'direct'
    assert 'confirmed_by_calculation' not in patch['source_locator']


def test_a_stated_unit_against_an_unstated_one_is_still_agreement():
    """One side said what the number is measured in and the other did not; that
    is not a disagreement, and `_claims_are_one` has said so since run
    `6af7479f`. The cell takes the unit it was missing."""
    patch = applied(88, 88, held_unit=None, arriving_unit='м')

    assert patch['value_origin'] == 'calculated'
    assert patch['unit'] == 'м'


def test_two_different_stated_units_are_not_agreement():
    """`0.0021 км` against `88 м` is the conflict this run actually had, and it
    must stay one."""
    patch = applied(88, 88, held_unit='км', arriving_unit='м')

    assert patch['value_origin'] == 'direct'
    assert 'confirmed_by_calculation' not in patch['source_locator']
