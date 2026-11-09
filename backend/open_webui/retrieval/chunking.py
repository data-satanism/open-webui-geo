"""Deterministic parent-child metadata for evidence-oriented RAG indexing."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable
from typing import Any

from langchain_core.documents import Document

DEFAULT_PARENT_CONTEXT_MAX_CHARS = 12_000
INTERNAL_KEYS = {'_rag_parent_text', '_rag_annotation_spans', '_rag_atomic_ranges', '_rag_source_facets'}
MAX_METADATA_VALUES = 64
MAX_METADATA_VALUE_CHARS = 512
ALLOWED_SOURCE_CLASSES = frozenset(
    {
        'annotated_corpus',
        'company_registry',
        'feasibility_study',
        'geological_report',
        'gis_project',
        'licence_document',
        'map_explanatory_note',
        'metallurgical_test_report',
        'official_map',
        'official_registry',
        'reference_book',
        'reserve_protocol',
        'resource_statement',
        'scientific_article',
        'study_registry',
        'technical_report',
        'technical_standard',
        'unclassified',
        'work_program',
    }
)
ALLOWED_TEMPORAL_ROLES = frozenset(
    {
        'approved_plan',
        'current_fact',
        'current_plan',
        'historical_actual',
        'not_temporal',
        'proposed_plan',
        'unspecified',
    }
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f'{prefix}-{_sha256(chr(31).join(map(str, parts)))[:24]}'


def _as_sequence(value: Any) -> list[Any]:
    if value in (None, ''):
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(',') if part.strip()]
        return list(parsed) if isinstance(parsed, list) else [parsed]
    return [value]


def _json_scalar(values: Iterable[Any]) -> str:
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    return json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))


def _bounded_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_METADATA_VALUE_CHARS:
        return None
    return normalized


def _bounded_strings(value: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in _as_sequence(value):
        normalized = _bounded_string(item)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
        if len(values) >= MAX_METADATA_VALUES:
            break
    return values


def extract_parent_child_ingestion_metadata(file_metadata: Any) -> dict[str, Any]:
    """Extract only trusted GeoMAS indexing fields from uploaded file metadata.

    Open WebUI stores multipart ``metadata`` under ``file.meta.data``. The
    allowlist deliberately excludes loader locators, file identity, internal
    parent text and annotation offsets so an upload cannot overwrite lineage
    produced from the actual extracted document.
    """
    if not isinstance(file_metadata, dict):
        return {}
    nested = file_metadata.get('data')
    candidates = {
        **file_metadata,
        **(nested if isinstance(nested, dict) else {}),
    }
    output: dict[str, Any] = {}
    for key in ('document_id', 'document_version'):
        normalized = _bounded_string(candidates.get(key))
        if normalized is not None:
            output[key] = normalized
    for key in ('object_ids', 'domain_facets'):
        normalized = _bounded_strings(candidates.get(key))
        if normalized:
            output[key] = normalized
    source_class = _bounded_string(candidates.get('source_class'))
    if source_class in ALLOWED_SOURCE_CLASSES:
        output['source_class'] = source_class
    temporal_role = _bounded_string(candidates.get('temporal_role'))
    if temporal_role in ALLOWED_TEMPORAL_ROLES:
        output['temporal_role'] = temporal_role
    return output


def documents_have_parent_child_lineage(documents: list[Document]) -> bool:
    """Return true only when every document is an already finalized child."""
    return bool(documents) and all(
        document.metadata.get('child_chunk_id')
        and document.metadata.get('parent_chunk_id')
        and document.metadata.get('document_id')
        and document.metadata.get('document_version')
        for document in documents
    )


def _section_path(metadata: dict[str, Any]) -> str:
    existing = metadata.get('section_path')
    if existing:
        return str(existing)
    headings = [metadata.get(f'Header {level}') for level in range(1, 7)]
    return ' > '.join(str(value).strip() for value in headings if value) or 'document'


def _annotation_spans(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = _as_sequence(metadata.get('annotation_spans'))
    return [value for value in values if isinstance(value, dict)]


def _atomic_ranges(metadata: dict[str, Any]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for value in _as_sequence(metadata.get('atomic_ranges')):
        if not isinstance(value, dict):
            continue
        start, end = value.get('start'), value.get('end')
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
            ranges.append((start, end))
    for span in _annotation_spans(metadata):
        if not (span.get('atomic') or span.get('unit_kind') in {'resource_row', 'grr_row', 'table_row'}):
            continue
        start, end = span.get('start'), span.get('end')
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
            ranges.append((start, end))
    return sorted(set(ranges))


def _facet_counts(spans: Iterable[dict[str, Any]], start: int, end: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for span in spans:
        span_start, span_end = span.get('start'), span.get('end')
        if not isinstance(span_start, int) or not isinstance(span_end, int):
            continue
        if max(start, span_start) >= min(end, span_end):
            continue
        labels = span.get('labels') or span.get('domain_facets') or []
        for label in _as_sequence(labels):
            if str(label).strip():
                counts[str(label).strip()] += 1
    return counts


def _coverage_scalar(counts: Counter[str]) -> str:
    return json.dumps(dict(sorted(counts.items())), ensure_ascii=False, separators=(',', ':'))


def _non_whitespace_map(value: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    offsets: list[int] = []
    for offset, char in enumerate(value):
        if not char.isspace():
            chars.append(char)
            offsets.append(offset)
    return ''.join(chars), offsets


def _locate_normalized(
    parent_text: str, child_text: str, cursor: int
) -> tuple[int, int, int, list[int], list[int]] | None:
    parent_normalized, parent_offsets = _non_whitespace_map(parent_text)
    child_normalized, child_offsets = _non_whitespace_map(child_text)
    if not child_normalized:
        return None
    normalized_cursor = bisect_left(parent_offsets, cursor)
    normalized_start = parent_normalized.find(child_normalized, normalized_cursor)
    if normalized_start < 0:
        normalized_start = parent_normalized.find(child_normalized)
    if normalized_start < 0:
        return None
    normalized_end = normalized_start + len(child_normalized)
    start = parent_offsets[normalized_start]
    end = parent_offsets[normalized_end - 1] + 1
    return start, end, normalized_start, parent_offsets, child_offsets


def _rebase_offset(
    original_offset: int,
    normalized_start: int,
    parent_offsets: list[int],
    child_offsets: list[int],
    child_length: int,
) -> int:
    relative = bisect_left(parent_offsets, original_offset) - normalized_start
    if relative <= 0:
        return 0
    if relative >= len(child_offsets):
        return child_length
    return child_offsets[relative]


def preserve_split_metadata(parent: Document, split_chunks: list[Document]) -> list[Document]:
    """Preserve header metadata and rebase document-level annotation offsets."""
    output: list[Document] = []
    cursor = 0
    annotations = _annotation_spans(parent.metadata)
    atomic_ranges = _atomic_ranges(parent.metadata)
    for chunk in split_chunks:
        start = parent.page_content.find(chunk.page_content, cursor)
        if start < 0:
            start = parent.page_content.find(chunk.page_content)
        normalized_location = None
        if start >= 0:
            end = start + len(chunk.page_content)
        else:
            normalized_location = _locate_normalized(parent.page_content, chunk.page_content, cursor)
            start, end = normalized_location[:2] if normalized_location else (0, len(parent.page_content))
        located = start >= 0 and (normalized_location is not None or parent.page_content.find(chunk.page_content) >= 0)
        cursor = end
        metadata = {**parent.metadata, **chunk.metadata}
        metadata['section_start_index'] = start
        metadata['annotation_locator_status'] = 'located' if located else 'unresolved'
        if annotations:

            def rebase(offset: int) -> int:
                if normalized_location is None:
                    return max(0, min(len(chunk.page_content), offset - start))
                return _rebase_offset(
                    offset,
                    normalized_location[2],
                    normalized_location[3],
                    normalized_location[4],
                    len(chunk.page_content),
                )

            metadata['annotation_spans'] = [
                {
                    **span,
                    'start': rebase(int(span['start'])),
                    'end': rebase(int(span['end'])),
                }
                for span in annotations
                if isinstance(span.get('start'), int)
                and isinstance(span.get('end'), int)
                and max(start, span['start']) < min(end, span['end'])
            ]
        if atomic_ranges:
            metadata['atomic_ranges'] = [
                {
                    'start': rebase(range_start) if annotations else max(0, range_start - start),
                    'end': rebase(range_end) if annotations else min(len(chunk.page_content), range_end - start),
                }
                for range_start, range_end in atomic_ranges
                if max(start, range_start) < min(end, range_end)
            ]
        output.append(Document(page_content=chunk.page_content, metadata=metadata))
    return output


def prepare_parent_documents(documents: list[Document]) -> list[Document]:
    """Attach stable parent identity and normalized evidence metadata.

    ``annotation_spans`` and ``atomic_ranges`` are interpreted relative to the
    supplied parent document. Markdown sections must therefore be materialized
    before this function is called.
    """
    parents: list[Document] = []
    for document in documents:
        source_metadata = dict(document.metadata or {})
        text = document.page_content
        document_hash = _sha256(text)
        identity = (
            source_metadata.get('document_id')
            or source_metadata.get('file_id')
            or source_metadata.get('source')
            or source_metadata.get('name')
            or document_hash
        )
        document_id = str(source_metadata.get('document_id') or _stable_id('document', identity))
        document_version = str(source_metadata.get('document_version') or source_metadata.get('hash') or document_hash)
        section_path = _section_path(source_metadata)
        raw_page = source_metadata.get('page', source_metadata.get('page_number', -1))
        page = source_metadata.get('page_label', source_metadata.get('page_number', raw_page))
        if not isinstance(page, int | str):
            page = -1
        parent_chunk_id = _stable_id('parent', document_id, document_version, page, section_path, document_hash)
        annotations = _annotation_spans(source_metadata)
        source_facets = _as_sequence(source_metadata.get('domain_facets'))
        parent_counts = _facet_counts(annotations, 0, len(text))
        parent_facets = set(map(str, source_facets)) | set(parent_counts)
        metadata = {
            **source_metadata,
            'document_id': document_id,
            'document_version': document_version,
            'document_sha256': document_hash,
            'page': page,
            'source_page_index': raw_page,
            'page_locator_status': 'provided' if page != -1 else 'unknown',
            'section_path': section_path,
            'parent_chunk_id': parent_chunk_id,
            'object_ids': _json_scalar(_as_sequence(source_metadata.get('object_ids'))),
            'domain_facets': _json_scalar(parent_facets),
            'parent_domain_facets': _json_scalar(parent_facets),
            'parent_facet_coverage': _coverage_scalar(parent_counts),
            'source_class': str(source_metadata.get('source_class') or 'unclassified'),
            'temporal_role': str(source_metadata.get('temporal_role') or 'unspecified'),
            '_rag_parent_text': text,
            '_rag_annotation_spans': annotations,
            '_rag_atomic_ranges': _atomic_ranges(source_metadata),
            '_rag_source_facets': source_facets,
        }
        parents.append(Document(page_content=text, metadata=metadata))
    return parents


def _expand_to_atomic_ranges(start: int, end: int, ranges: list[tuple[int, int]]) -> tuple[int, int]:
    changed = True
    while changed:
        changed = False
        for range_start, range_end in ranges:
            if max(start, range_start) < min(end, range_end) and (range_start < start or range_end > end):
                start, end = min(start, range_start), max(end, range_end)
                changed = True
    return start, end


def _bounded_parent_context(text: str, child_start: int, child_end: int, max_chars: int) -> tuple[str, int, int]:
    if len(text) <= max_chars:
        return text, 0, len(text)
    child_end = min(max(child_end, child_start), len(text))
    child_start = min(max(child_start, 0), child_end)
    required = child_end - child_start
    if required >= max_chars:
        return text[child_start : child_start + max_chars], child_start, min(child_start + max_chars, len(text))
    remaining = max_chars - required
    context_start = max(0, child_start - remaining // 2)
    context_end = min(len(text), context_start + max_chars)
    context_start = max(0, context_end - max_chars)
    return text[context_start:context_end], context_start, context_end


def finalize_child_documents(
    parent: Document,
    children: list[Document],
    max_parent_context_chars: int = DEFAULT_PARENT_CONTEXT_MAX_CHARS,
) -> list[Document]:
    """Expand explicit atomic rows, assign child IDs, and attach bounded parent context."""
    parent_text = str(parent.metadata.get('_rag_parent_text', parent.page_content))
    annotations = list(parent.metadata.get('_rag_annotation_spans') or [])
    atomic_ranges = list(parent.metadata.get('_rag_atomic_ranges') or [])
    output: list[Document] = []
    seen: set[tuple[int, int]] = set()
    for child in children:
        metadata = {**parent.metadata, **(child.metadata or {})}
        raw_start = metadata.get('start_index', 0)
        start = raw_start if isinstance(raw_start, int) and raw_start >= 0 else 0
        end = min(len(parent_text), start + len(child.page_content))
        start, end = _expand_to_atomic_ranges(start, end, atomic_ranges)
        if (start, end) in seen:
            continue
        seen.add((start, end))
        child_text = parent_text[start:end]
        child_hash = _sha256(child_text)
        coverage = _facet_counts(annotations, start, end)
        source_facets = _as_sequence(parent.metadata.get('_rag_source_facets'))
        child_facets = set(map(str, source_facets)) | set(coverage)
        parent_context, context_start, context_end = _bounded_parent_context(
            parent_text, start, end, max_parent_context_chars
        )
        for key in INTERNAL_KEYS | {'annotation_spans', 'atomic_ranges'}:
            metadata.pop(key, None)
        metadata.update(
            {
                'start_index': start,
                'end_index': end,
                'child_chunk_id': _stable_id('child', metadata['parent_chunk_id'], start, end, child_hash),
                'child_sha256': child_hash,
                'domain_facets': _json_scalar(child_facets),
                'child_domain_facets': _json_scalar(child_facets),
                'child_facet_coverage': _coverage_scalar(coverage),
                'parent_context': parent_context,
                'parent_context_start': context_start,
                'parent_context_end': context_end,
                'parent_context_sha256': _sha256(parent_context),
            }
        )
        output.append(Document(page_content=child_text, metadata=metadata))
    return output


def split_parent_documents(
    parents: list[Document],
    text_splitter,
    max_parent_context_chars: int = DEFAULT_PARENT_CONTEXT_MAX_CHARS,
) -> list[Document]:
    children: list[Document] = []
    for parent in parents:
        split = text_splitter.split_documents([parent])
        children.extend(finalize_child_documents(parent, split, max_parent_context_chars))
    return children


def expand_parent_context_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep child ranking scores while returning one bounded context per parent."""
    if not result or not result.get('documents') or not result.get('metadatas'):
        return result
    documents = result['documents'][0] if result['documents'] else []
    metadatas = result['metadatas'][0] if result['metadatas'] else []
    distances = result.get('distances', [[]])[0] if result.get('distances') else []
    expanded_documents: list[str] = []
    expanded_metadata: list[dict[str, Any]] = []
    expanded_distances: list[Any] = []
    seen_parents: set[str] = set()
    for index, (document, metadata) in enumerate(zip(documents, metadatas)):
        metadata = dict(metadata or {})
        parent_id = metadata.get('parent_chunk_id')
        parent_context = metadata.get('parent_context')
        if not parent_id or not isinstance(parent_context, str):
            dedupe_key = f'legacy:{index}'
            context = document
        else:
            dedupe_key = str(parent_id)
            context = parent_context
            metadata['ranked_child_sha256'] = _sha256(str(document))
            metadata['context_expanded_to_parent'] = True
        if dedupe_key in seen_parents:
            continue
        seen_parents.add(dedupe_key)
        expanded_documents.append(context)
        expanded_metadata.append(metadata)
        expanded_distances.append(distances[index] if index < len(distances) else None)
    return {
        **result,
        'documents': [expanded_documents],
        'metadatas': [expanded_metadata],
        'distances': [expanded_distances],
    }
