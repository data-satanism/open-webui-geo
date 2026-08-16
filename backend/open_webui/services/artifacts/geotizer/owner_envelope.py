"""The GeoTeaser owner envelope: batching, extraction, merge and repair.

CORE-BOUNDARY-01 action 2. GeoTeaser-specific logic lives here and nowhere
else.
"""

from __future__ import annotations

import json
import logging
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
from ...core.tasks import (
    AgentKind,
    AgentTask,
    PRODUCER_AGENT_KIND,
    infer_agent_kind,
)
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


# The first logger in `services/`. The boundary this tree defends is the
# `open_webui` import, not the standard library, and the alternative to a log
# line here is swallowing a contract mismatch silently -- which is the one
# outcome this whole file exists to prevent.
log = logging.getLogger(__name__)


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
    """Map a `gis_service` producer name to the agent kind that serves it.

    The table is the contract; the inference behind it is the fallback the
    deployed Workspace Tool has had all along, and it is load-bearing rather
    than decorative. `PRODUCER_AGENT_KIND` names producers this repository does
    not own, so the day the service adds one, a strict lookup fails the run at
    its first batch -- and it fails on a string, having retrieved nothing.
    """
    mapped = PRODUCER_AGENT_KIND.get(producer)
    if mapped is not None:
        return mapped
    inferred = infer_agent_kind(producer)
    if inferred is not None:
        log.info(
            'Producer %r is not in PRODUCER_AGENT_KIND; inferred kind %r. Add it '
            'to the table to make this explicit.',
            producer,
            inferred,
        )
        return inferred
    raise GeotizerOrchestrationError(
        f'Unsupported GeoTeaser producer: {producer}. '
        f'Known: {sorted(PRODUCER_AGENT_KIND)}'
    )


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
    feedback_by_attempt: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fail closed while preserving individually valid owner decisions.

    `feedback` is the last attempt's violations and `feedback_by_attempt` is all
    of them. The distinction cost a diagnosis: in run `5880a164` the
    `KB-GRR-FACTORS` chunk returned 9,372 characters, then 11,687 characters
    carrying a real `patches`/`source_inventory` envelope, then nothing -- and
    the card reported only `Agent returned an empty response`, because that was
    the third attempt's feedback and the first two had been overwritten. The
    violation that actually rejected a well-formed envelope was not recorded
    anywhere, so the histogram of what the contract refuses could not be built.
    """
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
                    # Every attempt's violations, not only the last. Without it
                    # a chunk that was rejected for a real contract reason and
                    # then returned nothing reports only the empty response.
                    'owner_attempt_feedback': [dict(item) for item in feedback_by_attempt],
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


# -- making the inventory submittable ----------------------------------------

# What an owner's `source_domain` means in the submission schema's vocabulary.
# `derived` is the fallback rather than `unknown`, because a source the owner
# produced from other sources is what an unattributed entry almost always is,
# and `unknown` would be a claim about the source rather than about our
# knowledge of it.
_DOMAIN_TO_SOURCE_TYPE = {
    'gis': 'gis',
    'web': 'web',
    'kb': 'knowledge_base',
    'knowledge_base': 'knowledge_base',
    'vision': 'vision',
}


def normalize_source_inventory(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Coerce owner sources to the submission schema, then deduplicate.

    Ported from the deployed Workspace Tool `geoteaser 2.2.0`
    (`GMM/operations/workspace-exports/geoteaser.py:3284`). Register A-04: the
    repaired version was in the production Tool and the broken one here, so a
    merge that took this repository's side would have reintroduced the defect.

    GIS requires `source_id`, `source_type` and `title`. This repository's
    `merge_owner_envelopes` copies each entry through and only re-namespaces the
    id, and the local validator only ever harvested `source_id` -- so an owner
    that serialized its contributor evidence as sources, carrying `producer`,
    `source_domain` and `source_locator` instead, passed every local check and
    was rejected with HTTP 422 at submission, after the whole batch had been
    built.

    Repairing rather than dropping keeps provenance that would otherwise be
    lost: the owner had the evidence, it just wrote it under the wrong schema.
    Returns `(envelope, notes)`; the notes are surfaced as run degradations,
    because a card built on rebuilt source metadata is not the same as one built
    on metadata the owner got right.
    """
    raw_sources = envelope.get('source_inventory')
    if not isinstance(raw_sources, list) or not raw_sources:
        return dict(envelope), []

    notes: list[str] = []
    repaired: list[dict[str, Any]] = []
    canonical: dict[str, str] = {}  # original source_id -> kept source_id
    by_identity: dict[tuple, str] = {}  # content -> kept source_id
    coerced = 0

    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            continue
        source_id = str(raw.get('source_id') or '').strip()
        if not source_id:
            continue

        locator = raw.get('locator')
        if locator in (None, '', {}, []):
            locator = raw.get('source_locator')
        if isinstance(locator, Mapping | list):
            locator = json.dumps(locator, ensure_ascii=False, sort_keys=True)

        source_type = str(raw.get('source_type') or '').strip()
        if not source_type:
            domain = str(raw.get('source_domain') or '').strip().lower()
            source_type = _DOMAIN_TO_SOURCE_TYPE.get(domain, 'derived')

        # Fall back through the fields that actually identify the source. The
        # source_id is last: it carries the chunk and attempt suffixes that make
        # otherwise identical entries look distinct and defeat deduplication.
        title = str(raw.get('title') or '').strip()
        if not title:
            producer = str(raw.get('producer') or '').strip()
            note = ' '.join(str(raw.get('retrieval_note') or '').split())[:120]
            title = f'{producer} evidence' if producer else note or source_id

        source = {
            'source_id': source_id,
            'source_type': source_type,
            'title': title,
            'locator': str(locator or ''),
            'url': raw.get('url'),
        }
        if any(key not in raw or raw.get(key) in (None, '') for key in ('source_type', 'title')):
            coerced += 1

        identity = (
            source['source_type'],
            source['title'],
            source['locator'],
            str(source['url'] or ''),
        )
        existing = by_identity.get(identity)
        if existing is not None:
            canonical[source_id] = existing
            continue
        by_identity[identity] = source_id
        canonical[source_id] = source_id
        repaired.append(source)

    dropped = len(raw_sources) - len(repaired) - sum(1 for k, v in canonical.items() if k != v)
    duplicates = sum(1 for k, v in canonical.items() if k != v)
    if coerced:
        notes.append(
            f'{coerced} owner source entries were missing source_type or title '
            'and were rebuilt from their evidence fields'
        )
    if duplicates:
        notes.append(f'{duplicates} duplicate source entries were merged')
    if dropped > 0:
        notes.append(f'{dropped} source entries had no source_id and were dropped')

    patches = []
    for patch in envelope.get('patches') or []:
        if not isinstance(patch, Mapping):
            continue
        refs = [str(ref) for ref in patch.get('source_refs') or []]
        remapped: list[str] = []
        for ref in refs:
            target = canonical.get(ref, ref)
            if target not in remapped:
                remapped.append(target)
        patches.append({**dict(patch), 'source_refs': remapped} if refs else dict(patch))

    return {**dict(envelope), 'source_inventory': repaired, 'patches': patches}, notes
