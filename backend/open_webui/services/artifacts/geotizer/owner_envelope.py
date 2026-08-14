"""The GeoTeaser owner envelope: batching, extraction, merge and repair.

CORE-BOUNDARY-01 action 2. GeoTeaser-specific logic lives here and nowhere
else.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from ...geotizer.errors import GeotizerOrchestrationError
from ...project_evidence.retrieval import (
    build_retrieval_plans,
)
from .validation import (
    _contract_violations,
    _partition_violations,
    validate_owner_envelope,
)
from ...core.tasks import AgentKind, AgentTask, PRODUCER_AGENT_KIND
from ...core.text import (
    _decode_embedded_objects,
    _is_nonstring_sequence,
    _strip_json_fence,
    bounded_text,
    extract_json_object,
)
from ...project_evidence.proposals import (
    _review_hypothesis,
    normalize_contributor_evidence,
)


MAX_RECOVERED_TOOL_OUTPUT_CHARS = 20_000


def execution_mode_for_task(
    task: AgentTask,
) -> Literal[
    'specialist_contributor',
    'specialist_owner_completion',
    'tool_free_owner',
]:
    """Keep state-changing tools outside every bounded owner decision."""
    if task.role == 'owner' and task.kind == 'skilled':
        return 'tool_free_owner'
    if task.role == 'owner':
        return 'specialist_owner_completion'
    return 'specialist_contributor'


def agent_kind_for_producer(producer: str) -> AgentKind:
    try:
        return PRODUCER_AGENT_KIND[producer]
    except KeyError as exc:
        raise GeotizerOrchestrationError(f'Unsupported GeoTeaser producer: {producer}') from exc


def build_batch_tasks(next_batch: Mapping[str, Any]) -> tuple[AgentTask, ...]:
    """Plan contributor calls before the single exact owner call."""
    batch_id = str(next_batch.get('batch_id') or '')
    owner = str(next_batch.get('producer') or '')
    if not batch_id or not owner:
        raise GeotizerOrchestrationError('next_batch must contain batch_id and producer')

    tasks: list[AgentTask] = []
    seen_routes: set[str] = set()
    for route in next_batch.get('evidence_routes') or []:
        if route.get('satisfied_by') != 'contributor_call':
            continue
        route_id = str(route.get('route_id') or '')
        producer = str(route.get('producer') or '')
        if not route_id or route_id in seen_routes:
            raise GeotizerOrchestrationError(f'Invalid or duplicate evidence route in batch {batch_id}')
        seen_routes.add(route_id)
        tasks.append(
            AgentTask(
                kind=agent_kind_for_producer(producer),
                producer=producer,
                role='contributor',
                task_id=route_id,
                payload=dict(route),
            )
        )

    tasks.append(
        AgentTask(
            kind=agent_kind_for_producer(owner),
            producer=owner,
            role='owner',
            task_id=batch_id,
            payload=dict(next_batch),
        )
    )
    return tuple(tasks)


def partition_owner_batch(
    next_batch: Mapping[str, Any],
    *,
    max_fields: int,
) -> tuple[dict[str, Any], ...]:
    """Split one GIS-owned batch into bounded LLM calls without changing ownership."""
    if max_fields < 1:
        raise GeotizerOrchestrationError('max_fields must be positive')
    fields = [dict(field) for field in next_batch.get('fields') or []]
    if not fields:
        return (dict(next_batch),)

    total = (len(fields) + max_fields - 1) // max_fields
    chunks: list[dict[str, Any]] = []
    for offset in range(0, len(fields), max_fields):
        chunk_fields = fields[offset : offset + max_fields]
        field_keys = {str(field.get('field_key') or '') for field in chunk_fields}
        row_ids = {field.get('row_id') for field in chunk_fields}
        evidence_routes = []
        for route in next_batch.get('evidence_routes') or []:
            declared_keys = [str(field_key) for field_key in route.get('field_keys') or []]
            route_keys = (
                [field_key for field_key in declared_keys if field_key in field_keys]
                if declared_keys
                else sorted(field_keys)
            )
            if not route_keys:
                continue
            declared_rows = list(route.get('row_ids') or [])
            evidence_routes.append(
                {
                    **dict(route),
                    'field_keys': route_keys,
                    'row_ids': [
                        row_id for row_id in (declared_rows if declared_rows else sorted(row_ids)) if row_id in row_ids
                    ],
                }
            )
        index = len(chunks) + 1
        chunks.append(
            {
                **dict(next_batch),
                'fields': chunk_fields,
                'field_count': len(chunk_fields),
                'evidence_routes': evidence_routes,
                'owner_chunk': {'index': index, 'total': total},
            }
        )
    return tuple(chunks)


def merge_owner_envelopes(
    next_batch: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Merge validated chunk envelopes into one atomic GIS batch submission."""
    if len(chunks) != len(envelopes) or not chunks:
        raise GeotizerOrchestrationError('Owner chunks and envelopes must form one non-empty partition')

    sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    patches: list[dict[str, Any]] = []
    for chunk_index, (chunk, envelope) in enumerate(
        # The guard above already refuses a ragged partition; `strict` keeps the
        # two statements from drifting apart.
        zip(chunks, envelopes, strict=True),
        start=1,
    ):
        violations = validate_owner_envelope(chunk, envelope)
        if violations:
            raise GeotizerOrchestrationError('; '.join(violations))

        renamed_refs: dict[str, str] = {}
        batch_namespace = str(next_batch.get('batch_id') or '').lower()
        for raw_source in envelope.get('source_inventory') or []:
            source = dict(raw_source)
            source_id = str(source.get('source_id') or '')
            candidate = f'{batch_namespace}__part_{chunk_index}__{source_id}'
            suffix = 2
            while candidate in source_by_id:
                candidate = f'{batch_namespace}__part_{chunk_index}__{source_id}__{suffix}'
                suffix += 1
            source['source_id'] = candidate
            source_by_id[candidate] = source
            sources.append(source)
            renamed_refs[source_id] = candidate

        for raw_patch in envelope.get('patches') or []:
            patch = dict(raw_patch)
            patch['source_refs'] = [
                renamed_refs.get(str(source_ref), str(source_ref)) for source_ref in patch.get('source_refs') or []
            ]
            patches.append(patch)

    merged = {
        'run_id': run_id,
        'batch_id': next_batch['batch_id'],
        'producer': next_batch['producer'],
        'policy_version': next_batch['policy_version'],
        'template_version': next_batch['template_version'],
        'source_inventory': sources,
        'patches': patches,
    }
    violations = validate_owner_envelope(next_batch, merged)
    if violations:
        raise GeotizerOrchestrationError('; '.join(violations))
    return merged


