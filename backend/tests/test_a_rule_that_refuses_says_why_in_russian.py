"""Every rule that refuses a value states a sentence a reader can act on.

The card renders a rule's message and never its name. That is a rule about the
renderer, in `gis_service`, and it has a supply half here: a rule whose
`stated_reason` is empty leaves the renderer with nothing to print, and the
card then says only that a rule refused -- which is less than run `c0455027`'s
card said, and the whole point was to say more.

That run's evidence:

    rule                                              cells  of which empty
    unit_contradicts_its_source                         1          0
    spatial_question_needs_a_spatial_answer            20          6
    resource_estimate_needs_more_than_a_press_number   23         20
    an_object_outside_the_radius_does_not_answer…       1   no such key

Counted from the run's own `state.json`, not from the rule's frequency: the
two middle rules quote the specialist's `retrieval_note` and the note is
sometimes there, so 27 of the 45 refused cells had no sentence rather than all
45. The fourth rule kept its sentence in `selection_trace` and wrote none
beside the rule at all.

The quoted note is still preferred where there is one: it names the actual
publication, the actual units, the actual layer. What changed is that a rule
now owes a sentence in every case rather than only in the case where someone
else happened to write one.
"""

from __future__ import annotations

import re

import pytest


#: The same shape `gis_service.reader_text.MACHINE_TOKEN` refuses to print.
#: Stated twice on purpose: the two repositories deploy separately, and a
#: sentence that passes here and is dropped there would be a rule that looks
#: answered and renders as a gap.
MACHINE_TOKEN = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+')


def _resource_envelope(retrieval_note):
    return {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 's1', 'source_type': 'web', 'title': 'источник'},
        ],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r046.a01',
                'value': '830000',
                'unit': 'тонн руды',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['s1'],
                'source_locator': {'page': 3},
                'retrieval_note': retrieval_note,
            }
        ],
    }


def _spatial_envelope(retrieval_note):
    return {
        'source_inventory': [
            {'source_id': 'kb-1', 'source_type': 'knowledge_base', 'title': 'Приложение'},
        ],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'value': 130,
                'unit': 'км',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['kb-1'],
                'source_locator': {'page': '4'},
                'retrieval_note': retrieval_note,
            }
        ],
    }


_UNANSWERABLE = [
    {
        'field_key': 'geotizer_object.v1.r078.a01',
        'roles': ['settlement'],
        'role_labels': ['населённый пункт'],
        'code': 'layer_not_found',
    }
]


def _reason(patch):
    return patch['source_locator']['if_not_why_not']['stated_reason']


def _radius_envelope(value):
    """An r084 patch whose object is 130 km away, against a 50 km row."""
    return {
        'source_inventory': [
            {'source_id': 'w1', 'source_type': 'web', 'title': 'статья'},
        ],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a02',
                'value': value,
                'unit': None,
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['w1'],
                'source_locator': {},
                'retrieval_note': '',
            }
        ],
    }


# --- the lone-web resource rule --------------------------------------------

def test_a_lone_web_refusal_states_a_reason_when_the_note_is_empty():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        LONE_WEB_RESOURCE_REASON_RU,
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(_resource_envelope(''))

    assert _reason(repaired['patches'][0]) == LONE_WEB_RESOURCE_REASON_RU


