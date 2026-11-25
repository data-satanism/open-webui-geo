"""Tests for `services/ontology/geomas.py`: the copied packages, the linker, field annotation and query expansion."""

from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path

import pytest

from open_webui.services.geotizer.errors import GeotizerOrchestrationError
from open_webui.services.ontology import geomas
from open_webui.services.ontology.geomas import (
    ASSETS,
    annotate_batch,
    expand_queries,
    linked_entities,
    ontology_record,
)

CASES = Path(__file__).resolve().parent / 'fixtures/geomas_ontology/question-linking-cases.v0.2.json'
MAPPING = (
    Path(__file__).resolve().parents[1]
    / 'open_webui/services/artifacts/geotizer/assets/cpr_to_geotizer_mapping.v1.json'
)
WIDENED_C2 = 'запасы C2 по Лекыну Прогнозные ресурсы ресурсы p1 p2 p3 Оценка ресурсов запасы А В С1 С2'


def _all_fields() -> list[dict]:
    keys = [field['field_key'] for field in json.loads(MAPPING.read_text(encoding='utf-8'))['fields']]
    return annotate_batch({'fields': [{'field_key': key} for key in keys]})['fields']


def test_the_packages_load_and_match_their_record():
    provenance = json.loads((ASSETS / 'provenance.json').read_text(encoding='utf-8'))
    ontology = geomas._ontology()

    assert len(ontology['entities']) == 864
    assert len(ontology['fields']) == 351
    assert len(ontology['rows']) == 108
    assert [(p['id'], p['version']) for p in provenance['packages']] == [
        ('geomas-core', '1.2.0'),
        ('geoteaser', '1.0.0'),
    ]


@pytest.mark.parametrize(
    'relative',
    ['geoteaser/1.0.0/fields.json', 'geomas-core/1.2.0/codelists/yes_no.json', 'geomas-core/1.2.0/manifest.json'],
)
def test_one_changed_byte_stops_the_load_and_names_the_file(tmp_path, relative):
    copy = tmp_path / 'assets'
    shutil.copytree(ASSETS, copy)
    target = copy / relative
    raw = bytearray(target.read_bytes())
    raw[-2] = ord(' ') if raw[-2] != ord(' ') else ord('\t')
    target.write_bytes(bytes(raw))

    with pytest.raises(GeotizerOrchestrationError, match=relative):
        geomas._load(str(copy))


def test_a_count_that_differs_from_the_record_stops_the_load(tmp_path):
    copy = tmp_path / 'assets'
    shutil.copytree(ASSETS, copy)
    provenance = json.loads((copy / 'provenance.json').read_text(encoding='utf-8'))
    provenance['packages'][0]['counts']['entities'] = 863
    (copy / 'provenance.json').write_text(json.dumps(provenance), encoding='utf-8')

    with pytest.raises(GeotizerOrchestrationError, match='entities is 864'):
        geomas._load(str(copy))


def test_linking_reads_no_window_longer_than_the_longest_phrase(monkeypatch):
    ontology = geomas._ontology()
    phrases = ontology['phrases']
    looked_up = []

    class Recording(dict):
        def get(self, key, default=None):
            looked_up.append(len(key))
            return phrases.get(key, default)

    monkeypatch.setitem(ontology, 'phrases', Recording())
    query = ' '.join(['запасы C2 по Лекыну'] * 500)

    assert 'D05' in geomas.linked_entities(query)
    assert max(looked_up) == ontology['longest_phrase'] < 2000


def _broken_assets(tmp_path, monkeypatch, damage):
    copy = tmp_path / 'assets'
    shutil.copytree(ASSETS, copy)
    damage(copy)
    monkeypatch.setattr(geomas, 'ASSETS', copy)


def _drop_packages(copy):
    provenance = json.loads((copy / 'provenance.json').read_text(encoding='utf-8'))
    del provenance['packages']
    (copy / 'provenance.json').write_text(json.dumps(provenance), encoding='utf-8')


@pytest.mark.parametrize(
    'damage',
    [
        lambda copy: (copy / 'geoteaser/1.0.0/fields.json').write_bytes(b'[]'),
        lambda copy: (copy / 'geoteaser/1.0.0/rows.json').unlink(),
        _drop_packages,
        lambda copy: (copy / 'provenance.json').write_text('[]', encoding='utf-8'),
    ],
    ids=['changed', 'missing', 'no-packages', 'not-a-mapping'],
)
def test_chat_retrieval_keeps_its_queries_when_the_assets_do_not_load(tmp_path, monkeypatch, damage):
    _broken_assets(tmp_path, monkeypatch, damage)

    assert geomas.expand_queries(['Магнитометрия на участке']) == ['Магнитометрия на участке']