def owner_failure_envelope(
    next_batch: Mapping[str, Any],
    *,
    run_id: str,
    attempts: int,
    feedback: Sequence[Any],
    object_name: str = '',
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
    candidate_envelopes: Sequence[Mapping[str, Any]] = (),
    attempt_diagnostics: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fail closed while preserving individually valid owner decisions."""
    chunk = next_batch.get('owner_chunk') or {}
    chunk_index = int(chunk.get('index') or 1)
    chunk_total = int(chunk.get('total') or 1)
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    source_id = f'orchestration-review-{batch_id.lower()}-part-{chunk_index}'
    locator = f'run_id={run_id}; batch_id={batch_id}; owner_chunk={chunk_index}/{chunk_total}; attempts={attempts}'
    feedback_text = bounded_text(
        json.dumps(list(feedback), ensure_ascii=False),
        max_chars=1200,
    )
    fallback = {
        'run_id': run_id,
        'batch_id': batch_id,
        'producer': producer,
        'policy_version': str(next_batch.get('policy_version') or ''),
        'template_version': str(next_batch.get('template_version') or ''),
        'source_inventory': [
            {
                'source_id': source_id,
                'source_type': 'orchestration',
                'title': (f'{producer} owner output failed deterministic validation for {batch_id}'),
                'locator': locator,
                'url': None,
            }
        ],
        'patches': [
            {
                'field_key': str(field.get('field_key') or ''),
                'value': None,
                'unit': None,
                'status': 'requires_expert_review',
                'source_refs': [source_id],
                'source_locator': {
                    'run_id': run_id,
                    'batch_id': batch_id,
                    'owner_chunk': f'{chunk_index}/{chunk_total}',
                    'attempts': attempts,
                    'owner_attempt_diagnostics': [dict(item) for item in attempt_diagnostics],
                },
                'retrieval_note': (
                    'Specialist evidence was requested, but the owner response '
                    'did not satisfy the deterministic field contract after '
                    f'{attempts} attempts. Validation feedback: {feedback_text}'
                ),
            }
            for field in next_batch.get('fields') or []
        ],
    }
    if batch_id == 'ASSEMBLE':
        for field, patch in zip(
            next_batch.get('fields') or [],
            # Built from the same field list a few lines above, one patch each.
            fallback['patches'],
            strict=True,
        ):
            patch['value'] = _review_hypothesis(
                field,
                object_name=object_name,
                accepted_field_summary=accepted_field_summary,
            )
            patch['retrieval_note'] = (
                f'{patch["retrieval_note"]} The displayed hypothesis is a '
                'review draft, not an accepted factual value; validate it '
                'against the cited GIS, KB, WEB and DataCube evidence.'
            )

    return _salvage_owner_candidates(
        next_batch,
        fallback,
        candidate_envelopes,
    )


def _salvage_owner_candidates(
    next_batch: Mapping[str, Any],
    fallback: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Keep valid per-field patches even when the complete envelope is invalid."""
    result = {
        **dict(fallback),
        'source_inventory': [dict(source) for source in fallback.get('source_inventory') or []],
        'patches': [dict(patch) for patch in fallback.get('patches') or []],
    }
    field_by_key = {str(field.get('field_key') or ''): dict(field) for field in next_batch.get('fields') or []}
    patch_by_key = {str(patch.get('field_key') or ''): patch for patch in result['patches']}
    accepted: set[str] = set()

    for attempt, candidate in reversed(tuple(enumerate(candidates, start=1))):
        inventory = {
            str(source.get('source_id') or ''): dict(source)
            for source in candidate.get('source_inventory') or []
            if isinstance(source, Mapping) and str(source.get('source_id') or '')
        }
        for raw_patch in candidate.get('patches') or []:
            if not isinstance(raw_patch, Mapping):
                continue
            field_key = str(raw_patch.get('field_key') or '')
            if field_key in accepted or field_key not in field_by_key:
                continue
            if (
                str(next_batch.get('batch_id') or '') == 'ASSEMBLE'
                and raw_patch.get('status') == 'requires_expert_review'
                and raw_patch.get('value') in (None, '')
            ):
                continue

            refs = [str(source_ref) for source_ref in raw_patch.get('source_refs') or []]
            if not refs or any(source_ref not in inventory for source_ref in refs):
                continue
            renamed = {
                source_ref: (f'salvage-{str(next_batch.get("batch_id") or "").lower()}-attempt-{attempt}__{source_ref}')
                for source_ref in refs
            }
            patch = {
                **dict(raw_patch),
                'source_refs': [renamed[source_ref] for source_ref in refs],
            }
            sources = []
            for source_ref in refs:
                source = dict(inventory[source_ref])
                source['source_id'] = renamed[source_ref]
                sources.append(source)
            one_field_batch = {
                **dict(next_batch),
                'fields': [field_by_key[field_key]],
                'field_count': 1,
            }
            one_field_envelope = {
                'run_id': result.get('run_id'),
                'batch_id': next_batch.get('batch_id'),
                'producer': next_batch.get('producer'),
                'policy_version': next_batch.get('policy_version'),
                'template_version': next_batch.get('template_version'),
                'source_inventory': sources,
                'patches': [patch],
            }
            if validate_owner_envelope(one_field_batch, one_field_envelope):
                continue
            patch_by_key[field_key].update(patch)
            result['source_inventory'].extend(sources)
            accepted.add(field_key)
    return result


def extract_owner_envelope(
    text: str,
    next_batch: Mapping[str, Any],
) -> dict[str, Any]:
    """Select one structurally exact owner envelope among incidental JSON objects."""
    try:
        return extract_json_object(text)
    except GeotizerOrchestrationError as original_error:
        if not isinstance(text, str) or not text.strip():
            raise
        candidates = _decode_embedded_objects(_strip_json_fence(text))
        expected_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
        matching = []
        for candidate in candidates:
            violations = _contract_violations(next_batch, candidate)
            patches = candidate.get('patches')
            if not isinstance(patches, list):
                continue
            violations.extend(_partition_violations(expected_keys, patches))
            if not violations:
                matching.append(candidate)
        unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in matching}
        if len(unique) == 1:
            return next(iter(unique.values()))
        raise GeotizerOrchestrationError(
            'Agent response must contain exactly one structurally exact '
            f'owner JSON object; matching_candidates={len(unique)}'
        ) from original_error


