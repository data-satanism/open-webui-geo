"""The proposal: merging accepted items, assembling the artefact, resume checks and the reviewer Markdown."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .chunks import StoredChunk
from .errors import EvidenceOutsideDocuments
from .reply import OUTCOMES
from .seed import PROPOSED_KINDS, SeedIndex

RESUME_KEYS = ('seed_sha256', 'model_id', 'parameters')
DOCUMENT_STATUSES = ('complete', 'no_stored_chunks', 'failed', 'pending')
FOLD_AFTER = 10
CODE_SPAN_LIMIT = 120
RUN_ID = re.compile(r'[0-9a-f]{32}')
TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
_OCCURRENCE_STRINGS = ('file_id', 'chunk_id', 'surface_form', 'excerpt', 'proposed_kind')
_LOCATOR_STRINGS = ('document_id', 'document_version', 'section_path', 'child_chunk_id')


def accepted_occurrence(
    item: Mapping[str, str],
    file_id: str,
    chunk: StoredChunk,
    chunk_rank: int,
    item_rank: int,
    locator: Mapping[str, Any],
) -> dict[str, Any]:
    """One accepted item with the chunk it came from, as the run checkpoint stores it."""
    occurrence: dict[str, Any] = {
        'file_id': file_id,
        'chunk_id': chunk.chunk_id,
        'chunk_rank': chunk_rank,
        'item_rank': item_rank,
        'surface_form': item['surface_form'],
        'excerpt': item['excerpt'],
        'proposed_kind': item['proposed_kind'],
    }
    for key in ('proposed_class', 'suggested_seed_term_id'):
        if item.get(key) is not None:
            occurrence[key] = item[key]
    occurrence['locator'] = dict(locator)
    return occurrence


def _majority(values: Iterable[str | None]) -> str | None:
    counts = Counter(value for value in values if value is not None)
    if not counts:
        return None
    best = max(counts.values())
    return min(value for value, count in counts.items() if count == best)


def _evidence(occurrence: Mapping[str, Any]) -> dict[str, Any]:
    excerpt = occurrence['excerpt']
    return {
        'file_id': occurrence['file_id'],
        'chunk_id': occurrence['chunk_id'],
        'excerpt': excerpt,
        'excerpt_sha256': hashlib.sha256(excerpt.encode('utf-8')).hexdigest(),
        **occurrence.get('locator', {}),
    }


def _selected_evidence(
    group: Sequence[Mapping[str, Any]], document_position: Mapping[str, int], limit: int
) -> list[dict[str, Any]]:
    by_file: dict[str, list[Mapping[str, Any]]] = {}
    for occurrence in group:
        by_file.setdefault(occurrence['file_id'], []).append(occurrence)
    ranked = []
    for file_id, occurrences in by_file.items():
        ordered = sorted(occurrences, key=lambda o: (o['chunk_rank'], o['item_rank']))
        for rank, occurrence in enumerate(ordered):
            key = (rank, document_position[file_id], occurrence['chunk_rank'], occurrence['item_rank'])
            ranked.append((key, occurrence))
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, occurrence in sorted(ranked, key=lambda pair: pair[0]):
        identity = (occurrence['file_id'], occurrence['chunk_id'], occurrence['excerpt'])
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(_evidence(occurrence))
        if len(selected) == limit:
            break
    return selected


def merge_items(
    occurrences_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    document_order: Sequence[str],
    index: SeedIndex,
    normalize: Callable[[str], str],
    max_evidence: int,
) -> list[dict[str, Any]]:
    """Group accepted occurrences by normalised surface form into proposal items, sorted by form.

    Counts are over every occurrence. `seed_term_ids` lists every seed term whose normalised label
    equals the form; an item with none is a new candidate. Each of `proposed_kind`,
    `proposed_class` and `suggested_seed_term_id` takes the value most occurrences carry, a tie
    going to the smallest value; an optional key is absent only when no occurrence carries it.
    Evidence takes each document's first occurrence in document order, then each document's
    second, and so on, up to `max_evidence` entries.
    """
    position = {file_id: rank for rank, file_id in enumerate(document_order)}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for file_id in document_order:
        for occurrence in occurrences_by_file.get(file_id, ()):
            groups.setdefault(normalize(occurrence['surface_form']), []).append(occurrence)
    items = []
    for form in sorted(groups):
        group = groups[form]
        item: dict[str, Any] = {
            'normalized_form': form,
            'surface_forms': sorted({occurrence['surface_form'] for occurrence in group}),
        }
        seed_term_ids = index.by_form.get(form)
        if seed_term_ids:
            item['seed_term_ids'] = list(seed_term_ids)
        else:
            item['status'] = 'new_candidate'
            item['proposed_kind'] = _majority(occurrence['proposed_kind'] for occurrence in group)
            proposed_class = _majority(occurrence.get('proposed_class') for occurrence in group)
            if proposed_class is not None:
                item['proposed_class'] = proposed_class
        suggested = _majority(occurrence.get('suggested_seed_term_id') for occurrence in group)
        if suggested is not None:
            item['suggested_seed_term_id'] = suggested
        item['document_count'] = len({occurrence['file_id'] for occurrence in group})
        item['occurrence_count'] = len(group)
        item['evidence'] = _selected_evidence(group, position, max_evidence)
        items.append(item)
    return items


def assemble_proposal(
    *,
    header: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    index: SeedIndex,
) -> dict[str, Any]:
    """The proposal document in the pinned schema's key order.

    `header` carries `run_id`, `seed_id`, `seed_sha256`, `model_id`, `parameters`, `scope`,
    `started_at` and, once no document is pending, `finished_at`. Raises
    `EvidenceOutsideDocuments` when an evidence entry names a file absent from `documents`.
    """
    listed = {document['file_id'] for document in documents}
    for item in items:
        for evidence in item['evidence']:
            if evidence['file_id'] not in listed:
                raise EvidenceOutsideDocuments(
                    f'item {item["normalized_form"]!r} cites file {evidence["file_id"]!r}, which is not in documents[]'
                )
    linked = {term_id for item in items for term_id in item.get('seed_term_ids', ())}
    proposal: dict[str, Any] = {
        key: header[key]
        for key in ('run_id', 'seed_id', 'seed_sha256', 'model_id', 'parameters', 'scope', 'started_at')
    }
    if header.get('finished_at'):
        proposal['finished_at'] = header['finished_at']
    proposal['documents'] = [dict(document) for document in documents]
    proposal['items'] = [dict(item) for item in items]
    proposal['unseen_seed_term_ids'] = [term_id for term_id in index.lexical_term_ids if term_id not in linked]
    return proposal


def resume_mismatches(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The keys among `seed_sha256`, `model_id` and `parameters` whose values differ between two runs."""
    return [key for key in RESUME_KEYS if previous.get(key) != current.get(key)]


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _valid_document(document: Any) -> bool:
    if not isinstance(document, Mapping) or not (
        _non_empty(document.get('file_id')) and _non_empty(document.get('name'))
    ):
        return False
    status = document.get('status')
    if status == 'pending':
        return set(document) == {'file_id', 'name', 'status'}
    outcomes = document.get('outcomes')
    return (
        status in DOCUMENT_STATUSES
        and set(document) == {'file_id', 'name', 'status', 'chunks_sampled', 'outcomes'}
        and _count(document.get('chunks_sampled'))
        and isinstance(outcomes, Mapping)
        and set(outcomes) == set(OUTCOMES)
        and all(_count(count) for count in outcomes.values())
    )


