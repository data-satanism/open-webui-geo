"""Every rule that refuses a value states a reader-facing sentence, preferring
the specialist's own note where there is one."""

from __future__ import annotations

import re

import pytest


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


def test_a_lone_web_refusal_states_a_reason_when_the_note_is_empty():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        LONE_WEB_RESOURCE_REASON_RU,
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(_resource_envelope(''))

    assert _reason(repaired['patches'][0]) == LONE_WEB_RESOURCE_REASON_RU


def test_the_specialists_own_note_is_still_preferred():
    """A non-empty specialist note is kept as the lone-web refusal's reason."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(
        _resource_envelope('Пресс-релиз 2007 года.')
    )

    assert _reason(repaired['patches'][0]) == 'Пресс-релиз 2007 года.'


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


def test_the_out_of_radius_refusal_states_a_reason_beside_its_rule():
    """The out-of-radius refusal writes a reader-facing reason naming both
    distances beside its rule on the candidate."""
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
    'access_road Kolyma, 130 км',
    'power_line 220 кВ, 130 км',
    'объект (rail_station), 130 км',
))
def test_the_out_of_radius_reason_survives_whatever_the_value_says(value):
    """The out-of-radius reason carries no machine token whatever the value
    holds, and the value stays on the candidate."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    repaired, _ = refuse_out_of_radius_infrastructure(_radius_envelope(value))
    candidate = repaired['patches'][0]['source_locator']['candidates'][0]

    assert not MACHINE_TOKEN.search(candidate['locator']['stated_reason'])
    assert candidate['value'] == value


@pytest.mark.parametrize('name', (
    'LONE_WEB_RESOURCE_REASON_RU',
    'ABSENT_SPATIAL_LAYER_REASON_RU',
    'UNIT_CONTRADICTS_SOURCE_RU',
    'OUT_OF_RADIUS_REASON_RU',
    'POLICY_EXCLUSION_NOTE_RU',
    'NON_NUMERIC_IN_NUMERIC_ROW_RU',
))
def test_every_default_sentence_would_survive_the_renderers_gate(name):
    """Each default refusal sentence, with its slots filled, carries no machine
    token."""
    from open_webui.services.artifacts.geotizer import owner_envelope

    sentence = getattr(owner_envelope, name)
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