def recover_backend_owned_owner_envelope(
    text: str,
    next_batch: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any] | None:
    """Recover patches while keeping envelope identity backend-owned."""
    candidates = _owner_payload_candidates(text)
    if not candidates:
        return None

    expected_keys = {str(field.get('field_key') or '') for field in next_batch.get('fields') or []}
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        patches = candidate.get('patches')
        if patches is None:
            patches = candidate.get('field_patches')
        if patches is None:
            patches = candidate.get('decisions')
        if not _is_nonstring_sequence(patches):
            continue
        patch_list = [dict(patch) for patch in patches if isinstance(patch, Mapping)]
        if not patch_list and patches:
            continue

        inventory = candidate.get('source_inventory')
        if inventory is None:
            inventory = candidate.get('sources')
        inventory_list = (
            [dict(source) for source in inventory if isinstance(source, Mapping)]
            if _is_nonstring_sequence(inventory)
            else []
        )
        recognized = sum(1 for patch in patch_list if str(patch.get('field_key') or '') in expected_keys)
        recovered = {
            'run_id': run_id,
            'batch_id': str(next_batch.get('batch_id') or ''),
            'producer': str(next_batch.get('producer') or ''),
            'policy_version': str(next_batch.get('policy_version') or ''),
            'template_version': str(next_batch.get('template_version') or ''),
            'source_inventory': inventory_list,
            'patches': patch_list,
        }
        ranked.append((recognized, -index, recovered))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def _owner_payload_candidates(text: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(text, str) or not text.strip():
        return ()
    stripped = _strip_json_fence(text)
    candidates: list[dict[str, Any]] = []
    pending = [(root, 0) for root in _owner_payload_roots(stripped)]
    while pending:
        value, depth = pending.pop()
        if depth > 2:
            continue
        if isinstance(value, Mapping):
            own, nested = _mapping_owner_payloads(value)
            candidates.extend(own)
            pending.extend((item, depth + 1) for item in nested)
        elif _is_nonstring_sequence(value):
            own, nested = _sequence_owner_payloads(value)
            candidates.extend(own)
            pending.extend((item, depth + 1) for item in nested)
    unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in candidates}
    return tuple(unique.values())


