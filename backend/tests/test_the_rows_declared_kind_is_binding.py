"""Three of the Domain Reviewer's five answers, made enforceable.

Recorded 2026-08-30 in
`operations/domain-review/2026-08-30__five-answers-from-the-domain-reviewer.md`
(GMM), and unqualified in all three cases:

    «Допустимо ли использовать название минерала в поле элемента и наоборот?»
        — Нет.
    «Как отличить абсолютный возраст от календарного года работ?»
        — Абсолютный возраст ... измеряется в миллиардах лет.
    «Допустимо ли подменять тоннаж руды массой металла?»
        — Нет.

The fourth answer — «не знаю, это совершенно разные сущности» about
technological samples and study records — is deliberately **not** implemented.
An expert saying two entities are unmistakable is an expert saying no
discriminating rule is needed, and inventing one would be this repository
making up a domain distinction the domain does not have.

The asymmetry between the two vocabularies decides the shape of the first rule.
Elements are a closed set. Minerals are not, and a rule that refused anything
absent from a hand-written mineral list would refuse correct answers -- so both
directions fire on positive identification only, and anything unrecognised
passes.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import (
    refuse_the_wrong_kind_of_answer,
)

MINERAL_ROW = 'geotizer_object.v1.r060.a01'      # D61 «минерал 1»
ELEMENT_ROW = 'geotizer_object.v1.r065.a05'      # H66 «главное полезное ископаемое 1»
AGE_ROW = 'geotizer_object.v1.r021.a05'          # H22 «абсолютный возраст»
ORE_ROW = 'geotizer_object.v1.r046.a02'          # E47 «объем руды»


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


# -- answer 1: element and mineral do not substitute ---------------------

def test_an_element_in_a_mineral_row_is_refused():
    patch, notes = refuse(MINERAL_ROW, 'минерал 1', 'Медь')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'element_and_mineral_are_not_interchangeable'
    assert notes


def test_a_mineral_in_an_element_row_is_refused():
    """Both directions, because the answer was unqualified in both."""
    patch, _ = refuse(ELEMENT_ROW, 'главное полезное ископаемое 1', 'халькопирит')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'element_and_mineral_are_not_interchangeable'


def test_the_right_kind_in_each_row_is_left_alone():
    """Run `1c46b6ca` has both of these, correct, and the rule must not touch
    them: D61 reads «молибденит» and H66 reads «Медь»."""
    mineral, mineral_notes = refuse(MINERAL_ROW, 'минерал 1', 'молибденит')
    element, element_notes = refuse(
        ELEMENT_ROW, 'главное полезное ископаемое 1', 'Медь'
    )

    assert mineral['status'] == 'filled' and not mineral_notes
    assert element['status'] == 'filled' and not element_notes


def test_a_mineral_the_list_does_not_know_passes():
    """The rule fires only when it is sure. No hand-written mineral list is
    complete, and refusing an unrecognised name would refuse correct answers
    -- which is worse than missing a wrong one."""
    patch, notes = refuse(MINERAL_ROW, 'минерал 1', 'ковеллиноподобная фаза X')

    assert patch['status'] == 'filled'
    assert not notes


def test_a_mineral_whose_name_contains_an_element_name_is_not_an_element():
    """«молибденит» contains «молибден» and is a mineral. The element match is
    on whole tokens for exactly this reason."""
    patch, _ = refuse(MINERAL_ROW, 'минерал 1', 'молибденит')

    assert patch['status'] == 'filled'


def test_a_native_metal_among_ore_minerals_is_not_a_substitution():
    """The answer refused *substitution*, and native metals are both things at
    once. Run `1c46b6ca` has the case: F60 «сопутствующие рудные минералы»
    lists «... шеелит, минералы группы платиноидов, золото, серебро» — native
    gold and native silver, correctly among ore minerals. Firing on the element
    name alone refuses that, so both directions require the other kind to be
    absent."""
    patch, notes = refuse(
        'geotizer_object.v1.r059.a03',
        'сопуствующие рудные минералы',
        'сфалерит, галенит, блеклые руды, касситерит, шеелит, '
        'минералы группы платиноидов, золото, серебро',
    )

    assert patch['status'] == 'filled'
    assert not notes


def test_an_element_row_annotated_with_its_mineral_passes():
    """The mirror of the case above. «Медь (халькопирит)» names the commodity
    and says which mineral carries it; that is an annotation, not a
    substitution."""
    patch, _ = refuse(ELEMENT_ROW, 'главное полезное ископаемое 1', 'Медь (халькопирит)')

    assert patch['status'] == 'filled'


# -- answer 2: absolute age is not a work year --------------------------

def test_a_calendar_year_in_an_absolute_age_row_is_refused():
    patch, _ = refuse(AGE_ROW, 'абсолютный возраст', '1969')

    assert patch['status'] == 'requires_expert_review'
    assert rule_of(patch) == 'an_absolute_age_is_not_a_calendar_year'


def test_a_real_absolute_age_passes():
    """«измеряется в миллиардах лет». No geological age falls in 1900-2100, and
    an age written in млн/млрд лет does not parse as a bare four-digit year, so
    the check is a numeric range and needs no vocabulary at all."""
    for age in ('1,7 млрд лет', '250 млн лет', '~2.5 Ga', '340'):
        patch, _ = refuse(AGE_ROW, 'абсолютный возраст', age)
        assert patch['status'] == 'filled', age


def test_a_calendar_year_outside_a_work_row_is_untouched():
    """The rule is bound to the age rows. A year in «год оценки» is the answer
    that row wants."""
    patch, _ = refuse('geotizer_object.v1.r046.a05', 'год оценки', '1969')

    assert patch['status'] == 'filled'


# -- answer 4: metal mass is not ore tonnage ----------------------------

def test_a_metal_mass_in_an_ore_tonnage_row_is_refused():
    """The three cells that exhibited this said it in their own note rather
    than in the number: a bare «1,2» is neither quantity on its face."""
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
    """Where a source gives ore tonnage, grade and contained metal, that is one
    estimate answering three rows — not one number serving all three. A
    reviewer needs the number that was offered in order to route it."""
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


# -- the shape every one of them shares ---------------------------------

def test_a_refusal_is_never_not_found():
    """Something was found and policy declined it. `not_found` says nobody
    found anything, and coercing to it would drop the value a reviewer needs.
    Established two rounds ago and unchanged by any of these answers."""
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