def previous_documents(previous: Mapping[str, Any]) -> dict[str, dict[str, Any]] | None:
    """The documents of a previous proposal by file id, or None when the proposal is malformed.

    Well-formed means a 32-character lowercase hex `run_id`, a `started_at` of the form
    `YYYY-MM-DDTHH:MM:SSZ`, and a
    `documents` list whose entries each carry exactly the keys their status requires.
    """
    run_id = previous.get('run_id')
    started_at = previous.get('started_at')
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        return None
    if not isinstance(started_at, str) or not TIMESTAMP.fullmatch(started_at):
        return None
    documents = previous.get('documents')
    if not isinstance(documents, list) or not all(_valid_document(document) for document in documents):
        return None
    return {document['file_id']: dict(document) for document in documents}


def _valid_locator(locator: Any) -> bool:
    if not isinstance(locator, Mapping) or not set(locator) <= {'page', 'start_index', *_LOCATOR_STRINGS}:
        return False
    if 'page' in locator and not (_count(locator['page']) and locator['page'] >= 1):
        return False
    if 'start_index' in locator and not _count(locator['start_index']):
        return False
    return all(_non_empty(locator[key]) for key in _LOCATOR_STRINGS if key in locator)


def _valid_occurrence(occurrence: Any, file_id: str, index: SeedIndex) -> bool:
    return (
        isinstance(occurrence, Mapping)
        and occurrence.get('file_id') == file_id
        and all(_non_empty(occurrence.get(key)) for key in _OCCURRENCE_STRINGS)
        and occurrence['proposed_kind'] in PROPOSED_KINDS
        and _count(occurrence.get('chunk_rank'))
        and _count(occurrence.get('item_rank'))
        and ('proposed_class' not in occurrence or occurrence['proposed_class'] in index.class_term_ids)
        and ('suggested_seed_term_id' not in occurrence or occurrence['suggested_seed_term_id'] in index.term_ids)
        and _valid_locator(occurrence.get('locator'))
    )