def test_the_specialists_own_note_is_still_preferred():
    """It names the publication. The default cannot."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(
        _resource_envelope('Пресс-релиз 2007 года.')
    )

    assert _reason(repaired['patches'][0]) == 'Пресс-релиз 2007 года.'


# --- the absent-spatial-layer rule -----------------------------------------

def test_a_spatial_refusal_states_a_reason_when_the_note_is_empty():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        ABSENT_SPATIAL_LAYER_REASON_RU,
        refuse_unanswerable_spatial_rows,
    )

    repaired, _ = refuse_unanswerable_spatial_rows(_spatial_envelope(''), _UNANSWERABLE)

    assert _reason(repaired['patches'][0]) == ABSENT_SPATIAL_LAYER_REASON_RU


def test_the_spatial_note_is_still_preferred():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    repaired, _ = refuse_unanswerable_spatial_rows(
        _spatial_envelope('Из приложения к лицензии.'), _UNANSWERABLE
    )

    assert _reason(repaired['patches'][0]) == 'Из приложения к лицензии.'


# --- the out-of-radius rule, which wrote no such key -----------------------

def test_the_out_of_radius_refusal_states_a_reason_beside_its_rule():
    """It kept its sentence in `selection_trace`, which describes what was done
    with the cell. A refused-candidate line needs the other sentence: why the
    value was declined."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        OUT_OF_RADIUS_RULE,
        refuse_out_of_radius_infrastructure,
    )

    repaired, _ = refuse_out_of_radius_infrastructure(
        _radius_envelope('посёлок Омсукчан, 130 км')
    )
    candidate = repaired['patches'][0]['source_locator']['candidates'][0]

    assert candidate['locator']['rule'] == OUT_OF_RADIUS_RULE
    reason = candidate['locator']['stated_reason']
    assert '130' in reason
    assert '50' in reason
    assert not MACHINE_TOKEN.search(reason)


@pytest.mark.parametrize('value', (
    # An English GIS layer or feature name in the value, which is where this
    # rule fires: r084/r085 are infrastructure rows measured against project
    # layers, and those layers are commonly named in English snake_case.
    'access_road Kolyma, 130 км',
    'power_line 220 кВ, 130 км',
    'объект (rail_station), 130 км',
))
def test_the_out_of_radius_reason_survives_whatever_the_value_says(value):
    """The first version spliced `patch['value']` into the sentence.

    `gis_service` drops a `stated_reason` carrying a bare identifier WHOLE
    rather than cutting the identifier out of it, so one English layer name in
    a specialist's value would have taken the rule's only sentence with it --
    and the card would have printed «формулировка правила не задана» for the
    one rule this whole change is named after. A rule's default has to be
    available in every case, so it is built from two numbers and no quoted
    text. The value is still shown, as the refused candidate.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    repaired, _ = refuse_out_of_radius_infrastructure(_radius_envelope(value))
    candidate = repaired['patches'][0]['source_locator']['candidates'][0]

    assert not MACHINE_TOKEN.search(candidate['locator']['stated_reason'])
    # Not lost: the value a reader needs is the candidate's, beside the reason.
    assert candidate['value'] == value


# --- and the sweep over all of them ----------------------------------------

@pytest.mark.parametrize('name', (
    'LONE_WEB_RESOURCE_REASON_RU',
    'ABSENT_SPATIAL_LAYER_REASON_RU',
    'UNIT_CONTRADICTS_SOURCE_RU',
    'OUT_OF_RADIUS_REASON_RU',
    'POLICY_EXCLUSION_NOTE_RU',
    'NON_NUMERIC_IN_NUMERIC_ROW_RU',
))
def test_every_default_sentence_would_survive_the_renderers_gate(name):
    """`gis_service.reader_text.reader_facing` drops a sentence carrying a bare
    identifier rather than cutting the identifier out of it, so a default that
    names a key renders as a gap -- the very thing it was written to close."""
    from open_webui.services.artifacts.geotizer import owner_envelope

    sentence = getattr(owner_envelope, name)
    # Two of these are templates, and every slot in them takes a value this
    # code produces -- a unit name off `CANONICAL_UNIT_SPELLINGS`, or a
    # distance. None takes free text, which is the property being asserted:
    # a slot that took a specialist's sentence could carry an identifier into
    # a message whose whole purpose is not to.
    filled = sentence.format(
        source='м', stated='км', stated_km=130.0, limit_km=50.0,
    ) if '{' in sentence else sentence

    assert not MACHINE_TOKEN.search(filled)


def test_the_wrong_kind_sentences_would_survive_it_too():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        WRONG_KIND_REASON_RU,
        WRONG_KIND_RULES,
    )

    assert set(WRONG_KIND_REASON_RU) == set(WRONG_KIND_RULES)
    for sentence in WRONG_KIND_REASON_RU.values():
        assert not MACHINE_TOKEN.search(sentence)