def test_the_fill_stops_when_the_assets_fail_verification(tmp_path, monkeypatch):
    _broken_assets(tmp_path, monkeypatch, lambda copy: (copy / 'geoteaser/1.0.0/fields.json').write_bytes(b'[]'))

    with pytest.raises(GeotizerOrchestrationError):
        geomas.annotate_batch({'fields': []})


def test_the_template_keys_are_the_card_keys():
    mapping = {field['field_key'] for field in json.loads(MAPPING.read_text(encoding='utf-8'))['fields']}

    assert set(geomas._ontology()['fields']) == mapping


def test_every_linking_case_reaches_its_ids_and_none_of_its_gaps():
    document = json.loads(CASES.read_text(encoding='utf-8'))
    assert document['package'] == {'package_id': 'geomas-core', 'version': '1.2.0'}
    assert len(document['cases']) == 55

    failures = []
    for case in document['cases']:
        found = linked_entities(case['text_ru'])
        missing = set(case['expected_ids']) - found
        closed = {gap['id'] for gap in case.get('gaps', [])} & found
        if missing or closed:
            failures.append((case['id'], sorted(missing), sorted(closed)))

    assert failures == []


def test_the_concept_group_head_is_reached_through_its_member(monkeypatch):
    cases = {case['id']: case for case in json.loads(CASES.read_text(encoding='utf-8'))['cases']}
    monkeypatch.setitem(geomas._ontology(), 'heads', {})

    for case_id in ('PLAN-C2-LATIN', 'PLAN-C2-CYRILLIC'):
        assert not set(cases[case_id]['expected_ids']) <= linked_entities(cases[case_id]['text_ru'])


def test_field_terms_follow_the_row_entities():
    fields = _all_fields()
    counts = [len(field['ontology']['terms']) for field in fields]
    by_key = {field['field_key']: field['ontology'] for field in fields}

    assert len(fields) == 351
    assert counts.count(0) == 30
    assert statistics.median(counts) == 4
    assert counts.count(12) == 48
    assert by_key['geotizer_object.v1.r044.a01'] == {
        'terms': [
            'Прогнозные ресурсы',
            'ресурсы p1 p2 p3',
            'Оценка ресурсов',
            'Площадная продуктивность P',
            'Удельная продуктивность G; потенциал Q',
            'запасы А В С1 С2',
        ],
        'value_type': 'number',
        'codelist': None,
    }
    assert by_key['geotizer_object.v1.r013.a01']['value_type'] == 'enum'
    assert by_key['geotizer_object.v1.r013.a01']['codelist'] == ['да', 'нет']


def test_a_field_outside_the_template_is_left_as_it_was():
    batch = {'batch_id': 'B', 'fields': [{'field_key': 'f1', 'row_id': 1}]}

    assert annotate_batch(batch) == batch


@pytest.mark.parametrize(
    ('query', 'reached', 'widened'),
    [
        ('запасы C2 по Лекыну', {'D05', 'core-profile:ResourceEstimate'}, WIDENED_C2),
        (
            'Магнитометрия на участке',
            {'GP-013', 'GP-071'},
            'Магнитометрия на участке Магниторазведка Магнитные данные',
        ),
    ],
)
def test_a_query_that_names_a_concept_gets_one_widened_query(query, reached, widened):
    assert reached <= linked_entities(query)
    assert expand_queries([query]) == [query, widened]


def test_a_query_that_names_nothing_is_not_widened():
    assert linked_entities('Какая стадия работ?') == set()
    assert expand_queries(['Какая стадия работ?']) == ['Какая стадия работ?']
    assert expand_queries(['Какая стадия работ?', 'запасы C2 по Лекыну']) == [
        'Какая стадия работ?',
        'запасы C2 по Лекыну',
        WIDENED_C2,
    ]


def test_the_record_names_both_packages_and_the_source():
    record = ontology_record()

    assert record['packages'] == [
        {
            'id': 'geomas-core',
            'version': '1.2.0',
            'manifest_digest': 'da6162bbbe9aa45f33bdeed75fbbe2be69134dd821b17afe117fc02bfbc8833c',
        },
        {
            'id': 'geoteaser',
            'version': '1.0.0',
            'manifest_digest': '8316fdbe318d72d64dcd3b1ad07f737e08d6a0e5723b478b7f9ac23a54a536d5',
        },
    ]
    assert record['source_commit'] == '7886511d0e18b13285e2f8691245ad41024eee96'
    assert record['mindmap_sha256'] == '6a5dd06a73478b8920b406c2f2a2f5fa4e79e573ad8a35dd17f4acf162254df0'