def _owner_payload_roots(text: str) -> list[Any]:
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        return list(_decode_embedded_objects(text))


def _mapping_owner_payloads(
    value: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[Any]]:
    item = dict(value)
    recognized = (
        [item]
        if any(
            key in item
            for key in (
                'patches',
                'field_patches',
                'decisions',
                'field_proposals',
            )
        )
        else []
    )
    nested: list[Any] = []
    for key in ('result', 'data', 'output', 'owner_decision'):
        candidate = item.get(key)
        if isinstance(candidate, str):
            try:
                candidate = json.loads(_strip_json_fence(candidate))
            except json.JSONDecodeError:
                continue
        if candidate is not None:
            nested.append(candidate)
    return recognized, nested


def _sequence_owner_payloads(
    value: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[Any]]:
    values = list(value)
    if values and all(isinstance(item, Mapping) for item in values) and any('field_key' in item for item in values):
        return (
            [{'patches': [dict(item) for item in values]}],
            values,
        )
    return [], values


def extract_output_message_text(message: Mapping[str, Any]) -> str:
    """Normalize Open WebUI 0.10 output arrays into legacy message content."""
    content = message.get('content')
    if isinstance(content, str) and content.strip():
        return content.strip()

    output = message.get('output')
    if not isinstance(output, list):
        return ''
    for item in reversed(output):
        if not isinstance(item, Mapping) or item.get('type') != 'message':
            continue
        parts = item.get('content')
        if isinstance(parts, str) and parts.strip():
            return parts.strip()
        if not isinstance(parts, list):
            continue
        texts = [
            str(part.get('text')).strip()
            for part in parts
            if isinstance(part, Mapping)
            and part.get('type') in {'output_text', 'text'}
            and isinstance(part.get('text'), str)
            and str(part.get('text')).strip()
        ]
        if texts:
            return '\n'.join(texts)
    recovered_tool_outputs = _recover_function_call_outputs(output)
    if not recovered_tool_outputs:
        return ''
    return json.dumps(
        {
            'status': 'completed_with_tool_outputs',
            'tool_outputs': recovered_tool_outputs,
        },
        ensure_ascii=False,
    )


