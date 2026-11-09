"""Tests that a value may not carry a unit its own locator contradicts, and that a figure read off a layer summary may
not claim `calculated`.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.owner_envelope import (
    UNIT_CONTRADICTS_SOURCE_RULE,
    a_reading_is_not_a_computation,
    refuse_a_unit_the_source_contradicts,
)

TRENCH = 'geotizer_object.v1.r037.a03'


def _patch(**overrides):
    return {
        'field_key': TRENCH,
        'status': 'filled',
        'value': 0.00262,
        'unit': 'км',
        'value_origin': 'calculated',
        'source_refs': ['kb-study__part_3__lekyn_new_data_Канавы_ГСК'],
        'source_locator': {
            'feature_or_query': 'avg(Shape_Length)=0.00262°',
            'layer_id': 'Канавы_ГСК',
            'project_id': 'lekyn_new_data',
        },
        **overrides,
    }


def _refuse(*patches):
    return refuse_a_unit_the_source_contradicts({'patches': list(patches)})


def _only(envelope):
    return envelope['patches'][0]


def test_the_f38_pair_is_refused():
    """A value in km whose locator states degrees is refused to `requires_expert_review`."""
    envelope, notes = _refuse(_patch())

    patch = _only(envelope)
    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None and patch['unit'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == UNIT_CONTRADICTS_SOURCE_RULE
    assert notes


def test_both_figures_are_kept():
    """The refused value and unit are kept in `candidates`."""
    envelope, _ = _refuse(_patch())

    candidates = _only(envelope)['source_locator']['candidates']
    assert [(c['value'], c['unit']) for c in candidates] == [(0.00262, 'км')]


def test_the_same_unit_passes():
    envelope, notes = _refuse(
        _patch(
            unit='м',
            value=88,
            source_locator={'feature_or_query': 'mean:88 м', 'layer_id': 'Канавы_ГСК'},
        )
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_locator_naming_no_unit_is_silent():
    """A locator naming no unit refuses nothing."""
    envelope, notes = _refuse(
        _patch(source_locator={'layer_id': 'Канавы_ГСК', 'feature_or_query': 'строка 3'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_stated_conversion_passes():
    """A retrieval note stating a conversion lets the units differ."""
    envelope, notes = _refuse(
        _patch(
            value=88,
            unit='м',
            retrieval_note='Пересчитано из градусов в метры репроекцией в EPSG:32642.',
        )
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_deterministic_operation_is_a_stated_conversion():
    envelope, _ = _refuse(
        _patch(
            value=88,
            unit='м',
            source_locator={
                'operation': 'mean_geometry_length_m',
                'calculation_crs': 'EPSG:32642',
                'feature_or_query': 'avg(Shape_Length)=0.00262°',
            },
        )
    )

    assert _only(envelope)['status'] == 'filled'


def test_a_unit_the_table_does_not_know_never_refuses():
    """An unknown unit spelling refuses nothing."""
    envelope, notes = _refuse(
        _patch(unit='условных единиц', source_locator={'feature_or_query': 'avg=0.00262°'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_layer_named_after_a_unit_donates_nothing():
    """A unit word in a layer name is not read as the locator's unit."""
    envelope, notes = _refuse(
        _patch(unit='м', value=88, source_locator={'layer_id': 'Дороги, км'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_an_unfilled_cell_is_left_alone():
    envelope, notes = _refuse(_patch(status='not_found', value=None, unit=None))

    assert _only(envelope)['status'] == 'not_found'
    assert notes == []


def test_a_transcription_out_of_a_layer_summary_is_direct():
    envelope, notes = a_reading_is_not_a_computation({'patches': [_patch()]})

    assert _only(envelope)['value_origin'] == 'direct'
    assert notes


def test_a_gis_computation_keeps_calculated():
    """A patch whose locator names an operation and a CRS keeps `calculated`."""
    envelope, notes = a_reading_is_not_a_computation(
        {
            'patches': [
                _patch(
                    value=88,
                    unit='м',
                    source_locator={
                        'operation': 'mean_geometry_length_m',
                        'calculation_crs': 'EPSG:32642',
                        'feature_count': 34,
                        'source_layer_id': 'Канавы_ГСК',
                    },
                )
            ]
        }
    )

    assert _only(envelope)['value_origin'] == 'calculated'
    assert notes == []


def test_an_agreeing_owner_value_keeps_calculated():
    """A patch carrying `confirmed_by_calculation` keeps `calculated`."""
    envelope, _ = a_reading_is_not_a_computation(
        {
            'patches': [
                _patch(
                    value=34,
                    unit=None,
                    source_locator={
                        'layer_id': 'Канавы_ГСК',
                        'confirmed_by_calculation': {'value': 34, 'unit': None},
                    },
                )
            ]
        }
    )

    assert _only(envelope)['value_origin'] == 'calculated'


def test_an_owner_deriving_from_documents_keeps_calculated():
    """A `calculated` patch citing documents rather than a GIS layer keeps `calculated`."""
    envelope, notes = a_reading_is_not_a_computation(
        {
            'patches': [
                _patch(
                    value=101000,
                    unit='км²',
                    source_locator={'page_chunk_section': 'стр. 14', 'collection_or_url': 'kb'},
                )
            ]
        }
    )

    assert _only(envelope)['value_origin'] == 'calculated'
    assert notes == []


def test_relabelling_never_touches_the_value():
    envelope, _ = a_reading_is_not_a_computation({'patches': [_patch()]})

    patch = _only(envelope)
    assert patch['value'] == 0.00262 and patch['unit'] == 'км'


def test_a_contributor_naming_an_operation_keeps_calculated():
    """A layer locator that names an operation but states no figure with a unit keeps `calculated`."""
    envelope, notes = a_reading_is_not_a_computation(
        {
            'patches': [
                _patch(
                    value=150,
                    unit='km',
                    source_locator={
                        'project_id': 'project',
                        'layer_id': 'routes',
                        'feature_or_query': 'sum(length)',
                    },
                )
            ]
        }
    )

    assert _only(envelope)['value_origin'] == 'calculated'
    assert notes == []
