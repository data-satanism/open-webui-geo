"""Ontology induction through `induce_ontology_vocabulary`, asserted on the artefacts read back from storage."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import re
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import open_webui.storage.provider as storage_provider
import open_webui.tools.ontology_induction as shell
import pytest
from open_webui.retrieval.lexical import normalize_geological_text
from open_webui.services.ontology_induction import seed as seed_module
from open_webui.services.ontology_induction.errors import EvidenceOutsideDocuments
from open_webui.services.ontology_induction.proposal import assemble_proposal, merge_items
from open_webui.services.ontology_induction.seed import build_seed_index, load_pinned_seed

ASSETS = Path(seed_module.__file__).resolve().parent / 'assets'
SEED = json.loads((ASSETS / 'ontology-induction-seed.v0.1.json').read_text(encoding='utf-8'))
SCHEMA = json.loads((ASSETS / 'ontology-induction-proposal.schema.json').read_text(encoding='utf-8'))
KIND_BY_ID = {term['term_id']: term['kind'] for term in SEED['terms']}
JSON_FILE = re.compile(r'JSON, файл `([^`]+)`')
FINISHED = re.compile(r'^- Завершён: (.+)$', re.MULTILINE)


def reply(items):
    return {'choices': [{'message': {'content': json.dumps({'items': items}, ensure_ascii=False)}}]}


def item(surface_form, excerpt, kind='class', **optional):
    return {'surface_form': surface_form, 'excerpt': excerpt, 'proposed_kind': kind, **optional}


class _Files:
    def __init__(self):
        self.records = {}
        self.order = []

    def add(self, record):
        self.records[record.id] = record
        self.order.append(record.id)

    async def get_file_by_id_and_user_id(self, file_id, user_id):
        record = self.records.get(file_id)
        return record if record is not None and record.user_id == user_id else None

    async def update_file_metadata_by_id(self, file_id, meta):
        record = self.records[file_id]
        record.meta = {**record.meta, **meta}
        return record


class _Knowledges:
    def __init__(self, collections):
        self.collections = collections

    async def get_file_metadatas_by_id(self, knowledge_id):
        return [
            SimpleNamespace(id=file_id, hash=None, meta={'name': name})
            for file_id, name in self.collections.get(knowledge_id, ())
        ]


class _VectorClient:
    def __init__(self, chunks):
        self.chunks = chunks

    async def query(self, collection_name, filter, limit=None):
        stored = self.chunks.get((collection_name, filter['file_id']))
        if isinstance(stored, Exception):
            raise stored
        if stored is None:
            return None
        return SimpleNamespace(
            ids=[[chunk_id for chunk_id, _, _ in stored]],
            documents=[[text for _, text, _ in stored]],
            metadatas=[[metadata for _, _, metadata in stored]],
        )


class Harness:
    """Fakes for every OWUI dependency of the built-in; files land in a temp upload directory."""

    def __init__(self, monkeypatch, tmp_path, collections, chunks, replies=None, withheld=()):
        self.upload_dir = tmp_path / 'uploads'
        self.upload_dir.mkdir(parents=True)
        self.collections = collections
        self.replies = replies or {}
        self.withheld = set(withheld)
        self.calls = []
        self.files = _Files()
        self.user = SimpleNamespace(id='user-1', role='user', email='user@example.test', name='User')
        self.request = SimpleNamespace(
            app=SimpleNamespace(url_path_for=lambda name, id: f'/api/v1/files/{id}/content'),
            state=SimpleNamespace(),
        )
        monkeypatch.setattr(storage_provider, 'UPLOAD_DIR', str(self.upload_dir))
        monkeypatch.setattr(shell, 'Files', self.files)
        monkeypatch.setattr(shell, 'Knowledges', _Knowledges(collections))
        monkeypatch.setattr(shell, 'ASYNC_VECTOR_DB_CLIENT', _VectorClient(chunks))
        monkeypatch.setattr(shell, 'Users', SimpleNamespace(get_user_by_id=self._user))
        monkeypatch.setattr(shell, 'filter_accessible_collections', self._filter)
        monkeypatch.setattr(shell, 'generate_chat_completion', self._complete)
        monkeypatch.setattr(shell, 'upload_file_handler', self._upload)

    async def _user(self, user_id):
        return self.user if user_id == self.user.id else None

    async def _filter(self, collection_names, user, access_type='read'):
        return {name for name in collection_names if name not in self.withheld}

    async def _complete(self, request, form_data, user, bypass_filter=False, bypass_system_prompt=False):
        self.calls.append({'form_data': form_data, 'bypass_system_prompt': bypass_system_prompt})
        answer = self.replies.get(form_data['messages'][1]['content'], [])
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, dict) else reply(answer)

    async def _upload(self, request, file, metadata, process, user):
        assert process is False
        file_id = uuid.uuid4().hex
        path = self.upload_dir / f'{file_id}_{file.filename}'
        path.write_bytes(file.file.read())
        self.files.add(
            SimpleNamespace(
                id=file_id, user_id=user.id, path=str(path), meta={'name': file.filename, 'data': metadata or {}}
            )
        )
        return self.files.records[file_id]

    def own(self, name, content, data=None):
        file_id = uuid.uuid4().hex
        path = self.upload_dir / f'{file_id}_{name}'
        path.write_bytes(content)
        self.files.add(
            SimpleNamespace(id=file_id, user_id=self.user.id, path=str(path), meta={'name': name, 'data': data or {}})
        )
        return file_id

    async def run(self, **kwargs):
        defaults = {
            'model_id': 'induction-model',
            'min_chunk_chars': 0,
            '__request__': self.request,
            '__user__': {'id': self.user.id},
            '__files__': [{'type': 'collection', 'id': kid} for kid in self.collections],
        }
        return await shell.induce_ontology_vocabulary(**{**defaults, **kwargs})

    def stored(self, suffix):
        return [
            Path(self.files.records[file_id].path).read_bytes()
            for file_id in self.files.order
            if self.files.records[file_id].meta['name'].endswith(suffix)
        ]

    def proposals(self):
        found = []
        for file_id in self.files.order:
            record = self.files.records[file_id]
            name = record.meta['name']
            if name.endswith('.json') and not name.endswith('.checkpoint.json'):
                proposal = json.loads(Path(record.path).read_bytes())
                jsonschema.Draft202012Validator(SCHEMA).validate(proposal)
                found.append(proposal)
        return found

    def proposal(self):
        proposals = self.proposals()
        assert len(proposals) == 1
        return proposals[0]

    def sampled_texts(self):
        return [call['form_data']['messages'][1]['content'] for call in self.calls]


def by_form(proposal):
    return {entry['normalized_form']: entry for entry in proposal['items']}


def outcomes_of(proposal, file_id):
    return next(d for d in proposal['documents'] if d['file_id'] == file_id)['outcomes']


@pytest.mark.asyncio
async def test_evidence_carries_only_the_locator_keys_its_chunk_has(monkeypatch, tmp_path):
    legacy = {'file_id': 'f-legacy', 'name': 'a.pdf', 'source': 'a.pdf', 'start_index': 12, 'Header 1': 'Глава'}
    parent_child = {
        'file_id': 'f-pc',
        'document_id': 'doc-1',
        'document_version': 'v3',
        'page': 2,
        'source_page_index': 2,
        'section_path': 'Глава 1 > Раздел 2',
        'parent_chunk_id': 'parent-1',
        'child_chunk_id': 'child-1',
        'start_index': 0,
        'end_index': 40,
    }
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f-legacy', 'a.pdf'), ('f-pc', 'b.pdf')]},
        {
            ('kb', 'f-legacy'): [('c1', 'Здесь описана рудная зона участка.', legacy)],
            ('kb', 'f-pc'): [('c2', 'Выделена рудная залежь на глубине.', parent_child)],
        },
        {
            'Здесь описана рудная зона участка.': [item('рудная зона', 'описана рудная зона участка')],
            'Выделена рудная залежь на глубине.': [item('рудная залежь', 'Выделена рудная залежь')],
        },
    )

    await harness.run()

    items = by_form(harness.proposal())
    assert set(items['рудная зона']['evidence'][0]) == {
        'file_id',
        'chunk_id',
        'excerpt',
        'excerpt_sha256',
        'start_index',
    }
    assert items['рудная залежь']['evidence'][0] == {
        'file_id': 'f-pc',
        'chunk_id': 'c2',
        'excerpt': 'Выделена рудная залежь',
        'excerpt_sha256': items['рудная залежь']['evidence'][0]['excerpt_sha256'],
        'start_index': 0,
        'document_id': 'doc-1',
        'document_version': 'v3',
        'section_path': 'Глава 1 > Раздел 2',
        'child_chunk_id': 'child-1',
    }


@pytest.mark.asyncio
async def test_page_is_taken_only_from_a_numeric_page_label(monkeypatch, tmp_path):
    texts = ['Первая страница: штольня.', 'Пятая страница: канава.', 'Четвёртая римская: шурф.']
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {
            ('kb', 'f1'): [
                ('c1', texts[0], {'page': 0, 'page_label': 1}),
                ('c2', texts[1], {'page': 4}),
                ('c3', texts[2], {'page_label': 'iv'}),
            ]
        },
        {
            texts[0]: [item('штольня', 'штольня')],
            texts[1]: [item('канава', 'канава')],
            texts[2]: [item('шурф', 'шурф')],
        },
    )

    await harness.run()

    items = by_form(harness.proposal())
    assert items['штольня']['evidence'][0]['page'] == 1
    assert 'page' not in items['канава']['evidence'][0]
    assert 'page' not in items['шурф']['evidence'][0]


@pytest.mark.asyncio
async def test_resources_links_every_field_it_names(monkeypatch, tmp_path):
    text = 'Подсчитаны ресурсы золота категории C2.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {text: [item('ресурсы', 'Подсчитаны ресурсы золота', kind='attribute', proposed_class='core:class:Deposit')]},
    )

    await harness.run()

    linked = by_form(harness.proposal())['ресурсы']
    expected = sorted(
        term['term_id']
        for term in SEED['terms']
        if any(normalize_geological_text(label) == 'ресурсы' for label in term.get('labels_ru', ()))
    )
    assert linked['seed_term_ids'] == expected
    assert len(expected) == 79
    assert {KIND_BY_ID[term_id] for term_id in expected} == {'field'}
    assert not {'status', 'proposed_kind', 'proposed_class'} & set(linked)


@pytest.mark.asyncio
async def test_electrical_survey_lists_the_layer_role_and_the_six_fields_that_share_its_label(monkeypatch, tmp_path):
    text = 'Электроразведка выполнена по сети профилей.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {text: [item('Электроразведка', 'Электроразведка выполнена', kind='layer_role')]},
    )

    await harness.run()

    assert by_form(harness.proposal())['электроразведка']['seed_term_ids'] == [
        *(f'field:geotizer_object.v1.r041.a0{n}' for n in range(1, 7)),
        'layer_role:electrical_survey',
    ]


@pytest.mark.asyncio
async def test_an_unknown_seed_term_or_class_is_counted_and_dropped(monkeypatch, tmp_path):
    text = 'Рудная зона прослежена канавами и скважинами.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {
            text: [
                item(
                    'Рудная зона', 'Рудная зона прослежена', suggested_seed_term_id='field:geotizer_object.v1.r999.a01'
                ),
                item('канавами', 'прослежена канавами', proposed_class='core:class:NoSuchClass'),
                item('скважинами', 'и скважинами', proposed_class='layer_role:electrical_survey'),
            ]
        },
    )

    await harness.run()

    proposal = harness.proposal()
    assert outcomes_of(proposal, 'f1')['unknown_seed_term'] == 3
    assert outcomes_of(proposal, 'f1')['accepted'] == 0
    assert proposal['items'] == []


@pytest.mark.asyncio
async def test_an_excerpt_the_chunk_does_not_contain_is_counted_and_dropped(monkeypatch, tmp_path):
    text = 'Рудная   зона\nпрослежена канавами.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {
            text: [
                item('Рудная зона', 'Рудная зона прослежена'),
                item('штольня', 'пройдена штольня'),
            ]
        },
    )

    await harness.run()

    proposal = harness.proposal()
    assert outcomes_of(proposal, 'f1')['excerpt_not_in_chunk'] == 1
    assert outcomes_of(proposal, 'f1')['accepted'] == 1
    assert set(by_form(proposal)) == {'рудная зона'}


@pytest.mark.asyncio
async def test_a_term_is_matched_as_whole_tokens_never_inside_a_longer_word(monkeypatch, tmp_path):
    text = 'Участок перспективен на нерудное золото и россыпи.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {text: [item('рудное золото', 'перспективен на нерудное золото')]},
    )

    await harness.run()

    proposal = harness.proposal()
    assert outcomes_of(proposal, 'f1')['term_not_in_excerpt'] == 1
    assert proposal['items'] == []


@pytest.mark.asyncio
async def test_evidence_outside_documents_raises_before_anything_is_written(monkeypatch, tmp_path):
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): [('c1', 'Штольня.', {})]})
    ghost = {
        'normalized_form': 'штольня',
        'surface_forms': ['штольня'],
        'status': 'new_candidate',
        'proposed_kind': 'class',
        'document_count': 1,
        'occurrence_count': 1,
        'evidence': [{'file_id': 'ghost', 'chunk_id': 'c9', 'excerpt': 'штольня', 'excerpt_sha256': '0' * 64}],
    }
    monkeypatch.setattr(shell, 'merge_items', lambda *args, **kwargs: [ghost])

    result = await harness.run()

    assert 'evidence_file_not_in_documents' in result
    assert list(harness.upload_dir.iterdir()) == []
    assert harness.calls == []


def test_the_assembly_invariant_is_a_named_error():
    index = build_seed_index(SEED['terms'], normalize_geological_text)
    ghost = {'normalized_form': 'x', 'evidence': [{'file_id': 'ghost'}]}

    with pytest.raises(EvidenceOutsideDocuments, match='ghost'):
        assemble_proposal(header={}, documents=[{'file_id': 'f1'}], items=[ghost], index=index)


@pytest.mark.asyncio
async def test_every_call_of_a_run_carries_the_same_seed_block_and_no_field_relation_or_attribute(
    monkeypatch, tmp_path
):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый фрагмент.', {})], ('kb', 'f2'): [('c2', 'Второй фрагмент.', {})]},
    )

    await harness.run()

    assert len(harness.calls) == 2
    systems = [call['form_data']['messages'][0]['content'] for call in harness.calls]
    assert systems[0].encode('utf-8') == systems[1].encode('utf-8')
    shown = set(re.findall(r'"term_id":"([^"]+)"', systems[0]))
    assert {KIND_BY_ID[term_id] for term_id in shown} == {'class', 'layer_role', 'entity_scope', 'semantic_family'}
    hidden = [t['term_id'] for t in SEED['terms'] if t['kind'] in ('field', 'relation', 'attribute')]
    assert not any(f'"{term_id}"' in systems[0] for term_id in hidden)
    for call in harness.calls:
        form_data = call['form_data']
        assert [m['role'] for m in form_data['messages']] == ['system', 'user']
        assert form_data['temperature'] == 0
        assert form_data['response_format']['type'] == 'json_schema'
        assert form_data['chat_template_kwargs'] == {'enable_thinking': False}
        assert call['bypass_system_prompt'] is True


@pytest.mark.asyncio
async def test_no_attached_collection_is_refused_without_a_model_call(monkeypatch, tmp_path):
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): [('c1', 'Текст.', {})]})

    result = await harness.run(__files__=[])

    assert 'kb_scope_unconfigured' in result and 'unconfigured' in result
    assert harness.calls == []
    assert list(harness.upload_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_an_attachment_that_is_not_a_collection_is_refused(monkeypatch, tmp_path):
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): [('c1', 'Текст.', {})]})

    result = await harness.run(__files__=[{'type': 'collection', 'id': 'kb'}, {'type': 'file', 'id': 'f1'}])

    assert 'unsupported_attachment' in result
    assert harness.calls == []


@pytest.mark.asyncio
async def test_a_withheld_collection_refuses_the_whole_run(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb-open': [('f1', 'a.pdf')], 'kb-closed': [('f2', 'b.pdf')]},
        {('kb-open', 'f1'): [('c1', 'Текст.', {})], ('kb-closed', 'f2'): [('c2', 'Тайна.', {})]},
        withheld={'kb-closed'},
    )

    result = await harness.run()

    assert 'collection_not_accessible' in result and 'kb-closed' in result
    assert harness.calls == []
    assert list(harness.upload_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_a_file_without_stored_chunks_is_reported_and_its_text_is_not_read(monkeypatch, tmp_path):
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {})

    await harness.run()

    document = harness.proposal()['documents'][0]
    assert document['status'] == 'no_stored_chunks'
    assert document['chunks_sampled'] == 0
    assert harness.calls == []


@pytest.mark.asyncio
async def test_a_reasoning_only_reply_and_an_unparseable_reply_are_counted_once_each(monkeypatch, tmp_path):
    reasoning_only = {'choices': [{'message': {'content': '', 'reasoning_content': 'Думаю о терминах.'}}]}
    fenced = {'choices': [{'message': {'content': '```json\n{"items": []}\n```'}}]}
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый.', {}), ('c2', 'Второй.', {})]},
        {'Первый.': reasoning_only, 'Второй.': fenced},
    )

    await harness.run()

    outcomes = outcomes_of(harness.proposal(), 'f1')
    assert outcomes['empty_completion'] == 1
    assert outcomes['unparseable'] == 1
    assert len(harness.calls) == 2


@pytest.mark.asyncio
async def test_the_same_inputs_give_the_same_sample_and_the_same_proposal(monkeypatch, tmp_path):
    texts = [f'Фрагмент {n}: рудная зона номер {n}.' for n in range(8)]
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [(f'c{n}', text, {'page_label': n + 1}) for n, text in enumerate(texts)]},
        {text: [item('рудная зона', 'рудная зона')] for text in texts},
    )

    await harness.run()
    first_sample = harness.sampled_texts()
    await harness.run()
    second_sample = harness.sampled_texts()[len(first_sample) :]

    assert first_sample == second_sample and len(first_sample) == 3
    first, second = harness.proposals()
    volatile = ('run_id', 'started_at', 'finished_at')
    assert {k: v for k, v in first.items() if k not in volatile} == {
        k: v for k, v in second.items() if k not in volatile
    }


@pytest.mark.asyncio
async def test_a_resumed_run_calls_the_model_only_for_documents_not_complete(monkeypatch, tmp_path):
    replies = {
        'Первый документ: штольня.': [item('штольня', 'штольня')],
        'Второй документ: штольня и канава.': [item('штольня', 'штольня'), item('канава', 'канава')],
    }
    chunks = {
        ('kb', 'f1'): [('c1', 'Первый документ: штольня.', {})],
        ('kb', 'f2'): [('c2', 'Второй документ: штольня и канава.', {})],
    }
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]}, chunks, replies)

    first = await harness.run(max_documents=1)
    interrupted = harness.proposal()
    assert [d['status'] for d in interrupted['documents']] == ['complete', 'pending']
    assert 'finished_at' not in interrupted
    file_id = JSON_FILE.search(first).group(1)
    harness.calls.clear()

    second = await harness.run(resume_file_id=file_id)

    assert JSON_FILE.search(second).group(1) == file_id
    assert harness.sampled_texts() == ['Второй документ: штольня и канава.']
    resumed = harness.proposal()
    assert resumed['run_id'] == interrupted['run_id']
    assert [d['status'] for d in resumed['documents']] == ['complete', 'complete']
    assert 'finished_at' in resumed
    assert by_form(resumed)['штольня']['document_count'] == 2

    fresh = Harness(monkeypatch, tmp_path / 'fresh', {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]}, chunks, replies)
    await fresh.run()
    assert fresh.proposal()['items'] == resumed['items']


@pytest.mark.asyncio
async def test_a_resume_with_other_parameters_is_refused_without_a_model_call(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', 'Один.', {})], ('kb', 'f2'): [('c2', 'Два.', {})]},
    )
    first = await harness.run(max_documents=1)
    harness.calls.clear()

    result = await harness.run(resume_file_id=JSON_FILE.search(first).group(1), chunks_per_document=4)

    assert 'resume_mismatch' in result and 'parameters' in result
    assert harness.calls == []


@pytest.mark.asyncio
async def test_an_altered_seed_is_refused_at_load(monkeypatch, tmp_path):
    altered = tmp_path / 'assets'
    shutil.copytree(ASSETS, altered)
    seed_file = altered / 'ontology-induction-seed.v0.1.json'
    raw = seed_file.read_bytes()
    assert b'Digest binding' in raw
    seed_file.write_bytes(raw.replace(b'Digest binding', b'digest binding', 1))
    monkeypatch.setattr(seed_module, 'ASSETS', altered)
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): [('c1', 'Текст.', {})]})

    result = await harness.run()

    assert 'pinned_asset_mismatch' in result and 'ontology-induction-seed.v0.1.json' in result
    assert harness.calls == []


def test_the_pinned_assets_load_and_carry_the_pinned_digests():
    seed = load_pinned_seed()

    assert seed.sha256 == '6a8f917850804470146a1234d5a0858632dd38df4b5ee43804885152387e62c4'
    assert len(seed.terms) == 587
    assert seed.proposal_schema == SCHEMA


def test_a_merged_new_candidate_takes_the_most_frequent_value_and_the_smaller_on_a_tie():
    index = build_seed_index(SEED['terms'], normalize_geological_text)

    def occurrence(rank, kind, proposed_class=None):
        found = {
            'file_id': 'f1',
            'chunk_id': f'c{rank}',
            'chunk_rank': rank,
            'item_rank': 0,
            'surface_form': 'Рудная зона',
            'excerpt': f'Рудная зона {rank}',
            'proposed_kind': kind,
            'locator': {},
        }
        if proposed_class:
            found['proposed_class'] = proposed_class
        return found

    occurrences = [
        occurrence(0, 'relation', 'core:class:GeoObject'),
        occurrence(1, 'class', 'core:class:Deposit'),
        occurrence(2, 'class'),
    ]
    [merged] = merge_items({'f1': occurrences}, ['f1'], index, normalize_geological_text, 2)

    assert merged['proposed_kind'] == 'class'
    assert merged['proposed_class'] == 'core:class:Deposit'
    assert merged['occurrence_count'] == 3
    assert [e['chunk_id'] for e in merged['evidence']] == ['c0', 'c1']


@pytest.mark.asyncio
async def test_the_reviewer_markdown_is_russian_and_folds_long_ambiguous_matches(monkeypatch, tmp_path):
    text = 'Подсчитаны ресурсы, выделена рудная зона.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {text: [item('ресурсы', 'Подсчитаны ресурсы'), item('рудная зона', 'выделена рудная зона')]},
    )

    await harness.run()

    [markdown] = harness.stored('.md')
    rendered = markdown.decode('utf-8')
    for heading in (
        '## 1. Совпадения с одним термином затравки',
        '## 2. Неоднозначные совпадения',
        '## 3. Новые кандидаты',
        '## 4. Термины затравки с labels_ru без лексического совпадения',
        '## 5. Термины без labels_ru',
        '## 6. Документы',
    ):
        assert heading in rendered
    assert '| ресурсы | 79 | field ×79 |' in rendered
    assert '… и ещё 69' in rendered
    assert 'Без предложенного термина затравки' in rendered
    assert 'которые нельзя сопоставить лексически: 217.' in rendered


def markdown_section(rendered, number):
    start = rendered.index(f'\n## {number}. ')
    end = rendered.find('\n## ', start + 1)
    return rendered[start : end if end != -1 else len(rendered)]


@pytest.mark.asyncio
async def test_a_complete_document_with_no_chunk_long_enough_is_reported_as_not_read(monkeypatch, tmp_path):
    long_text = 'Рудная зона прослежена канавами на протяжении двух километров по простиранию.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', 'Короткий фрагмент.', {})], ('kb', 'f2'): [('c2', long_text, {})]},
        {long_text: [item('рудная зона', 'Рудная зона прослежена')]},
    )

    result = await harness.run(min_chunk_chars=50)

    documents = {d['file_id']: d for d in harness.proposal()['documents']}
    assert documents['f1']['status'] == 'complete'
    assert documents['f1']['chunks_sampled'] == 0
    assert documents['f2']['chunks_sampled'] == 1
    [markdown] = harness.stored('.md')
    rendered = markdown.decode('utf-8')
    header = rendered[: rendered.index('\n## 1. ')]
    assert (
        '- Документов complete, из которых не прочитан ни один фрагмент, потому что ни один не достиг '
        'min_chunk_chars = 50: 1\n' in header
    )
    assert '- Фрагментов в выборке, сумма chunks_sampled: 1; не более chunks_per_document = 3 на документ\n' in header
    assert '| `a.pdf` | complete | 0 | 0 | 0 | 0 | 0 | 0 |' in markdown_section(rendered, 6)
    assert (
        'Документы: complete 2, no_stored_chunks 0, failed 0, pending 0; '
        'из них complete, где ни один фрагмент не достиг min_chunk_chars, 1.' in result
    )


@pytest.mark.asyncio
async def test_the_reviewer_markdown_header_totals_items_and_calls_without_a_reply(monkeypatch, tmp_path):
    text = 'Пройдена штольня, выделена рудная зона.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', text, {})], ('kb', 'f2'): [('c2', 'Второй документ.', {})]},
        {
            text: [
                item('штольня', 'Пройдена штольня'),
                item('канава', 'Пройдена канава'),
                item('рудная зона', 'выделена рудная зона', suggested_seed_term_id='layer_role:no_such_role'),
            ],
            'Второй документ.': {'choices': [{'message': {'content': 'не JSON'}}]},
        },
    )

    await harness.run()

    [markdown] = harness.stored('.md')
    rendered = markdown.decode('utf-8')
    header = rendered[: rendered.index('\n## 1. ')]
    assert (
        '- Элементы ответов модели: accepted — 1, excerpt_not_in_chunk — 1, term_not_in_excerpt — 0, '
        'unknown_seed_term — 1\n' in header
    )
    assert (
        '- Вызовы модели без ответа: unparseable — 1, schema_violation — 0, empty_completion — 0, timeout — 0\n'
        in header
    )
    rows = markdown_section(rendered, 6)
    assert '| `a.pdf` | complete | 1 | 1 | 1 | 0 | 1 | 0 |' in rows
    assert '| `b.pdf` | complete | 1 | 0 | 0 | 0 | 0 | 1 |' in rows


@pytest.mark.asyncio
async def test_an_unmatched_seed_term_carries_the_count_of_new_candidates_suggesting_it(monkeypatch, tmp_path):
    text = 'Пройдено пять поисковых канав.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {text: [item('канав', 'поисковых канав', kind='layer_role', suggested_seed_term_id='layer_role:trench')]},
    )

    await harness.run()

    proposal = harness.proposal()
    assert by_form(proposal)['канав']['status'] == 'new_candidate'
    assert 'layer_role:trench' in proposal['unseen_seed_term_ids']
    [markdown] = harness.stored('.md')
    section = markdown_section(markdown.decode('utf-8'), 4)
    assert section.startswith('\n## 4. Термины затравки с labels_ru без лексического совпадения\n')
    assert '\n- `layer_role:trench` — новых кандидатов с этим предложением: 1\n' in section
    assert '\n- `layer_role:electrical_survey`\n' in section


@pytest.mark.asyncio
async def test_a_document_name_reaches_the_documents_section_only_inside_one_code_span(monkeypatch, tmp_path):
    name = 'Отчёт | ![x](https://evil.example/p.png) <img src=//evil/x> **жирный**.pdf'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', name)]},
        {('kb', 'f1'): [('c1', 'Текст без терминов.', {})]},
    )

    await harness.run()

    [markdown] = harness.stored('.md')
    section = markdown_section(markdown.decode('utf-8'), 6)
    span = '`Отчёт \\| ![x](https://evil.example/p.png) <img src=//evil/x> **жирный**.pdf`'
    assert f'\n| {span} | complete | 1 | 0 | 0 | 0 | 0 | 0 |\n' in section
    outside = section.replace(span, '')
    assert '![x]' not in outside
    assert '<img' not in outside
    assert '**жирный**' not in outside


def table_cells(row):
    return [cell.strip() for cell in re.split(r'(?<!\\)((?:\\\\)*)\|', row.strip())[::2][1:-1]]


@pytest.mark.parametrize(
    'name',
    [
        'a\\|![x](https://evil.example/p.png).pdf',
        'a\\\\|![x](https://evil.example/p.png).pdf',
        'a\\\\\\|<img src=//evil/x>.pdf',
        'отчёт\\',
    ],
)
@pytest.mark.asyncio
async def test_a_backslash_before_a_pipe_in_a_document_name_does_not_split_its_cell(monkeypatch, tmp_path, name):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', name)]},
        {('kb', 'f1'): [('c1', 'Текст без терминов.', {})]},
    )

    await harness.run()

    [markdown] = harness.stored('.md')
    [row] = [line for line in markdown.decode('utf-8').splitlines() if line.startswith('| `')]
    cells = table_cells(row)
    assert cells[1:] == ['complete', '1', '0', '0', '0', '0', '0']
    assert cells[0].startswith('`') and cells[0].endswith('`')


@pytest.mark.asyncio
async def test_a_timeout_and_a_schema_violation_are_counted_once_per_call(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый.', {}), ('c2', 'Второй.', {}), ('c3', 'Третий: штольня.', {})]},
        {
            'Первый.': TimeoutError(),
            'Второй.': {'choices': [{'message': {'content': '{"items": [{"surface_form": "x"}]}'}}]},
            'Третий: штольня.': [item('штольня', 'штольня')],
        },
    )

    await harness.run()

    proposal = harness.proposal()
    document = proposal['documents'][0]
    assert document['status'] == 'complete'
    assert document['outcomes']['timeout'] == 1
    assert document['outcomes']['schema_violation'] == 1
    assert document['outcomes']['accepted'] == 1
    assert set(by_form(proposal)) == {'штольня'}


@pytest.mark.parametrize(
    'second, code',
    [
        (RuntimeError('http://internal.example:8000/v1 refused'), 'model_call_failed:RuntimeError'),
        ({'error': {'message': 'upstream http://internal.example:8000/v1 down'}}, 'api_error'),
    ],
)
@pytest.mark.asyncio
async def test_a_failed_call_fails_the_document_and_drops_its_items(monkeypatch, tmp_path, second, code):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый: штольня.', {'page_label': 1}), ('c2', 'Второй.', {'page_label': 2})]},
        {'Первый: штольня.': [item('штольня', 'штольня')], 'Второй.': second},
    )

    result = await harness.run()

    proposal = harness.proposal()
    document = proposal['documents'][0]
    assert document['status'] == 'failed'
    assert document['outcomes']['accepted'] == 1
    assert proposal['items'] == []
    assert code in result
    assert 'internal.example' not in result


@pytest.mark.asyncio
async def test_a_chunk_query_that_raises_fails_the_document(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): ConnectionError('vector store down')}
    )

    result = await harness.run()

    document = harness.proposal()['documents'][0]
    assert document['status'] == 'failed'
    assert document['chunks_sampled'] == 0
    assert 'chunk_query_failed:ConnectionError' in result
    assert harness.calls == []


@pytest.mark.parametrize('override', [{'model_id': ''}, {'model_timeout_seconds': float('inf')}])
@pytest.mark.asyncio
async def test_an_invalid_parameter_is_refused_without_a_model_call(monkeypatch, tmp_path, override):
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, {('kb', 'f1'): [('c1', 'Текст.', {})]})

    result = await harness.run(**override)

    assert 'invalid_parameter' in result
    assert harness.calls == []
    assert list(harness.upload_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_a_resume_that_cannot_be_trusted_is_refused_without_a_model_call(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', 'Один.', {})], ('kb', 'f2'): [('c2', 'Два.', {})]},
    )
    first = await harness.run(max_documents=1)
    proposal = harness.proposal()
    harness.calls.clear()
    header = {key: proposal[key] for key in ('seed_sha256', 'model_id', 'parameters', 'scope')}
    unlinked = json.dumps({**proposal}).encode('utf-8')
    no_run_id = json.dumps({**header, 'documents': []}).encode('utf-8')
    base = f'ontology-induction-{proposal["run_id"]}'

    cases = {
        'resume_file_not_found': 'no-such-file',
        'resume_unreadable': harness.own(f'{base}.json', b'{not json'),
        'resume_unreadable ': harness.own(f'{base}.json', no_run_id),
        'resume_checkpoint_missing': harness.own(f'{base}.json', unlinked),
    }
    for code, file_id in cases.items():
        result = await harness.run(resume_file_id=file_id)
        assert code.strip() in result, (code, result)
    assert harness.calls == []
    assert JSON_FILE.search(first)


@pytest.mark.asyncio
async def test_a_resume_with_a_document_cap_moves_past_a_document_without_chunks(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('fa', 'a.pdf'), ('fb', 'b.pdf')]},
        {('kb', 'fb'): [('c1', 'Второй документ: штольня.', {})]},
        {'Второй документ: штольня.': [item('штольня', 'штольня')]},
    )

    first = await harness.run(max_documents=1)
    assert [d['status'] for d in harness.proposal()['documents']] == ['no_stored_chunks', 'pending']
    [markdown] = harness.stored('.md')
    rows = markdown_section(markdown.decode('utf-8'), 6)
    assert '| `a.pdf` | no_stored_chunks | 0 | 0 | 0 | 0 | 0 | 0 |' in rows
    assert '| `b.pdf` | pending | — | — | — | — | — | — |' in rows
    await harness.run(max_documents=1, resume_file_id=JSON_FILE.search(first).group(1))

    resumed = harness.proposal()
    assert [d['status'] for d in resumed['documents']] == ['no_stored_chunks', 'complete']
    assert harness.sampled_texts() == ['Второй документ: штольня.']
    assert 'finished_at' in resumed


@pytest.mark.asyncio
async def test_document_text_reaches_the_reviewer_markdown_only_inside_a_code_span(monkeypatch, tmp_path):
    text = 'Подпись: ![x](https://evil.example/p.png) и <img src=//evil/x> рядом.'
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', text, {})]},
        {
            text: [
                item('![x](https://evil.example/p.png)', '![x](https://evil.example/p.png)'),
                item('<img src=//evil/x>', '<img src=//evil/x>'),
            ]
        },
    )

    await harness.run()

    [markdown] = harness.stored('.md')
    rendered = markdown.decode('utf-8')
    assert '`![x](https://evil.example/p.png)`' in rendered
    assert '`<img src=//evil/x>`' in rendered
    assert rendered.count('![x]') == rendered.count('`![x]')
    assert rendered.count('<img') == rendered.count('`<img')


def _stored_state(harness):
    return {
        file_id: (Path(record.path).read_bytes(), json.dumps(record.meta, sort_keys=True))
        for file_id, record in harness.files.records.items()
    }


@pytest.mark.asyncio
async def test_a_resume_with_other_collections_is_refused_and_leaves_every_file_unchanged(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb-a': [('fa', 'a.pdf')], 'kb-b': [('fb', 'b.pdf')]},
        {('kb-a', 'fa'): [('c1', 'Первый: штольня.', {})], ('kb-b', 'fb'): [('c2', 'Второй: канава.', {})]},
        {'Первый: штольня.': [item('штольня', 'штольня')], 'Второй: канава.': [item('канава', 'канава')]},
    )
    first = await harness.run()
    assert 'finished_at' in harness.proposal()
    before = _stored_state(harness)
    harness.calls.clear()

    result = await harness.run(
        resume_file_id=JSON_FILE.search(first).group(1), __files__=[{'type': 'collection', 'id': 'kb-a'}]
    )

    assert 'resume_mismatch' in result and '`scope`' in result
    assert harness.calls == []
    assert _stored_state(harness) == before
    assert sorted(path.name for path in harness.upload_dir.iterdir()) == sorted(
        Path(record.path).name for record in harness.files.records.values()
    )


@pytest.mark.asyncio
async def test_a_resume_with_the_same_collections_in_another_order_keeps_the_original_order(monkeypatch, tmp_path):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb-a': [('fa', 'a.pdf')], 'kb-b': [('fb', 'b.pdf')]},
        {('kb-a', 'fa'): [('c1', 'Первый: штольня.', {})], ('kb-b', 'fb'): [('c2', 'Второй: канава.', {})]},
        {'Первый: штольня.': [item('штольня', 'штольня')], 'Второй: канава.': [item('канава', 'канава')]},
    )
    first = await harness.run(max_documents=1)
    harness.calls.clear()

    result = await harness.run(
        resume_file_id=JSON_FILE.search(first).group(1),
        __files__=[{'type': 'collection', 'id': 'kb-b'}, {'type': 'collection', 'id': 'kb-a'}],
    )

    assert 'resume_mismatch' not in result
    resumed = harness.proposal()
    assert resumed['scope']['collection_ids'] == ['kb-a', 'kb-b']
    assert [d['file_id'] for d in resumed['documents']] == ['fa', 'fb']
    assert [d['status'] for d in resumed['documents']] == ['complete', 'complete']
    assert harness.sampled_texts() == ['Второй: канава.']


def install_clock(monkeypatch):
    start = dt.datetime(2026, 10, 7, 13, 0, tzinfo=dt.UTC)
    seconds = itertools.count()
    monkeypatch.setattr(
        shell, '_now', lambda: (start + dt.timedelta(seconds=next(seconds))).strftime('%Y-%m-%dT%H:%M:%SZ')
    )


def markdown_finished_at(harness):
    [markdown] = harness.stored('.md')
    return FINISHED.search(markdown.decode('utf-8')).group(1)


@pytest.mark.asyncio
async def test_a_resume_with_nothing_to_process_keeps_finished_at(monkeypatch, tmp_path):
    install_clock(monkeypatch)
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый: штольня.', {})]},
        {'Первый: штольня.': [item('штольня', 'штольня')]},
    )
    first = await harness.run()
    finished_at = harness.proposal()['finished_at']
    assert markdown_finished_at(harness) == finished_at
    harness.calls.clear()

    await harness.run(resume_file_id=JSON_FILE.search(first).group(1))

    assert harness.calls == []
    assert harness.proposal()['finished_at'] == finished_at
    assert markdown_finished_at(harness) == finished_at


@pytest.mark.asyncio
async def test_a_resume_that_retries_a_failed_document_sets_finished_at_after_it(monkeypatch, tmp_path):
    install_clock(monkeypatch)
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf'), ('f2', 'b.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый: штольня.', {})], ('kb', 'f2'): [('c2', 'Второй: канава.', {})]},
        {'Первый: штольня.': [item('штольня', 'штольня')], 'Второй: канава.': RuntimeError('upstream down')},
    )
    first = await harness.run()
    assert [d['status'] for d in harness.proposal()['documents']] == ['complete', 'failed']
    readings = []

    async def complete(request, form_data, user, bypass_filter=False, bypass_system_prompt=False):
        readings.append(shell._now())
        return reply([item('канава', 'канава')])

    monkeypatch.setattr(shell, 'generate_chat_completion', complete)

    await harness.run(resume_file_id=JSON_FILE.search(first).group(1))

    resumed = harness.proposal()
    assert [d['status'] for d in resumed['documents']] == ['complete', 'complete']
    assert len(readings) == 1
    assert resumed['finished_at'] > readings[0]
    assert markdown_finished_at(harness) == resumed['finished_at']


@pytest.mark.asyncio
async def test_a_resume_with_a_document_left_pending_drops_finished_at_until_it_is_processed(monkeypatch, tmp_path):
    install_clock(monkeypatch)
    chunks = {('kb', f'f{n}'): [(f'c{n}', f'Документ {n}: штольня.', {})] for n in (1, 2, 3)}
    replies = {f'Документ {n}: штольня.': [item('штольня', 'штольня')] for n in (1, 2, 3)}
    harness = Harness(monkeypatch, tmp_path, {'kb': [('f1', 'a.pdf')]}, chunks, replies)
    first = await harness.run()
    finished_at = harness.proposal()['finished_at']
    file_id = JSON_FILE.search(first).group(1)
    harness.collections['kb'].extend([('f2', 'b.pdf'), ('f3', 'c.pdf')])

    await harness.run(resume_file_id=file_id, max_documents=1)

    partial = harness.proposal()
    assert [d['status'] for d in partial['documents']] == ['complete', 'complete', 'pending']
    assert 'finished_at' not in partial
    assert markdown_finished_at(harness) == 'нет, остались документы в статусе pending'

    await harness.run(resume_file_id=file_id)

    resumed = harness.proposal()
    assert [d['status'] for d in resumed['documents']] == ['complete', 'complete', 'complete']
    assert resumed['finished_at'] > finished_at
    assert markdown_finished_at(harness) == resumed['finished_at']


@pytest.mark.parametrize('malformed', ['yesterday', '', None, 5, '2026-10-07 13:00:00Z'])
@pytest.mark.asyncio
async def test_a_resume_with_a_malformed_finished_at_is_refused_and_leaves_every_file_unchanged(
    monkeypatch, tmp_path, malformed
):
    harness = Harness(
        monkeypatch,
        tmp_path,
        {'kb': [('f1', 'a.pdf')]},
        {('kb', 'f1'): [('c1', 'Первый: штольня.', {})]},
        {'Первый: штольня.': [item('штольня', 'штольня')]},
    )
    first = await harness.run()
    file_id = JSON_FILE.search(first).group(1)
    proposal_path = Path(harness.files.records[file_id].path)
    proposal_path.write_bytes(shell._json_bytes({**harness.proposal(), 'finished_at': malformed}))
    before = _stored_state(harness)
    harness.calls.clear()

    result = await harness.run(resume_file_id=file_id)

    assert 'resume_unreadable' in result
    assert harness.calls == []
    assert len(before) == 3
    assert _stored_state(harness) == before