def _recover_function_call_outputs(
    output: Sequence[Any],
) -> list[dict[str, Any]]:
    """Preserve completed tool evidence when a sub-chat has no final message."""
    calls_by_id: dict[str, Mapping[str, Any]] = {}
    recovered: list[dict[str, Any]] = []
    remaining_chars = MAX_RECOVERED_TOOL_OUTPUT_CHARS
    for item in output:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get('type')
        call_id = str(item.get('call_id') or item.get('id') or '')
        if item_type == 'function_call':
            if call_id:
                calls_by_id[call_id] = item
            continue
        if item_type != 'function_call_output':
            continue

        call = calls_by_id.get(call_id, {})
        raw_text = _function_output_text(item.get('output'))
        if not raw_text:
            continue
        kept_text = raw_text[:remaining_chars]
        truncated = len(kept_text) < len(raw_text)
        recovered.append(
            {
                'tool_name': str(call.get('name') or ''),
                'call_id': call_id,
                'arguments': str(call.get('arguments') or ''),
                'output': kept_text,
                'truncated': truncated,
            }
        )
        remaining_chars -= len(kept_text)
        if remaining_chars <= 0:
            break
    return recovered


def _function_output_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(
        value,
        str | bytes | bytearray,
    ):
        texts = [
            str(item.get('text')).strip()
            for item in value
            if isinstance(item, Mapping)
            and item.get('type') in {'input_text', 'output_text', 'text'}
            and isinstance(item.get('text'), str)
            and str(item.get('text')).strip()
        ]
        if texts:
            return '\n'.join(texts)
    if value is None:
        return ''
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def promote_assemble_conclusions(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    accepted_field_summary: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Turn evidence-backed review drafts into explicit calculated conclusions."""
    if str(next_batch.get('batch_id') or '') != 'ASSEMBLE':
        return dict(envelope)
    accepted = [
        item
        for item in accepted_field_summary
        if isinstance(item, Mapping)
        and item.get('status') in {'filled', 'requires_expert_review'}
        and item.get('value') not in (None, '')
    ]
    if not accepted:
        return dict(envelope)

    row_by_key = {
        str(field.get('field_key') or ''): int(field.get('row_id') or 0) for field in next_batch.get('fields') or []
    }
    input_keys = [str(item.get('field_key') or '') for item in accepted[:12]]
    input_refs = sorted(
        {str(source_ref) for item in accepted[:12] for source_ref in item.get('source_refs') or [] if str(source_ref)}
    )
    result = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    for patch in result['patches']:
        field_key = str(patch.get('field_key') or '')
        if (
            row_by_key.get(field_key) not in {98, 99}
            or patch.get('status') != 'requires_expert_review'
            or not isinstance(patch.get('value'), str)
            or len(str(patch['value']).strip()) < 120
        ):
            continue
        text = str(patch['value']).strip()
        hypothesis_prefix = 'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ:'
        if text.casefold().startswith(hypothesis_prefix.casefold()):
            text = text[len(hypothesis_prefix) :].strip()
        patch.update(
            {
                'status': 'filled',
                'value': f'РАСЧЁТНОЕ ЗНАЧЕНИЕ: {text}',
                'value_origin': 'calculated',
                'source_locator': {
                    'operation': 'accepted_field_synthesis',
                    'prior_locator': patch.get('source_locator'),
                    'accepted_field_keys': input_keys,
                    'accepted_source_refs': input_refs,
                },
                'retrieval_note': (
                    'Calculated synthesis of the accepted field summary. '
                    'Inputs are enumerated in source_locator; the result is an '
                    'analytical conclusion, not a direct source quotation, and '
                    'must be reviewed when underlying fields change.'
                ),
            }
        )
    return result


def xlsx_download_path(state: Mapping[str, Any]) -> str:
    xlsx = state.get('xlsx')
    if not isinstance(xlsx, Mapping):
        raise GeotizerOrchestrationError('Final state has no XLSX artifact')
    path = str(xlsx.get('download_path') or '')
    if not path.startswith('/geotizer/files/') or not path.endswith('/geotizer.xlsx'):
        raise GeotizerOrchestrationError('Final state has an invalid XLSX path')
    return path


def compact_batch_context(
    next_batch: Mapping[str, Any],
    *,
    object_name: str,
    run_id: str,
    datacube: Mapping[str, Any] | None,
    contributor_evidence: Sequence[Mapping[str, Any]],
    knowledge_search_plan: Mapping[str, Any] | None = None,
    rag_v2_enabled: bool = False,
    rag_v2_collections: Sequence[str] = (),
    rag_v2_index_version: str | None = None,
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded context an owner needs; omit unrelated run state."""
    retrieval_plans = (
        build_retrieval_plans(
            next_batch,
            knowledge_search_plan,
            run_id=run_id,
            object_name=object_name,
            index_version=rag_v2_index_version,
            collections=rag_v2_collections,
        )
        if rag_v2_enabled and knowledge_search_plan and str(next_batch.get('producer') or '') == 'KBagent_yulong'
        else ()
    )
    return {
        'object_name': object_name,
        'run_id': run_id,
        'batch': dict(next_batch),
        'datacube': dict(datacube or {}),
        'knowledge_search_plan': dict(knowledge_search_plan or {}),
        'retrieval_plans': [plan.as_dict() for plan in retrieval_plans],
        'accepted_field_summary': [dict(item) for item in accepted_field_summary],
        'contributor_evidence': [normalize_contributor_evidence(item) for item in contributor_evidence],
    }


def build_accepted_field_summary(
    state: Mapping[str, Any],
    *,
    additional_patches: Sequence[Mapping[str, Any]] = (),
    max_chars: int = 40_000,
) -> tuple[dict[str, Any], ...]:
    """Expose bounded accepted facts to synthesis batches without full state."""
    records = [
        *_accepted_summary_records(state.get('fields') or []),
        *_accepted_summary_records(additional_patches),
    ]

    result: list[dict[str, Any]] = []
    size = 0
    seen: set[str] = set()
    for record in records:
        field_key = str(record.get('field_key') or '')
        if not field_key or field_key in seen:
            continue
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if result and size + len(encoded) > max_chars:
            break
        seen.add(field_key)
        result.append(record)
        size += len(encoded)
    return tuple(result)


def _accepted_summary_records(
    values: Sequence[Any],
) -> list[dict[str, Any]]:
    return [
        _summary_record(raw)
        for raw in values
        if isinstance(raw, Mapping)
        and raw.get('status') in {'filled', 'requires_expert_review'}
        and raw.get('value') not in (None, '')
    ]


def _summary_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'field_key': str(raw.get('field_key') or ''),
        'group': str(raw.get('group') or ''),
        'element': str(raw.get('element') or ''),
        'attribute_name': str(raw.get('attribute_name') or ''),
        'status': str(raw.get('status') or ''),
        'value': raw.get('value'),
        'unit': raw.get('unit'),
        'value_origin': raw.get('value_origin'),
        'source_refs': list(raw.get('source_refs') or []),
        'retrieval_note': bounded_text(
            str(raw.get('retrieval_note') or ''),
            max_chars=500,
        ),
    }
