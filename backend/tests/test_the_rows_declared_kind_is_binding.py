"""Tests for `refuse_the_wrong_kind_of_answer`: element and mineral do not
substitute for each other, an absolute age is not a calendar year, and metal
mass is not ore tonnage."""

from __future__ import annotations


from open_webui.services.artifacts.geotizer.owner_envelope import (
    refuse_the_wrong_kind_of_answer,
)

MINERAL_ROW = 'geotizer_object.v1.r060.a01'
ELEMENT_ROW = 'geotizer_object.v1.r065.a05'
AGE_ROW = 'geotizer_object.v1.r021.a05'
ORE_ROW = 'geotizer_object.v1.r046.a02'


def batch(field_key, attribute_name):
    return {
        'batch_id': 'KB-GEO',
        'fields': [
            {
                'field_key': field_key,
                'row_id': int(field_key.split('.r')[1][:3]),
                'attribute_name': attribute_name,
            }
        ],
    }


def envelope(field_key, value, *, note=None, unit=None):
    return {
        'patches': [
            {
                'field_key': field_key,
                'status': 'filled',
                'value': value,
                'unit': unit,
                'value_origin': 'direct',
                'retrieval_note': note,
                'source_refs': ['kb__doc__1'],
                'source_locator': {},
            }
        ]
    }


def refuse(field_key, attribute_name, value, *, note=None, unit=None):
    repaired, notes = refuse_the_wrong_kind_of_answer(
        batch(field_key, attribute_name),
        envelope(field_key, value, note=note, unit=unit),
    )
    return repaired['patches'][0], notes


def rule_of(patch):
    return ((patch.get('source_locator') or {}).get('if_not_why_not') or {}).get('rule')


def test_an_element_in_a_mineral_row_is_refused():
    patch, notes = refuse(MINERAL_ROW, 'минерал 1', 'Медь')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'element_and_mineral_are_not_interchangeable'
    assert notes


def test_a_mineral_in_an_element_row_is_refused():
    """A mineral in an element row is refused."""
    patch, _ = refuse(ELEMENT_ROW, 'главное полезное ископаемое 1', 'халькопирит')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'element_and_mineral_are_not_interchangeable'


def test_the_right_kind_in_each_row_is_left_alone():
    """A mineral in a mineral row and an element in an element row are left
    alone."""
    mineral, mineral_notes = refuse(MINERAL_ROW, 'минерал 1', 'молибденит')
    element, element_notes = refuse(
        ELEMENT_ROW, 'главное полезное ископаемое 1', 'Медь'
    )

    assert mineral['status'] == 'filled' and not mineral_notes
    assert element['status'] == 'filled' and not element_notes


def test_a_mineral_the_list_does_not_know_passes():
    """An unrecognised mineral name passes."""
    patch, notes = refuse(MINERAL_ROW, 'минерал 1', 'ковеллиноподобная фаза X')

    assert patch['status'] == 'filled'
    assert not notes


def test_a_mineral_whose_name_contains_an_element_name_is_not_an_element():
    """A mineral whose name contains an element name is not taken for an
    element."""
    patch, _ = refuse(MINERAL_ROW, 'минерал 1', 'молибденит')

    assert patch['status'] == 'filled'


def test_a_native_metal_among_ore_minerals_is_not_a_substitution():
    """Element names listed beside recognised minerals in a mineral row are not
    refused."""
    patch, notes = refuse(
        'geotizer_object.v1.r059.a03',
        'сопуствующие рудные минералы',
        'сфалерит, галенит, блеклые руды, касситерит, шеелит, '
        'минералы группы платиноидов, золото, серебро',
    )

    assert patch['status'] == 'filled'
    assert not notes


def test_an_element_row_annotated_with_its_mineral_passes():
    """An element annotated with its carrier mineral passes in an element row."""
    patch, _ = refuse(ELEMENT_ROW, 'главное полезное ископаемое 1', 'Медь (халькопирит)')

    assert patch['status'] == 'filled'


def test_a_calendar_year_in_an_absolute_age_row_is_refused():
    patch, _ = refuse(AGE_ROW, 'абсолютный возраст', '1969')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'an_absolute_age_is_not_a_calendar_year'


def test_a_real_absolute_age_passes():
    """Geological ages pass in an absolute-age row."""
    for age in ('1,7 млрд лет', '250 млн лет', '~2.5 Ga', '340'):
        patch, _ = refuse(AGE_ROW, 'абсолютный возраст', age)
        assert patch['status'] == 'filled', age


def test_a_calendar_year_outside_a_work_row_is_untouched():
    """A calendar year outside the absolute-age rows is not refused."""
    patch, _ = refuse('geotizer_object.v1.r046.a05', 'год оценки', '1969')

    assert patch['status'] == 'filled'


def test_a_metal_mass_in_an_ore_tonnage_row_is_refused():
    """A metal mass, identified by its note, is refused in an ore-tonnage row."""
    patch, _ = refuse(
        ORE_ROW,
        'объем руды',
        '1.2',
        note='Объем руды не указан отдельно; тоннаж меди приведён как ресурсный показатель',
        unit='млн т',
    )

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'metal_mass_is_not_the_tonnage_of_ore'


def test_the_refused_figure_is_kept_as_a_candidate():
    """The refused value and unit are kept as a candidate, and the value is
    cleared."""
    patch, _ = refuse(
        ORE_ROW, 'объем руды', '1.2', note='тоннаж меди', unit='млн т'
    )
    candidates = (patch['source_locator'] or {}).get('candidates') or []

    assert patch['value'] is None
    assert [c['value'] for c in candidates] == ['1.2']
    assert [c['unit'] for c in candidates] == ['млн т']


def test_an_ore_tonnage_that_says_so_passes():
    patch, notes = refuse(
        ORE_ROW, 'объем руды', '12.5', note='млн т руды по категории C2', unit='млн т'
    )

    assert patch['status'] == 'filled'
    assert not notes


def test_a_refusal_is_never_not_found():
    """A wrong-kind refusal sets `requires_expert_review`, never `not_found`."""
    for field_key, attribute, value in (
        (MINERAL_ROW, 'минерал 1', 'Медь'),
        (AGE_ROW, 'абсолютный возраст', '1969'),
    ):
        patch, _ = refuse(field_key, attribute, value)
        assert patch['status'] == 'requires_expert_review', field_key


def test_a_cell_that_is_not_filled_is_not_touched():
    repaired, notes = refuse_the_wrong_kind_of_answer(
        batch(MINERAL_ROW, 'минерал 1'),
        {
            'patches': [
                {
                    'field_key': MINERAL_ROW,
                    'status': 'not_found',
                    'value': None,
                    'source_locator': {},
                }
            ]
        },
    )

    assert repaired['patches'][0]['status'] == 'not_found'
    assert not notes