def completed_occurrences(
    documents: Mapping[str, Mapping[str, Any]], run_id: str, checkpoint: Any, index: SeedIndex
) -> dict[str, list[dict[str, Any]]]:
    """Occurrences of the previous run's `complete` documents, by file id.

    A document is included only when the checkpoint belongs to `run_id` and every occurrence it
    holds for the document is well-formed and names only seed terms; any other document is
    processed again.
    """
    if not isinstance(checkpoint, Mapping) or checkpoint.get('run_id') != run_id:
        return {}
    stored = checkpoint.get('occurrences')
    if not isinstance(stored, Mapping):
        return {}
    found = {}
    for file_id, document in documents.items():
        occurrences = stored.get(file_id)
        if document['status'] != 'complete' or not isinstance(occurrences, list):
            continue
        if all(_valid_occurrence(occurrence, file_id, index) for occurrence in occurrences):
            found[file_id] = [dict(occurrence) for occurrence in occurrences]
    return found


def initial_documents(
    listed: Sequence[tuple[str, str]],
    previous: Mapping[str, Mapping[str, Any]],
    completed: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """The `documents[]` a run starts from, in listing order.

    A completed document and a document that ended `no_stored_chunks` or `failed` keep their
    previous entry under the current name; every other document is `pending`.
    """
    documents = []
    for file_id, name in listed:
        kept = previous.get(file_id)
        if kept is not None and (file_id in completed or kept['status'] in ('no_stored_chunks', 'failed')):
            documents.append({**kept, 'name': name})
        else:
            documents.append({'file_id': file_id, 'name': name, 'status': 'pending'})
    return documents


def documents_to_process(documents: Sequence[Mapping[str, Any]], completed: Mapping[str, Any]) -> list[str]:
    """File ids to process: `pending` documents first, then `no_stored_chunks` and `failed` ones, each in order."""
    open_ids = [document['file_id'] for document in documents if document['file_id'] not in completed]
    statuses = {document['file_id']: document['status'] for document in documents}
    return [f for f in open_ids if statuses[f] == 'pending'] + [f for f in open_ids if statuses[f] != 'pending']


def run_totals(proposal: Mapping[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    """Documents per status and outcomes summed over documents."""
    statuses = {status: 0 for status in DOCUMENT_STATUSES}
    outcomes = {outcome: 0 for outcome in OUTCOMES}
    for document in proposal['documents']:
        statuses[document['status']] += 1
        for outcome, count in (document.get('outcomes') or {}).items():
            outcomes[outcome] += count
    return statuses, outcomes


def _cell(text: Any) -> str:
    return ' '.join(str(text).split()).replace('|', '\\|')


def _ids(ids: Sequence[str]) -> str:
    shown = ', '.join(f'`{term_id}`' for term_id in ids[:FOLD_AFTER])
    hidden = len(ids) - FOLD_AFTER
    return f'{shown} … и ещё {hidden}' if hidden > 0 else shown


def code_span(text: Any, limit: int = CODE_SPAN_LIMIT) -> str:
    """`text` as one Markdown code span that is safe inside a table cell.

    Whitespace is collapsed, text beyond `limit` characters is cut and ended with `…`, the fence
    is one backtick longer than the longest backtick run inside, and `|` is escaped.
    """
    flat = ' '.join(str(text).split())
    if len(flat) > limit:
        flat = flat[:limit] + '…'
    fence = '`' * (max((len(run) for run in re.findall(r'`+', flat)), default=0) + 1)
    pad = ' ' if flat.startswith('`') or flat.endswith('`') else ''
    escaped = flat.replace('|', '\\|')
    return f'{fence}{pad}{escaped}{pad}{fence}'


def _forms(item: Mapping[str, Any]) -> str:
    return '; '.join(code_span(form) for form in item['surface_forms'])


def _single_matches(items: Sequence[Mapping[str, Any]]) -> list[str]:
    rows = [item for item in items if len(item.get('seed_term_ids', ())) == 1]
    if not rows:
        return ['Нет.']
    lines = [
        '| Термин затравки | Нормализованная форма | Поверхностные формы | Документов | Вхождений |',
        '| --- | --- | --- | ---: | ---: |',
    ]
    for item in sorted(rows, key=lambda item: (item['seed_term_ids'][0], item['normalized_form'])):
        lines.append(
            f'| `{item["seed_term_ids"][0]}` | {_cell(item["normalized_form"])} | {_forms(item)} '
            f'| {item["document_count"]} | {item["occurrence_count"]} |'
        )
    return lines


def _ambiguous_matches(items: Sequence[Mapping[str, Any]], index: SeedIndex) -> list[str]:
    rows = [item for item in items if len(item.get('seed_term_ids', ())) > 1]
    if not rows:
        return ['Нет.']
    lines = [
        '| Нормализованная форма | Терминов | Виды терминов | Термины затравки |',
        '| --- | ---: | --- | --- |',
    ]
    for item in rows:
        ids = item['seed_term_ids']
        kinds = Counter(index.kind_by_term_id.get(term_id, '?') for term_id in ids)
        kind_text = ', '.join(f'{kind} ×{count}' for kind, count in sorted(kinds.items()))
        lines.append(f'| {_cell(item["normalized_form"])} | {len(ids)} | {kind_text} | {_ids(ids)} |')
    return lines


def _new_candidates(items: Sequence[Mapping[str, Any]]) -> list[str]:
    rows = [item for item in items if item.get('status') == 'new_candidate']
    if not rows:
        return ['Нет.']
    groups: dict[str | None, list[Mapping[str, Any]]] = {}
    for item in rows:
        groups.setdefault(item.get('suggested_seed_term_id'), []).append(item)
    ordered = sorted(key for key in groups if key is not None) + ([None] if None in groups else [])
    lines: list[str] = []
    for key in ordered:
        title = f'Предложенный термин затравки `{key}`' if key else 'Без предложенного термина затравки'
        lines += [
            f'### {title}',
            '',
            '| Нормализованная форма | Поверхностные формы | Вид | Класс | Документов | Вхождений |',
            '| --- | --- | --- | --- | ---: | ---: |',
        ]
        ranked = sorted(
            groups[key], key=lambda item: (-item['document_count'], -item['occurrence_count'], item['normalized_form'])
        )
        for item in ranked:
            proposed_class = f'`{item["proposed_class"]}`' if item.get('proposed_class') else '—'
            lines.append(
                f'| {_cell(item["normalized_form"])} | {_forms(item)} | {item["proposed_kind"]} | {proposed_class} '
                f'| {item["document_count"]} | {item["occurrence_count"]} |'
            )
        lines.append('')
    return lines[:-1]


def render_markdown(proposal: Mapping[str, Any], index: SeedIndex) -> str:
    """The reviewer-facing Markdown of a proposal, in Russian, in five sections."""
    statuses, _ = run_totals(proposal)
    items = proposal['items']
    unseen = proposal['unseen_seed_term_ids']
    lines = [
        '# Индукция словаря онтологии: предложение для рецензии',
        '',
        f'- Запуск: `{proposal["run_id"]}`',
        f'- Затравка: `{proposal["seed_id"]}`, sha256 `{proposal["seed_sha256"]}`',
        f'- Модель: `{proposal["model_id"]}`',
        f'- Начат: {proposal["started_at"]}',
        f'- Завершён: {proposal.get("finished_at") or "нет, остались документы в статусе pending"}',
        '- Документы: ' + ', '.join(f'{status} — {count}' for status, count in statuses.items()),
        '',
        '## 1. Совпадения с одним термином затравки',
        '',
        *_single_matches(items),
        '',
        '## 2. Неоднозначные совпадения',
        '',
        *_ambiguous_matches(items, index),
        '',
        '## 3. Новые кандидаты',
        '',
        *_new_candidates(items),
        '',
        '## 4. Термины затравки, не встреченные в документах',
        '',
        *([f'- `{term_id}`' for term_id in unseen] or ['Нет.']),
        '',
        '## 5. Термины без labels_ru',
        '',
        f'Терминов затравки без labels_ru, которые нельзя сопоставить лексически: {index.unlabelled_count}.',
        '',
    ]
    return '\n'.join(lines)
