"""Ontology vocabulary induction over the chunks of the collections attached to a chat message."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import logging
import math
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from open_webui.models.files import Files
from open_webui.models.knowledge import Knowledges
from open_webui.models.users import Users
from open_webui.retrieval.lexical import normalize_geological_text
from open_webui.retrieval.utils import filter_accessible_collections
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.routers.files import upload_file_handler
from open_webui.services.ontology_induction.chunks import (
    evidence_locator,
    sample_chunks,
    stored_chunks,
)
from open_webui.services.ontology_induction.errors import OntologyInductionError
from open_webui.services.ontology_induction.proposal import (
    accepted_occurrence,
    assemble_proposal,
    code_span,
    completed_occurrences,
    documents_to_process,
    initial_documents,
    merge_items,
    previous_documents,
    render_markdown,
    resume_mismatches,
    run_totals,
)
from open_webui.services.ontology_induction.reply import (
    completion_failure,
    empty_outcomes,
    item_outcome,
    read_reply,
    response_format,
)
from open_webui.services.ontology_induction.seed import (
    DEFAULT_INDUCTION_PROMPT,
    PinnedSeed,
    SeedIndex,
    build_seed_index,
    load_pinned_seed,
    prompt_sha256,
    seed_block,
    system_prompt,
)
from open_webui.storage.provider import Storage
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.kb_collection_scope import resolve_kb_scope, visual_source_files

log = logging.getLogger(__name__)

TEMPERATURE = 0
META_KEY = 'ontology_induction'
NAME_LIMIT = 80


class _Refusal(Exception):
    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class _Ready:
    """What the checks before any read establish: the verified seed, its index, the scope and the user."""

    seed: PinnedSeed
    index: SeedIndex
    collection_ids: list[str]
    user: Any


@dataclass(frozen=True)
class _Settings:
    """The per-call settings of a run."""

    model_id: str
    chunks_per_document: int
    min_chunk_chars: int
    timeout: float
    system: str


@dataclass(frozen=True)
class _DocumentResult:
    """How one document ended: its status, counts, accepted occurrences and a short failure code."""

    status: str
    chunks_sampled: int
    outcomes: dict[str, int]
    occurrences: list[dict[str, Any]] = field(default_factory=list)
    failure: str = ''


class _Artefact:
    """One OWUI file of the run, created once and overwritten in place."""

    def __init__(self, request: Any, user: Any, name: str, content_type: str, file: Any = None) -> None:
        self.request = request
        self.user = user
        self.name = name
        self.content_type = content_type
        self.file = file

    async def write(self, content: bytes, metadata: Mapping[str, Any] | None = None) -> None:
        """Create the file with `metadata` on the first write; overwrite its storage object afterwards."""
        if self.file is None:
            upload = UploadFile(
                file=io.BytesIO(content), filename=self.name, headers={'content-type': self.content_type}
            )
            self.file = await upload_file_handler(
                self.request, file=upload, metadata=dict(metadata or {}), process=False, user=self.user
            )
            return
        tags = {
            'OpenWebUI-User-Email': self.user.email,
            'OpenWebUI-User-Id': self.user.id,
            'OpenWebUI-User-Name': self.user.name,
            'OpenWebUI-File-Id': self.file.id,
        }
        await asyncio.to_thread(Storage.upload_file, io.BytesIO(content), os.path.basename(self.file.path), tags)
        updated = await Files.update_file_metadata_by_id(
            self.file.id, {'size': len(content), 'file_hash': hashlib.sha256(content).hexdigest()}
        )
        if updated is None:
            log.warning('ontology induction: size and hash of file %s were not updated', self.file.id)

    def url(self) -> str:
        """The download path of the file."""
        return str(self.request.app.url_path_for('get_file_content_by_id', id=self.file.id))


@dataclass
class _Run:
    """The identity and files of a run, and what a resumed run inherits."""

    run_id: str
    started_at: str
    proposal_file: _Artefact
    markdown_file: _Artefact
    checkpoint_file: _Artefact
    previous: dict[str, dict[str, Any]] = field(default_factory=dict)
    completed: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _refusal_text(code: str, detail: str = '') -> str:
    lines = [f'**Индукция словаря онтологии отклонена:** `{code}`']
    if detail:
        lines.append(detail)
    return '\n\n'.join(lines)


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _plain(text: str) -> str:
    flat = ' '.join(str(text).split())
    return flat if len(flat) <= NAME_LIMIT else flat[:NAME_LIMIT] + '…'


def _base_name(run_id: str) -> str:
    return f'ontology-induction-{run_id}'


async def _status(emitter: Any, description: str, done: bool = False) -> None:
    if emitter is None:
        return
    try:
        await emitter({'type': 'status', 'data': {'description': description, 'done': done}})
    except Exception as exc:
        log.debug('ontology induction status emit failed: %s', exc)


def _parameters(
    chunks_per_document: int, min_chunk_chars: int, max_evidence_per_item: int, prompt: str
) -> dict[str, Any]:
    return {
        'chunks_per_document': chunks_per_document,
        'min_chunk_chars': min_chunk_chars,
        'temperature': TEMPERATURE,
        'max_evidence_per_item': max_evidence_per_item,
        'prompt_sha256': prompt_sha256(prompt),
    }


def _invalid_parameter(
    model_id: str,
    chunks_per_document: int,
    min_chunk_chars: int,
    max_documents: int,
    model_timeout_seconds: float,
    max_evidence_per_item: int,
) -> str | None:
    checks = (
        ('model_id', bool(model_id)),
        ('chunks_per_document', chunks_per_document >= 1),
        ('min_chunk_chars', min_chunk_chars >= 0),
        ('max_documents', max_documents >= 0),
        ('model_timeout_seconds', math.isfinite(model_timeout_seconds) and model_timeout_seconds > 0),
        ('max_evidence_per_item', max_evidence_per_item >= 1),
    )
    return next((name for name, ok in checks if not ok), None)


def _file_name(file: Any) -> str:
    meta = file.meta if isinstance(getattr(file, 'meta', None), Mapping) else {}
    return str(meta.get('name') or '')


def _links(file: Any) -> Mapping[str, Any]:
    meta = file.meta if isinstance(getattr(file, 'meta', None), Mapping) else {}
    data = meta.get('data') if isinstance(meta.get('data'), Mapping) else {}
    links = data.get(META_KEY)
    return links if isinstance(links, Mapping) else {}


async def _owned(file_id: Any, user: Any) -> Any:
    if not isinstance(file_id, str) or not file_id:
        return None
    file = await Files.get_file_by_id_and_user_id(file_id, user.id)
    return file if file is not None and getattr(file, 'path', None) else None


async def _read(file: Any) -> bytes | None:
    try:
        local = await asyncio.to_thread(Storage.get_file, file.path)
        return await asyncio.to_thread(Path(local).read_bytes)
    except Exception:
        log.warning('ontology induction: file %s could not be read', file.id, exc_info=True)
        return None


def _loads(raw: bytes | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError):
        return None


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def _first_rows(result: Any) -> tuple[Any, Any, Any]:
    if result is None:
        return None, None, None
    return tuple((rows or [None])[0] for rows in (result.ids, result.documents, result.metadatas))


async def _checked_scope(
    *,
    model_id: str,
    chunks_per_document: int,
    min_chunk_chars: int,
    max_documents: int,
    model_timeout_seconds: float,
    max_evidence_per_item: int,
    user_data: Mapping[str, Any] | None,
    request: Any,
    files: Sequence[Any] | None,
) -> _Ready:
    invalid = _invalid_parameter(
        model_id, chunks_per_document, min_chunk_chars, max_documents, model_timeout_seconds, max_evidence_per_item
    )
    if invalid:
        raise _Refusal('invalid_parameter', f'Недопустимое значение `{invalid}`.')
    seed = await asyncio.to_thread(load_pinned_seed)
    other = visual_source_files(files)
    if other:
        kinds = sorted({str(entry.get('type') or '?') if isinstance(entry, Mapping) else '?' for entry in other})
        raise _Refusal(
            'unsupported_attachment',
            'Читаются только коллекции знаний; вложения: ' + ', '.join(code_span(kind) for kind in kinds) + '.',
        )
    scope = resolve_kb_scope(files)
    if scope['kb_scope_status'] != 'configured':
        raise _Refusal(
            'kb_scope_unconfigured', 'kb_scope_status: unconfigured. Прикрепите коллекции знаний к сообщению.'
        )
    collection_ids = list(scope['kb_configured_collections'])
    if request is None or not user_data or not user_data.get('id'):
        raise _Refusal('missing_runtime_context', 'Нет запроса или пользователя.')
    user = await Users.get_user_by_id(user_data['id'])
    if user is None:
        raise _Refusal('user_unknown')
    allowed = await filter_accessible_collections(set(collection_ids), user, access_type='read')
    withheld = [collection_id for collection_id in collection_ids if collection_id not in allowed]
    if withheld:
        raise _Refusal(
            'collection_not_accessible',
            'Нет доступа на чтение: ' + ', '.join(code_span(c) for c in withheld) + '.',
        )
    index = await asyncio.to_thread(build_seed_index, seed.terms, normalize_geological_text)
    return _Ready(seed, index, collection_ids, user)


def _fresh(request: Any, user: Any) -> _Run:
    run_id = uuid.uuid4().hex
    base = _base_name(run_id)
    return _Run(
        run_id=run_id,
        started_at=_now(),
        proposal_file=_Artefact(request, user, f'{base}.json', 'application/json'),
        markdown_file=_Artefact(request, user, f'{base}.md', 'text/markdown'),
        checkpoint_file=_Artefact(request, user, f'{base}.checkpoint.json', 'application/json'),
    )


async def _resume(request: Any, user: Any, resume_file_id: str, current: Mapping[str, Any], index: SeedIndex) -> _Run:
    file = await _owned(resume_file_id, user)
    if file is None:
        raise _Refusal(
            'resume_file_not_found', f'Файл {code_span(resume_file_id)} не найден среди файлов пользователя.'
        )
    previous = _loads(await _read(file))
    if not isinstance(previous, dict):
        raise _Refusal('resume_unreadable', f'Файл {code_span(resume_file_id)} не является предложением индукции.')
    mismatched = resume_mismatches(previous, current)
    if mismatched:
        raise _Refusal('resume_mismatch', 'Отличаются: ' + ', '.join(f'`{key}`' for key in mismatched) + '.')
    documents = previous_documents(previous)
    if documents is None or _file_name(file) != f'{_base_name(previous["run_id"])}.json':
        raise _Refusal('resume_unreadable', f'Файл {code_span(resume_file_id)} не является предложением индукции.')
    run_id = previous['run_id']
    base = _base_name(run_id)
    links = _links(file)
    checkpoint = await _owned(links.get('checkpoint_file_id'), user)
    markdown = await _owned(links.get('markdown_file_id'), user)
    stored = await asyncio.to_thread(_loads, await _read(checkpoint)) if checkpoint is not None else None
    if (
        links.get('run_id') != run_id
        or markdown is None
        or _file_name(markdown) != f'{base}.md'
        or checkpoint is None
        or _file_name(checkpoint) != f'{base}.checkpoint.json'
        or not isinstance(stored, Mapping)
        or stored.get('run_id') != run_id
    ):
        raise _Refusal(
            'resume_checkpoint_missing', f'У файла {code_span(resume_file_id)} нет контрольной точки запуска.'
        )
    return _Run(
        run_id=run_id,
        started_at=previous['started_at'],
        proposal_file=_Artefact(request, user, f'{base}.json', 'application/json', file),
        markdown_file=_Artefact(request, user, f'{base}.md', 'text/markdown', markdown),
        checkpoint_file=_Artefact(request, user, f'{base}.checkpoint.json', 'application/json', checkpoint),
        previous=documents,
        completed=await asyncio.to_thread(completed_occurrences, documents, run_id, stored, index),
    )


async def _documents_in_scope(collection_ids: Sequence[str]) -> list[tuple[str, str, str]]:
    listed: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for collection_id in collection_ids:
        metadatas = await Knowledges.get_file_metadatas_by_id(collection_id)
        named = sorted((str((m.meta or {}).get('name') or m.id), m.id) for m in metadatas)
        for name, file_id in named:
            if file_id not in seen:
                seen.add(file_id)
                listed.append((collection_id, file_id, name))
    return listed


async def _call_model(request: Any, user: Any, settings: _Settings, text: str) -> Any:
    form_data = {
        'model': settings.model_id,
        'messages': [{'role': 'system', 'content': settings.system}, {'role': 'user', 'content': text}],
        'stream': False,
        'temperature': TEMPERATURE,
        'response_format': response_format(),
        'chat_template_kwargs': {'enable_thinking': False},
        'enable_thinking': False,
        'metadata': {'task': META_KEY},
    }
    return await asyncio.wait_for(
        generate_chat_completion(request, form_data, user, bypass_system_prompt=True), timeout=settings.timeout
    )


async def _process_document(
    request: Any, user: Any, collection_id: str, file_id: str, settings: _Settings, index: SeedIndex
) -> _DocumentResult:
    outcomes = empty_outcomes()
    try:
        result = await ASYNC_VECTOR_DB_CLIENT.query(collection_name=collection_id, filter={'file_id': file_id})
    except Exception as exc:
        log.warning('ontology induction: chunk query failed for file %s', file_id, exc_info=True)
        return _DocumentResult('failed', 0, outcomes, failure=f'chunk_query_failed:{type(exc).__name__}')
    chunks = stored_chunks(*_first_rows(result))
    if not chunks:
        return _DocumentResult('no_stored_chunks', 0, outcomes)
    sampled = sample_chunks(chunks, settings.chunks_per_document, settings.min_chunk_chars)
    occurrences: list[dict[str, Any]] = []
    for chunk_rank, chunk in enumerate(sampled):
        try:
            response = await _call_model(request, user, settings, chunk.text)
        except TimeoutError:
            outcomes['timeout'] += 1
            continue
        except Exception as exc:
            log.warning('ontology induction: model call failed for file %s', file_id, exc_info=True)
            return _DocumentResult('failed', len(sampled), outcomes, failure=f'model_call_failed:{type(exc).__name__}')
        failure = completion_failure(response)
        if failure:
            log.warning('ontology induction: completion for file %s is not a reply: %s', file_id, failure)
            return _DocumentResult('failed', len(sampled), outcomes, failure=failure)
        reply = read_reply(response)
        if reply.outcome:
            outcomes[reply.outcome] += 1
            continue
        locator = evidence_locator(chunk.metadata)
        for item_rank, item in enumerate(reply.items):
            outcome = item_outcome(item, chunk.text, normalize_geological_text, index)
            outcomes[outcome] += 1
            if outcome == 'accepted':
                occurrences.append(accepted_occurrence(item, file_id, chunk, chunk_rank, item_rank, locator))
    return _DocumentResult('complete', len(sampled), outcomes, occurrences)


async def induce_ontology_vocabulary(
    resume_file_id: str = '',
    *,
    model_id: str = '',
    chunks_per_document: int = 3,
    min_chunk_chars: int = 200,
    max_documents: int = 0,
    model_timeout_seconds: float = 180,
    max_evidence_per_item: int = 5,
    induction_prompt: str = '',
    __request__: Any = None,
    __user__: dict | None = None,
    __event_emitter__: Any = None,
    __files__: list | None = None,
) -> str:
    """Propose ontology vocabulary from the documents of the knowledge collections attached to this message.

    Use this function when the user asks to induce, extract or propose ontology vocabulary or terms
    from the attached collections. It samples stored chunks of every document, lists the terms they
    use against the GMM ontology seed with the excerpt each came from, and returns download links
    for a JSON proposal and a reviewer Markdown file. Attach the collections to the message first.

    :param resume_file_id: Exact id of the JSON proposal file of an earlier run, to continue it.
        Only a file id a previous result of this tool printed; never invent one.
    :param model_id: Model that reads the chunks.
    :param chunks_per_document: Chunks sampled per document.
    :param min_chunk_chars: Chunks shorter than this many characters are not sampled.
    :param max_documents: Documents processed by this call; 0 means every document.
    :param model_timeout_seconds: Time limit of one model call, in seconds.
    :param max_evidence_per_item: Evidence entries kept per proposed item.
    :param induction_prompt: Replaces the default induction prompt when non-empty.
    :return: Markdown with the proposal links, totals per document status and per outcome, and refusals.
    """
    try:
        return await _run(
            resume_file_id=str(resume_file_id or '').strip(),
            model_id=str(model_id or '').strip(),
            chunks_per_document=chunks_per_document,
            min_chunk_chars=min_chunk_chars,
            max_documents=max_documents,
            model_timeout_seconds=model_timeout_seconds,
            max_evidence_per_item=max_evidence_per_item,
            prompt=induction_prompt if str(induction_prompt or '').strip() else DEFAULT_INDUCTION_PROMPT,
            request=__request__,
            user_data=__user__,
            emitter=__event_emitter__,
            files=__files__,
        )
    except _Refusal as refusal:
        await _status(__event_emitter__, f'Индукция отклонена: {refusal.code}', done=True)
        return _refusal_text(refusal.code, refusal.detail)
    except OntologyInductionError as exc:
        await _status(__event_emitter__, f'Индукция отклонена: {exc.code}', done=True)
        return _refusal_text(exc.code, str(exc))


async def _persist(
    run: _Run,
    header: dict[str, Any],
    documents: list[dict[str, Any]],
    occurrences: Mapping[str, list[dict[str, Any]]],
    order: Sequence[str],
    index: SeedIndex,
    max_evidence_per_item: int,
) -> dict[str, Any]:
    def snapshot() -> tuple[dict[str, Any], bytes, bytes, bytes]:
        items = merge_items(occurrences, order, index, normalize_geological_text, max_evidence_per_item)
        if all(document['status'] != 'pending' for document in documents):
            header['finished_at'] = header.get('finished_at') or _now()
        proposal = assemble_proposal(header=header, documents=documents, items=items, index=index)
        checkpoint = _json_bytes({'run_id': run.run_id, 'occurrences': occurrences})
        return proposal, checkpoint, render_markdown(proposal, index).encode('utf-8'), _json_bytes(proposal)

    proposal, checkpoint, markdown, body = await asyncio.to_thread(snapshot)
    await run.checkpoint_file.write(checkpoint)
    await run.markdown_file.write(markdown)
    links = {'checkpoint_file_id': run.checkpoint_file.file.id, 'markdown_file_id': run.markdown_file.file.id}
    await run.proposal_file.write(body, {META_KEY: {'run_id': run.run_id, **links}})
    return proposal


async def _run(
    *,
    resume_file_id: str,
    model_id: str,
    chunks_per_document: int,
    min_chunk_chars: int,
    max_documents: int,
    model_timeout_seconds: float,
    max_evidence_per_item: int,
    prompt: str,
    request: Any,
    user_data: Mapping[str, Any] | None,
    emitter: Any,
    files: Sequence[Any] | None,
) -> str:
    ready = await _checked_scope(
        model_id=model_id,
        chunks_per_document=chunks_per_document,
        min_chunk_chars=min_chunk_chars,
        max_documents=max_documents,
        model_timeout_seconds=model_timeout_seconds,
        max_evidence_per_item=max_evidence_per_item,
        user_data=user_data,
        request=request,
        files=files,
    )
    settings = _Settings(
        model_id,
        chunks_per_document,
        min_chunk_chars,
        model_timeout_seconds,
        system_prompt(prompt, seed_block(ready.seed.terms)),
    )
    current = {
        'seed_sha256': ready.seed.sha256,
        'model_id': model_id,
        'parameters': _parameters(chunks_per_document, min_chunk_chars, max_evidence_per_item, prompt),
    }
    run = (
        await _resume(request, ready.user, resume_file_id, current, ready.index)
        if resume_file_id
        else _fresh(request, ready.user)
    )

    listed = await _documents_in_scope(ready.collection_ids)
    order = [file_id for _, file_id, _ in listed]
    collection_of = {file_id: collection_id for collection_id, file_id, _ in listed}
    names = {file_id: name for _, file_id, name in listed}
    occurrences = {file_id: run.completed[file_id] for file_id in order if file_id in run.completed}
    documents = initial_documents([(file_id, names[file_id]) for file_id in order], run.previous, occurrences)
    header: dict[str, Any] = {
        'run_id': run.run_id,
        'seed_id': ready.seed.seed_id,
        **current,
        'scope': {'collection_ids': ready.collection_ids},
        'started_at': run.started_at,
    }
    queue = documents_to_process(documents, occurrences)
    selected = queue[:max_documents] if max_documents else queue

    proposal = await _persist(run, header, documents, occurrences, order, ready.index, max_evidence_per_item)
    failures: list[str] = []
    for position, file_id in enumerate(selected, start=1):
        await _status(emitter, f'Индукция: документ {position}/{len(selected)} — {_plain(names[file_id])}')
        result = await _process_document(request, ready.user, collection_of[file_id], file_id, settings, ready.index)
        documents[order.index(file_id)] = {
            'file_id': file_id,
            'name': names[file_id],
            'status': result.status,
            'chunks_sampled': result.chunks_sampled,
            'outcomes': result.outcomes,
        }
        if result.status == 'complete':
            occurrences[file_id] = result.occurrences
        else:
            occurrences.pop(file_id, None)
        if result.failure:
            failures.append(f'{code_span(_plain(names[file_id]))}: `{result.failure}`')
        proposal = await _persist(run, header, documents, occurrences, order, ready.index, max_evidence_per_item)
    await _status(emitter, 'Индукция завершена', done=True)
    return _result_text(proposal, run, failures)


def _result_text(proposal: Mapping[str, Any], run: _Run, failures: Sequence[str]) -> str:
    statuses, outcomes = run_totals(proposal)
    state = 'завершён' if proposal.get('finished_at') else 'не завершён: продолжите с `resume_file_id`'
    lines = [
        f'**Индукция словаря онтологии**, запуск `{proposal["run_id"]}` {state}.',
        '',
        f'- Предложение (JSON, файл `{run.proposal_file.file.id}`): '
        f'[{run.proposal_file.name}]({run.proposal_file.url()})',
        f'- Для рецензии (Markdown): [{run.markdown_file.name}]({run.markdown_file.url()})',
        '',
        'Документы: ' + ', '.join(f'{status} {count}' for status, count in statuses.items()) + '.',
        'Исходы: ' + ', '.join(f'{outcome} {count}' for outcome, count in outcomes.items()) + '.',
        '',
        'Отказы: ' + ('; '.join(failures) if failures else 'нет') + '.',
    ]
    if statuses['failed'] or statuses['no_stored_chunks']:
        lines.append('Документы failed и no_stored_chunks обрабатываются повторно при продолжении с `resume_file_id`.')
    return '\n'.join(lines)
