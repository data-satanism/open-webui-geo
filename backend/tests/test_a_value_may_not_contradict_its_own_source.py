"""Three runs produced a wrong number in `F38` that rendered cleanly.

Each round it was wrong differently, and each round's fix moved it on:

    0.0024 «градусы»   obviously not an answer — the owner ignored it
    0.0021 bare        no unit — the owner supplied the row's
    0.00262 «км»       the source says degrees, the value says kilometres

Labelling the source stopped the owner guessing the unit. It did not stop the
owner overriding it. `0.00262 км` is 2.62 metres against a measured 88 —
wrong by a factor of 34 and entirely plausible on the page, which is the
failure mode worth designing against.

The rule is a string comparison between two fields of one patch. A locator
naming no unit is silent, an unknown spelling is silent, a stated conversion
passes, and only two known and different units refuse.

The second rule here is about the label rather than the number. Both of
`F38`'s candidates read `value_origin: calculated` in run `35509321` — one a
`mean_geometry_length_m` over 34 features in EPSG:32642, the other a figure
transcribed out of a layer summary. `calculated` is the discriminator three
rounds of verification have rested on, and a transcription may not claim it.
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


# ------------------------------------------------------- the unit comparison


def test_the_f38_pair_is_refused():
    """The exact shape run `35509321` finalized as `conflicted`."""
    envelope, notes = _refuse(_patch())

    patch = _only(envelope)
    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None and patch['unit'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == UNIT_CONTRADICTS_SOURCE_RULE
    assert notes


def test_both_figures_are_kept():
    """`requires_expert_review` with the value kept, never `not_found`.

    Something was found and policy declined it. A reviewer needs the number
    that was offered in order to judge it.
    """
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
    """The common case. Refusing on absence would refuse correct answers."""
    envelope, notes = _refuse(
        _patch(source_locator={'layer_id': 'Канавы_ГСК', 'feature_or_query': 'строка 3'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_stated_conversion_passes():
    """`0.00262°` may legitimately become `88 м` by reprojection."""
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
    """Silence on the unknown, the same narrowing the element rule needed."""
    envelope, notes = _refuse(
        _patch(unit='условных единиц', source_locator={'feature_or_query': 'avg=0.00262°'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_a_layer_named_after_a_unit_donates_nothing():
    """«Дороги, км» is a layer name, not a claim about this figure."""
    envelope, notes = _refuse(
        _patch(unit='м', value=88, source_locator={'layer_id': 'Дороги, км'})
    )

    assert _only(envelope)['status'] == 'filled'
    assert notes == []


def test_an_unfilled_cell_is_left_alone():
    envelope, notes = _refuse(_patch(status='not_found', value=None, unit=None))

    assert _only(envelope)['status'] == 'not_found'
    assert notes == []


# ------------------------------------------------ a reading is not a compute


def test_a_transcription_out_of_a_layer_summary_is_direct():
    envelope, notes = a_reading_is_not_a_computation({'patches': [_patch()]})

    assert _only(envelope)['value_origin'] == 'direct'
    assert notes


def test_a_gis_computation_keeps_calculated():
    """The operation, the CRS and the feature count are what make it one."""
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
    """The merge fix's case. `confirmed_by_calculation` is what says so."""
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
    """Run `93bc59a9` measured 69 such cells against two GIS computations.

    A broad rule here would mislabel the overwhelming majority to catch one,
    so only a patch citing a GIS layer with no operation is relabelled.
    """
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
    """`sum(length)` over a layer is an operation, not a quoted result.

    The locator has to state the figure with its unit -- the way
    `summarize_layer` prints `avg(Shape_Length)=0.00262°` -- for the value to
    be a transcription. Without that condition the rule demoted every GIS
    field proposal a contributor made, which the orchestration suite caught
    before the rule reached a run.
    """
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
