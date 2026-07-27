"""Pure planning and validation for the GeoTeaser orchestration loop."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

AgentKind = Literal['gis', 'kb', 'web', 'skilled']

PRODUCER_AGENT_KIND: Mapping[str, AgentKind] = {
    'GISagent_yulong': 'gis',
    'KBagent_yulong': 'kb',
    'WEBagent_yulong': 'web',
    'SkilledAgent': 'skilled',
}

ALLOWED_FIELD_STATUSES = frozenset(
    {
        'filled',
        'not_found',
        'not_applicable',
        'conflicted',
        'requires_expert_review',
    }
)
ALLOWED_VALUE_ORIGINS = frozenset(
    {
        'direct',
        'calculated',
        'analogue',
    }
)
NEGATIVE_VALUE_MARKERS = frozenset(
    {
        'n/a',
        'na',
        'not found',
        'нет данных',
        'данные не найдены',
        'не найдено',
        'не найдено данных',
        'отсутствует',
    }
)
ANALOGUE_BASIS_MARKERS = (
    'analog',
    'analogue',
    'regional context',
    'regional geology',
    'месторождени-аналог',
    'месторождение-аналог',
    'по аналог',
    'региональн',
    'данным региона',
)
CALCULATED_BASIS_MARKERS = (
    'calculated',
    'derived',
    'inferred',
    'model prospectivity',
    'prospectivity',
    'выводн',
    'оценочн',
    'по модели',
    'по типу месторождения',
    'предполагаем',
    'расчет',
    'расчёт',
)
MAX_CONTRIBUTOR_EVIDENCE_CHARS = 20_000


class GeotizerOrchestrationError(ValueError):
    """Raised when the deterministic orchestration contract is violated."""


@dataclass(frozen=True)
class AgentTask:
    kind: AgentKind
    producer: str
    role: Literal['contributor', 'owner']
    task_id: str
    payload: Mapping[str, Any]


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


def owner_completion_valves(
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Disable every retrieval/tool path for an evidence-complete owner."""
    normalized = dict(values)
    overrides = {
        'use_ui_compatible_flow_for_builtin_agents': False,
        'ui_flow_agents': '',
        'gis_tool_ids': '',
        'web_tool_ids': '',
        'kb_tool_ids': '',
        'direct_tool_agents': '',
        'gis_openapi_base_url': '',
        'web_openapi_base_url': '',
        'kb_openapi_base_url': '',
        'enable_web_search_feature': False,
        'execute_kb_builtin_tools_in_process': False,
    }
    for name, value in overrides.items():
        if name in normalized:
            normalized[name] = value
    return normalized


@dataclass(frozen=True)
class GisObjectSearchProfile:
    """Bounded GIS-derived descriptors used to expand knowledge retrieval."""

    object_name: str
    project_id: str
    profile_status: Literal['ready', 'partial', 'unavailable']
    location_terms: tuple[str, ...]
    commodity_terms: tuple[str, ...]
    deposit_type_terms: tuple[str, ...]
    geology_terms: tuple[str, ...]
    evidence: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            'schema_version': 1,
            'profile_status': self.profile_status,
            'project_resolution': {
                'status': 'resolved',
                'project_id': self.project_id,
                'object_name': self.object_name,
                'authority': 'geotizer_start',
            },
            'location_terms': list(self.location_terms),
            'commodity_terms': list(self.commodity_terms),
            'deposit_type_terms': list(self.deposit_type_terms),
            'geology_terms': list(self.geology_terms),
            'evidence': [dict(item) for item in self.evidence],
            'diagnostics': list(self.diagnostics),
        }


@dataclass(frozen=True)
class GisFieldProposal:
    """Typed, locator-bound contributor proposal for one GeoTeaser field."""

    field_key: str
    value: Any
    unit: str | None
    value_origin: Literal['direct', 'calculated', 'analogue']
    relation_to_object: str
    source_id: str
    source_title: str
    source_locator: Any
    retrieval_note: str
    value_kind: str = ''
    temporal_role: str = ''
    entity_role: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {
            'field_key': self.field_key,
            'value': self.value,
            'unit': self.unit,
            'value_origin': self.value_origin,
            'relation_to_object': self.relation_to_object,
            'source_id': self.source_id,
            'source_title': self.source_title,
            'source_locator': self.source_locator,
            'retrieval_note': self.retrieval_note,
            'value_kind': self.value_kind,
            'temporal_role': self.temporal_role,
            'entity_role': self.entity_role,
        }


def normalize_gis_field_proposals(
    raw_output: str,
    *,
    allowed_field_keys: Sequence[str],
) -> tuple[GisFieldProposal, ...]:
    """Decode valid GIS proposals and ignore foreign or untraceable claims."""
    try:
        payload = extract_json_object(raw_output)
    except GeotizerOrchestrationError:
        return ()
    raw_proposals = payload.get('field_proposals')
    if (
        not isinstance(raw_proposals, Sequence)
        or isinstance(raw_proposals, str | bytes)
    ):
        return ()

    allowed = {str(field_key) for field_key in allowed_field_keys}
    proposals: list[GisFieldProposal] = []
    seen: set[str] = set()
    for raw in raw_proposals:
        if not isinstance(raw, Mapping):
            continue
        field_key = str(raw.get('field_key') or '')
        value_origin = str(raw.get('value_origin') or '')
        source_id = str(raw.get('source_id') or '')
        source_locator = raw.get('source_locator')
        retrieval_note = str(raw.get('retrieval_note') or '').strip()
        value = raw.get('value')
        if (
            field_key not in allowed
            or value in (None, '')
            or value_origin not in ALLOWED_VALUE_ORIGINS
            or not source_id
            or source_locator in (None, '', {}, [])
            or (
                value_origin in {'calculated', 'analogue'}
                and not retrieval_note
            )
        ):
            continue
        relation_to_object = str(
            raw.get('relation_to_object')
            or (
                'deposit_analogue'
                if value_origin == 'analogue'
                else 'direct'
            )
        )
        proposal = GisFieldProposal(
            field_key=field_key,
            value=value,
            unit=(
                str(raw.get('unit'))
                if raw.get('unit') is not None
                else None
            ),
            value_origin=value_origin,  # type: ignore[arg-type]
            relation_to_object=relation_to_object,
            source_id=source_id,
            source_title=str(raw.get('source_title') or source_id),
            source_locator=source_locator,
            retrieval_note=retrieval_note,
            value_kind=str(raw.get('value_kind') or '').strip(),
            temporal_role=str(raw.get('temporal_role') or '').strip(),
            entity_role=str(raw.get('entity_role') or '').strip(),
        )
        identity = json.dumps(
            proposal.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
        )
        if identity not in seen:
            seen.add(identity)
            proposals.append(proposal)
    return tuple(proposals)


def normalize_gis_object_profile(
    raw_output: str,
    *,
    object_name: str,
    project_id: str,
) -> GisObjectSearchProfile:
    """Decode optional GIS descriptors without reopening project resolution."""
    try:
        payload = extract_json_object(raw_output)
    except GeotizerOrchestrationError as exc:
        return GisObjectSearchProfile(
            object_name=object_name,
            project_id=project_id,
            profile_status='unavailable',
            location_terms=(),
            commodity_terms=(),
            deposit_type_terms=(),
            geology_terms=(),
            evidence=(),
            diagnostics=(str(exc),),
        )

    location_terms = _normalized_terms(payload.get('location_terms'))
    commodity_terms = _normalized_terms(payload.get('commodity_terms'))
    deposit_type_terms = _normalized_terms(payload.get('deposit_type_terms'))
    geology_terms = _normalized_terms(payload.get('geology_terms'))
    raw_evidence = payload.get('evidence')
    if (
        not isinstance(raw_evidence, Sequence)
        or isinstance(raw_evidence, str | bytes)
    ):
        raw_evidence = []
    evidence = tuple(
        dict(item)
        for item in raw_evidence[:20]
        if isinstance(item, Mapping)
    )
    diagnostics: tuple[str, ...] = ()
    if not evidence and any(
        (
            location_terms,
            commodity_terms,
            deposit_type_terms,
            geology_terms,
        )
    ):
        location_terms = ()
        commodity_terms = ()
        deposit_type_terms = ()
        geology_terms = ()
        diagnostics = (
            'GIS descriptors were ignored because no exact GIS evidence '
            'locator was supplied.',
        )
    has_descriptors = any(
        (
            location_terms,
            commodity_terms,
            deposit_type_terms,
            geology_terms,
        )
    )
    return GisObjectSearchProfile(
        object_name=object_name,
        project_id=project_id,
        profile_status='ready' if has_descriptors and evidence else 'partial',
        location_terms=location_terms,
        commodity_terms=commodity_terms,
        deposit_type_terms=deposit_type_terms,
        geology_terms=geology_terms,
        evidence=evidence,
        diagnostics=diagnostics,
    )


def build_knowledge_search_plan(
    profile: GisObjectSearchProfile,
) -> dict[str, Any]:
    """Plan direct, contextual and analogue retrieval in decreasing authority."""
    direct_terms = _normalized_terms(
        [
            *_search_aliases(profile.object_name),
            *_search_aliases(profile.project_id),
        ]
    )
    regional_terms = _normalized_terms(
        [*profile.location_terms, *profile.geology_terms]
    )
    analogue_terms = _normalized_terms(
        [
            *profile.commodity_terms,
            *profile.deposit_type_terms,
            *profile.geology_terms,
        ]
    )
    return {
        'schema_version': 1,
        'object_profile': profile.as_dict(),
        'tiers': [
            {
                'tier_id': 'direct',
                'relation_to_object': 'direct',
                'query_terms': list(direct_terms),
                'enabled': True,
                'allowed_use': (
                    'May support object-specific factual fields when the '
                    'source explicitly identifies this object.'
                ),
            },
            {
                'tier_id': 'regional_context',
                'relation_to_object': 'regional_context',
                'query_terms': list(regional_terms),
                'enabled': bool(regional_terms),
                'allowed_use': (
                    'May support regional setting and a calculated object '
                    'alternative when value_origin=calculated is explicit.'
                ),
            },
            {
                'tier_id': 'deposit_analogue',
                'relation_to_object': 'deposit_analogue',
                'query_terms': list(analogue_terms),
                'enabled': bool(analogue_terms),
                'allowed_use': (
                    'May support analogue fields and an object alternative '
                    'when value_origin=analogue is explicit. The value must '
                    'remain visibly distinguishable from a direct fact.'
                ),
            },
        ],
        'decision_rules': [
            (
                'Absence of a directly named collection is not proof that '
                'the knowledge base has no relevant evidence.'
            ),
            (
                'Search enabled tiers in order: direct, regional_context, '
                'deposit_analogue.'
            ),
            (
                'Search every direct alias, including underscore/space, '
                'hyphen and soft-sign variants, before declaring a direct miss.'
            ),
            (
                'Record relation_to_object and the GIS descriptors used for '
                'every contextual or analogue source in retrieval_note and '
                'source_locator.'
            ),
            (
                'Contextual or analogue evidence may fill an alternative '
                'object value only with value_origin=calculated|analogue, '
                'an exact locator and an explanation of the derivation.'
            ),
        ],
    }


def _search_aliases(value: str) -> tuple[str, ...]:
    """Generate conservative spelling aliases used by legacy collection names."""
    normalized = ' '.join(value.strip().split())
    if not normalized:
        return ()
    spaced = normalized.replace('_', ' ')
    variants = [
        normalized,
        spaced,
        spaced.replace('-', ' '),
        spaced.replace('–', ' '),
        spaced.replace('—', ' '),
        spaced.replace('ь', ''),
        spaced.replace('Ь', ''),
    ]
    suffixes = (' площадь', ' участок', ' лицензионная площадь')
    folded = spaced.casefold()
    for suffix in suffixes:
        if folded.endswith(suffix):
            variants.append(spaced[: -len(suffix)].strip())
    return _normalized_terms(variants)


def _normalized_terms(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Sequence):
        values = [value for value in raw if isinstance(value, str)]
    else:
        values = []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = ' '.join(value.strip().split())
        canonical = term.casefold().replace('ё', 'е')
        if not term or canonical in seen:
            continue
        seen.add(canonical)
        result.append(term)
    return tuple(result)


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
            declared_keys = [
                str(field_key)
                for field_key in route.get('field_keys') or []
            ]
            route_keys = (
                [
                    field_key
                    for field_key in declared_keys
                    if field_key in field_keys
                ]
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
                        row_id
                        for row_id in (
                            declared_rows
                            if declared_rows
                            else sorted(row_ids)
                        )
                        if row_id in row_ids
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
        raise GeotizerOrchestrationError(
            'Owner chunks and envelopes must form one non-empty partition'
        )

    sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    patches: list[dict[str, Any]] = []
    for chunk_index, (chunk, envelope) in enumerate(
        zip(chunks, envelopes),
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
            candidate = (
                f'{batch_namespace}__part_{chunk_index}__{source_id}'
            )
            suffix = 2
            while candidate in source_by_id:
                candidate = (
                    f'{batch_namespace}__part_{chunk_index}__'
                    f'{source_id}__{suffix}'
                )
                suffix += 1
            source['source_id'] = candidate
            source_by_id[candidate] = source
            sources.append(source)
            renamed_refs[source_id] = candidate

        for raw_patch in envelope.get('patches') or []:
            patch = dict(raw_patch)
            patch['source_refs'] = [
                renamed_refs.get(str(source_ref), str(source_ref))
                for source_ref in patch.get('source_refs') or []
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


def repair_negative_provenance(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    run_id: str,
    attempt: int,
) -> dict[str, Any]:
    """Register the actual specialist execution for unreferenced not-found patches."""
    repaired = {
        **dict(envelope),
        'source_inventory': [
            dict(source)
            for source in envelope.get('source_inventory') or []
        ],
        'patches': [
            dict(patch)
            for patch in envelope.get('patches') or []
        ],
    }
    missing = [
        patch
        for patch in repaired['patches']
        if patch.get('status') == 'not_found'
        and patch.get('source_refs') == []
    ]
    if not missing:
        return repaired

    chunk = next_batch.get('owner_chunk') or {}
    chunk_index = int(chunk.get('index') or 1)
    chunk_total = int(chunk.get('total') or 1)
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    source_id = (
        f'derived-negative-{batch_id.lower()}-'
        f'part-{chunk_index}-attempt-{attempt}'
    )
    existing_ids = {
        str(source.get('source_id') or '')
        for source in repaired['source_inventory']
    }
    suffix = 2
    candidate = source_id
    while candidate in existing_ids:
        candidate = f'{source_id}-{suffix}'
        suffix += 1
    source_id = candidate
    repaired['source_inventory'].append(
        {
            'source_id': source_id,
            'source_type': 'derived',
            'title': f'{producer} completed negative search for {batch_id}',
            'locator': (
                f'run_id={run_id}; batch_id={batch_id}; '
                f'owner_chunk={chunk_index}/{chunk_total}; attempt={attempt}'
            ),
            'url': None,
        }
    )
    for patch in missing:
        patch['source_refs'] = [source_id]
    return repaired


def owner_failure_envelope(
    next_batch: Mapping[str, Any],
    *,
    run_id: str,
    attempts: int,
    feedback: Sequence[Any],
    object_name: str = '',
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
    candidate_envelopes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fail closed while preserving individually valid owner decisions."""
    chunk = next_batch.get('owner_chunk') or {}
    chunk_index = int(chunk.get('index') or 1)
    chunk_total = int(chunk.get('total') or 1)
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    source_id = (
        f'orchestration-review-{batch_id.lower()}-part-{chunk_index}'
    )
    locator = (
        f'run_id={run_id}; batch_id={batch_id}; '
        f'owner_chunk={chunk_index}/{chunk_total}; attempts={attempts}'
    )
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
                'title': (
                    f'{producer} owner output failed deterministic validation '
                    f'for {batch_id}'
                ),
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
            fallback['patches'],
        ):
            patch['value'] = _review_hypothesis(
                field,
                object_name=object_name,
                accepted_field_summary=accepted_field_summary,
            )
            patch['retrieval_note'] = (
                f"{patch['retrieval_note']} The displayed hypothesis is a "
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
        'source_inventory': [
            dict(source)
            for source in fallback.get('source_inventory') or []
        ],
        'patches': [
            dict(patch)
            for patch in fallback.get('patches') or []
        ],
    }
    field_by_key = {
        str(field.get('field_key') or ''): dict(field)
        for field in next_batch.get('fields') or []
    }
    patch_by_key = {
        str(patch.get('field_key') or ''): patch
        for patch in result['patches']
    }
    accepted: set[str] = set()

    for attempt, candidate in reversed(tuple(enumerate(candidates, start=1))):
        inventory = {
            str(source.get('source_id') or ''): dict(source)
            for source in candidate.get('source_inventory') or []
            if isinstance(source, Mapping)
            and str(source.get('source_id') or '')
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

            refs = [
                str(source_ref)
                for source_ref in raw_patch.get('source_refs') or []
            ]
            if not refs or any(source_ref not in inventory for source_ref in refs):
                continue
            renamed = {
                source_ref: (
                    f"salvage-{str(next_batch.get('batch_id') or '').lower()}"
                    f'-attempt-{attempt}__{source_ref}'
                )
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


def _review_hypothesis(
    field: Mapping[str, Any],
    *,
    object_name: str,
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
) -> str:
    row_id = int(field.get('row_id') or 0)
    element = str(field.get('element') or 'показатель')
    attribute = str(field.get('attribute_name') or 'значение')
    object_label = object_name or 'исследуемого объекта'
    facts = _accepted_fact_phrases(accepted_field_summary)
    if row_id in {91, 92, 93}:
        direction = {
            91: 'осложняющий фактор',
            92: 'улучшающий фактор',
            93: 'фактор прироста ресурсов',
        }[row_id]
        if facts:
            fact_index = (
                (row_id - 91) * 3
                + _attribute_ordinal(attribute)
            ) % len(facts)
            fact = facts[fact_index]
            validation = {
                91: (
                    'Проверить, создаёт ли это ограничение для ресурсов, '
                    'технологии, сроков или инфраструктуры проекта.'
                ),
                92: (
                    'Проверить, повышает ли это достоверность модели, '
                    'извлечение или доступность объекта.'
                ),
                93: (
                    'Проверить, позволяет ли это расширить минерализованный '
                    'контур или перевести ресурсы в более высокую категорию.'
                ),
            }[row_id]
            return (
                f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: {direction} — {fact}. '
                f'{validation}'
            )
        return (
            f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: для {object_label} возможен '
            f'{direction} ({attribute}). Проверить ранжированием прямых GIS, '
            'KB и DataCube свидетельств; подтвердить или отклонить экспертом.'
        )
    if row_id == 98:
        if facts:
            evidence = '; '.join(facts[:3])
            return (
                f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: для {object_label} приняты следующие '
                f'объектные опорные факты: {evidence}. Перспективность следует '
                'проверить совместной моделью геологии, ресурсов, технологии '
                'и доступности, отдельно подтвердив наиболее чувствительные '
                'допущения.'
            )
        return (
            f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: перспективность {object_label} должна '
            'оцениваться совместно по геологии, изученности, ресурсной модели, '
            'технологии и инфраструктуре. Итог допустим только после проверки '
            'противоречий и ключевых пробелов.'
        )
    if row_id == 99:
        if facts:
            evidence = '; '.join(facts[3:6] or facts[:3])
            return (
                f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: ранняя низкая оценка '
                f'{object_label} могла быть связана с неполнотой или прежней '
                f'интерпретацией данных, тогда как сейчас учтены: {evidence}. '
                'Проверить эту причинную связь переинтерпретацией первичных '
                'материалов и сопоставлением с актуальной ресурсной моделью.'
            )
        return (
            f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: следующий этап для {object_label} — '
            'закрыть ресурсные и технологические неопределённости адресными '
            'исследованиями, после чего актуализировать план ГРР и экономические '
            'допущения.'
        )
    return (
        f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: {element} — {attribute} для {object_label}. '
        'Проверить по первичному документу или прямому объектному источнику.'
    )


def _attribute_ordinal(attribute: str) -> int:
    for token in reversed(attribute.split()):
        if token.isdigit():
            return max(int(token) - 1, 0)
    return 0


def _accepted_fact_phrases(
    summary: Sequence[Mapping[str, Any]],
    *,
    limit: int = 9,
) -> list[str]:
    """Return short, distinct, object-specific facts for review synthesis."""
    facts: list[str] = []
    seen: set[str] = set()
    for item in summary:
        if item.get('status') != 'filled' or item.get('value') in (None, ''):
            continue
        element = bounded_text(str(item.get('element') or ''), max_chars=90)
        attribute = bounded_text(
            str(item.get('attribute_name') or ''),
            max_chars=55,
        )
        value = bounded_text(str(item.get('value') or ''), max_chars=150)
        unit = bounded_text(str(item.get('unit') or ''), max_chars=25)
        if not element or not value:
            continue
        label = element
        if attribute and attribute.lower() not in {'значение', 'название'}:
            label = f'{label}, {attribute}'
        phrase = f'{label}: {value}'
        if unit and unit not in value:
            phrase = f'{phrase} {unit}'
        normalized = phrase.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        facts.append(phrase)
        if len(facts) >= limit:
            break
    return facts


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract exactly one JSON object from a model response."""
    if not isinstance(text, str) or not text.strip():
        raise GeotizerOrchestrationError('Agent returned an empty response')

    stripped = _strip_json_fence(text)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _decode_embedded_object(stripped)
    if not isinstance(parsed, dict):
        raise GeotizerOrchestrationError('Agent response must be a JSON object')
    return parsed


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
        expected_keys = [
            str(field.get('field_key') or '')
            for field in next_batch.get('fields') or []
        ]
        matching = []
        for candidate in candidates:
            violations = _contract_violations(next_batch, candidate)
            patches = candidate.get('patches')
            if not isinstance(patches, list):
                continue
            violations.extend(_partition_violations(expected_keys, patches))
            if not violations:
                matching.append(candidate)
        unique = {
            json.dumps(item, ensure_ascii=False, sort_keys=True): item
            for item in matching
        }
        if len(unique) == 1:
            return next(iter(unique.values()))
        raise GeotizerOrchestrationError(
            'Agent response must contain exactly one structurally exact '
            f'owner JSON object; matching_candidates={len(unique)}'
        ) from original_error


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith('```'):
        first_newline = stripped.find('\n')
        last_fence = stripped.rfind('```')
        if first_newline >= 0 and last_fence > first_newline:
            return stripped[first_newline + 1 : last_fence].strip()
    return stripped


def _decode_embedded_object(text: str) -> dict[str, Any]:
    objects = _decode_embedded_objects(text)
    if len(objects) != 1:
        raise GeotizerOrchestrationError(
            'Agent response must contain exactly one unambiguous JSON object'
        )
    return objects[0]


def _decode_embedded_objects(text: str) -> tuple[dict[str, Any], ...]:
    decoder = json.JSONDecoder()
    objects: list[tuple[int, int, dict[str, Any]]] = []
    for index, char in enumerate(text):
        if char != '{':
            continue
        try:
            value, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append((index, index + consumed, value))
    top_level = [
        candidate
        for candidate in objects
        if not any(other_start < candidate[0] and candidate[1] <= other_end for other_start, other_end, _ in objects)
    ]
    unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for _, _, item in top_level}
    return tuple(unique.values())


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
    return ''


def normalize_delegator_message(message: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Expose persisted output text where older delegators expect content."""
    if not isinstance(message, Mapping):
        return message
    recovered = extract_output_message_text(message)
    if recovered:
        if recovered == message.get('content'):
            return message
    else:
        if message.get('done') is not True:
            return message
        recovered = json.dumps(
            {
                'status': 'completed_without_final_text',
                'note': (
                    'The specialist completed without a final textual message; '
                    'function-call output remains in the persisted output array.'
                ),
            },
            ensure_ascii=False,
        )
    return {**message, 'content': recovered}


def validate_owner_envelope(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return deterministic preflight violations for an owner envelope."""
    violations = _contract_violations(next_batch, envelope)
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return tuple([*violations, 'patches must be an array'])

    expected_keys = [str(field.get('field_key') or '') for field in next_batch.get('fields') or []]
    violations.extend(_partition_violations(expected_keys, patches))
    source_ids, inventory_violations = _source_inventory(envelope.get('source_inventory'))
    violations.extend(inventory_violations)
    field_by_key = {
        str(field.get('field_key') or ''): field
        for field in next_batch.get('fields') or []
    }
    for index, patch in enumerate(patches):
        violations.extend(_patch_violations(index, patch, source_ids))
        if isinstance(patch, Mapping):
            field = field_by_key.get(str(patch.get('field_key') or ''))
            if field is not None:
                violations.extend(
                    _semantic_patch_violations(
                        index,
                        field,
                        patch,
                        batch_id=str(next_batch.get('batch_id') or ''),
                    )
                )
    return tuple(violations)


def _contract_violations(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> list[str]:
    violations: list[str] = []
    expected = {
        'batch_id': str(next_batch.get('batch_id') or ''),
        'producer': str(next_batch.get('producer') or ''),
        'policy_version': str(next_batch.get('policy_version') or ''),
        'template_version': str(next_batch.get('template_version') or ''),
    }
    for key, value in expected.items():
        if envelope.get(key) != value:
            violations.append(f'{key}: expected {value!r}, got {envelope.get(key)!r}')
    return violations


def _partition_violations(
    expected_keys: Sequence[str],
    patches: Sequence[Any],
) -> list[str]:
    violations: list[str] = []
    actual_keys = [str(patch.get('field_key') or '') for patch in patches if isinstance(patch, Mapping)]
    duplicates = sorted(key for key in set(actual_keys) if actual_keys.count(key) > 1)
    if duplicates:
        violations.append(f'duplicate field_key values: {duplicates}')
    missing = sorted(set(expected_keys) - set(actual_keys))
    extra = sorted(set(actual_keys) - set(expected_keys))
    if missing:
        violations.append(f'missing field_key values: {missing}')
    if extra:
        violations.append(f'foreign field_key values: {extra}')
    if len(patches) != len(expected_keys):
        violations.append(f'patch count: expected {len(expected_keys)}, got {len(patches)}')
    return violations


def _source_inventory(inventory: Any) -> tuple[set[str], list[str]]:
    if not isinstance(inventory, list):
        return set(), ['source_inventory must be an array']
    source_ids = {str(source.get('source_id') or '') for source in inventory if isinstance(source, Mapping)}
    source_ids.discard('')
    return source_ids, []


def _patch_violations(
    index: int,
    patch: Any,
    source_ids: set[str],
) -> list[str]:
    if not isinstance(patch, Mapping):
        return [f'patches[{index}] must be an object']
    violations: list[str] = []
    status = str(patch.get('status') or '')
    if status not in ALLOWED_FIELD_STATUSES:
        violations.append(f'patches[{index}].status is unsupported: {status}')
    value = patch.get('value')
    if status == 'filled' and value in (None, ''):
        violations.append(f'patches[{index}] filled without value')
    if (
        status == 'filled'
        and isinstance(value, str)
        and ' '.join(value.casefold().split()).strip(' .;:-')
        in NEGATIVE_VALUE_MARKERS
    ):
        violations.append(
            f'patches[{index}] negative marker cannot use status=filled'
        )
    violations.extend(_value_origin_violations(index, patch, status))
    if status in {'not_found', 'not_applicable', 'conflicted'} and value is not None:
        violations.append(f'patches[{index}] {status} must use value=null')
    refs = patch.get('source_refs')
    if not isinstance(refs, list) or not refs:
        violations.append(f'patches[{index}].source_refs must be non-empty')
        return violations
    unknown_refs = sorted({str(ref) for ref in refs} - source_ids)
    if unknown_refs:
        violations.append(f'patches[{index}] has unregistered source_refs: {unknown_refs}')
    if status == 'filled' and patch.get('source_locator') in (
        None,
        '',
        {},
        [],
    ):
        violations.append(f'patches[{index}] filled without source_locator')
    return violations


def _value_origin_violations(
    index: int,
    patch: Mapping[str, Any],
    status: str,
) -> list[str]:
    raw_value_origin = patch.get('value_origin')
    value_origin = (
        str(raw_value_origin or 'direct')
        if status == 'filled'
        else raw_value_origin
    )
    violations: list[str] = []
    if status == 'filled' and value_origin not in ALLOWED_VALUE_ORIGINS:
        violations.append(
            f'patches[{index}].value_origin is unsupported: {value_origin}'
        )
    if status != 'filled' and raw_value_origin is not None:
        violations.append(
            f'patches[{index}] {status} must use value_origin=null'
        )
    if (
        status == 'filled'
        and value_origin in {'calculated', 'analogue'}
        and not str(patch.get('retrieval_note') or '').strip()
    ):
        violations.append(
            f'patches[{index}] {value_origin} requires retrieval_note'
        )
    return violations


def _semantic_patch_violations(
    index: int,
    field: Mapping[str, Any],
    patch: Mapping[str, Any],
    *,
    batch_id: str,
) -> list[str]:
    row_id = int(field.get('row_id') or 0)
    status = str(patch.get('status') or '')
    note = str(patch.get('retrieval_note') or '').casefold()
    origin = str(patch.get('value_origin') or 'direct')
    locator = patch.get('source_locator')
    semantic = locator if isinstance(locator, Mapping) else {}
    value_kind = str(semantic.get('value_kind') or '').casefold()
    temporal_role = str(semantic.get('temporal_role') or '').casefold()
    return [
        *_resource_patch_violations(
            index,
            row_id=row_id,
            status=status,
            value_kind=value_kind,
            note=note,
        ),
        *_plan_patch_violations(
            index,
            row_id=row_id,
            status=status,
            temporal_role=temporal_role,
            origin=origin,
            note=note,
        ),
        *_assemble_patch_violations(
            index,
            row_id=row_id,
            batch_id=batch_id,
            status=status,
            value=patch.get('value'),
        ),
    ]


def _resource_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    value_kind: str,
    note: str,
) -> list[str]:
    if status != 'filled' or not 44 <= row_id <= 56:
        return []
    if (
        value_kind == 'prospectivity_score'
        or 'prospectivity' in note
        or 'перспективност' in note
    ):
        return [
            f'patches[{index}] prospectivity score cannot fill a resource field'
        ]
    return []


def _plan_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    temporal_role: str,
    origin: str,
    note: str,
) -> list[str]:
    if status != 'filled' or not 68 <= row_id <= 76:
        return []
    violations: list[str] = []
    if temporal_role == 'historical_actual':
        violations.append(
            f'patches[{index}] historical work cannot be a current plan'
        )
    historical_markers = (
        'historical',
        'историческ',
        'выполнен',
        'проведен',
        '197',
        '198',
        '199',
        '200',
        '201',
    )
    if origin == 'direct' and any(
        marker in note
        for marker in historical_markers
    ):
        violations.append(
            f'patches[{index}] historical evidence cannot be a direct current plan'
        )
    return violations


def _assemble_patch_violations(
    index: int,
    *,
    row_id: int,
    batch_id: str,
    status: str,
    value: Any,
) -> list[str]:
    if batch_id != 'ASSEMBLE':
        return []
    violations: list[str] = []
    if status == 'requires_expert_review':
        if not isinstance(value, str) or not value.strip():
            violations.append(
                f'patches[{index}] expert review requires a visible hypothesis'
            )
        elif 'гипотеза для проверки:' not in value.casefold():
            violations.append(
                f'patches[{index}] review value must start with a checkable hypothesis'
            )
    if row_id in {98, 99} and status == 'filled':
        if not isinstance(value, str) or len(value.strip()) < 120:
            violations.append(
                f'patches[{index}] conclusion/comment is not substantive'
            )
    return violations


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
        str(field.get('field_key') or ''): int(field.get('row_id') or 0)
        for field in next_batch.get('fields') or []
    }
    input_keys = [str(item.get('field_key') or '') for item in accepted[:12]]
    input_refs = sorted(
        {
            str(source_ref)
            for item in accepted[:12]
            for source_ref in item.get('source_refs') or []
            if str(source_ref)
        }
    )
    result = {
        **dict(envelope),
        'patches': [
            dict(patch)
            for patch in envelope.get('patches') or []
        ],
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


def correct_explicitly_derived_value_origins(
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Correct direct labels contradicted by an explicit derivation note.

    The owner remains responsible for choosing whether a value is usable.
    This pure boundary correction only prevents an accepted alternative from
    being rendered as a direct object fact when its own retrieval note says
    that it came from an analogue, regional context, or calculation/model.
    """
    result = {
        **dict(envelope),
        'patches': [
            dict(patch)
            for patch in envelope.get('patches') or []
        ],
    }
    for patch in result['patches']:
        if str(patch.get('status') or '') != 'filled':
            continue
        current = str(patch.get('value_origin') or 'direct')
        if current != 'direct':
            continue
        inferred = _origin_from_explicit_basis(
            str(patch.get('retrieval_note') or ''),
        )
        if inferred is not None:
            patch['value_origin'] = inferred
    return result


def _origin_from_explicit_basis(note: str) -> str | None:
    normalized = ' '.join(note.casefold().split())
    if any(marker in normalized for marker in ANALOGUE_BASIS_MARKERS):
        return 'analogue'
    if any(marker in normalized for marker in CALCULATED_BASIS_MARKERS):
        return 'calculated'
    return None


def owner_submission(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    violations = validate_owner_envelope(next_batch, envelope)
    if violations:
        raise GeotizerOrchestrationError('; '.join(violations))
    return {
        'action': 'submit_batch',
        'run_id': envelope['run_id'],
        'batch_id': envelope['batch_id'],
        'producer': envelope['producer'],
        'policy_version': envelope['policy_version'],
        'template_version': envelope['template_version'],
        'patches': envelope['patches'],
        'source_inventory': envelope['source_inventory'],
    }


def xlsx_download_path(state: Mapping[str, Any]) -> str:
    xlsx = state.get('xlsx')
    if not isinstance(xlsx, Mapping):
        raise GeotizerOrchestrationError('Final state has no XLSX artifact')
    path = str(xlsx.get('download_path') or '')
    if not path.startswith('/geotizer/files/') or not path.endswith('/geotizer.xlsx'):
        raise GeotizerOrchestrationError('Final state has an invalid XLSX path')
    return path


def ensure_state_can_continue(state: Mapping[str, Any]) -> None:
    status = state.get('workflow_status')
    if status == 'needs_input':
        raise GeotizerOrchestrationError(json.dumps(state.get('error') or state, ensure_ascii=False))
    if status == 'validation_failed':
        raise GeotizerOrchestrationError(json.dumps(state.get('violations') or state, ensure_ascii=False))
    if status not in {'collecting', 'finalized'}:
        raise GeotizerOrchestrationError(f'Unsupported GeoTeaser workflow_status: {status!r}')


def compact_batch_context(
    next_batch: Mapping[str, Any],
    *,
    object_name: str,
    run_id: str,
    datacube: Mapping[str, Any] | None,
    contributor_evidence: Sequence[Mapping[str, Any]],
    knowledge_search_plan: Mapping[str, Any] | None = None,
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded context an owner needs; omit unrelated run state."""
    return {
        'object_name': object_name,
        'run_id': run_id,
        'batch': dict(next_batch),
        'datacube': dict(datacube or {}),
        'knowledge_search_plan': dict(knowledge_search_plan or {}),
        'accepted_field_summary': [
            dict(item)
            for item in accepted_field_summary
        ],
        'contributor_evidence': [
            normalize_contributor_evidence(item)
            for item in contributor_evidence
        ],
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


def normalize_contributor_evidence(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    """Make evidence authority explicit before an LLM owner sees it."""
    normalized = dict(item)
    source_domain = str(item.get('source_domain') or '').strip().lower()
    normalized['source_domain'] = source_domain or 'unknown'
    if source_domain == 'gis':
        normalized['relation_to_object'] = 'direct'
        normalized['evidence_authority'] = 'linked_gis_project'
        normalized['negative_search_precedence'] = (
            'A knowledge-base or web miss cannot negate a confirmed GIS fact.'
        )
    elif source_domain == 'vision':
        normalized['relation_to_object'] = str(
            item.get('relation_to_object')
            or 'project_specific_source'
        )
        normalized['evidence_authority'] = 'project_visual_evidence'
        normalized['negative_search_precedence'] = (
            'Visual evidence is calculated or analogue evidence and never '
            'overrides a direct object fact.'
        )
    else:
        normalized['relation_to_object'] = str(
            item.get('relation_to_object') or 'source_declared'
        )
        normalized['evidence_authority'] = str(
            item.get('evidence_authority') or 'contributor'
        )
    normalized['output'] = bounded_text(
        str(item.get('output') or ''),
        max_chars=MAX_CONTRIBUTOR_EVIDENCE_CHARS,
    )
    return normalized


def apply_structured_gis_field_proposals(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    contributor_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply unambiguous GIS proposals with explicit origin precedence."""
    return _apply_structured_field_proposals(
        next_batch,
        envelope,
        contributor_evidence,
        source_domains={'gis'},
    )


def apply_structured_external_field_proposals(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    contributor_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply typed KB/WEB proposals after target-semantic validation."""
    return _apply_structured_field_proposals(
        next_batch,
        envelope,
        contributor_evidence,
        source_domains={'kb', 'web'},
    )


def _apply_structured_field_proposals(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    contributor_evidence: Sequence[Mapping[str, Any]],
    *,
    source_domains: set[str],
) -> dict[str, Any]:
    proposals_by_key = _structured_proposals_by_field(
        next_batch,
        contributor_evidence,
        source_domains=source_domains,
    )
    field_by_key = {
        str(field.get('field_key') or ''): field
        for field in next_batch.get('fields') or []
    }
    result = {
        **dict(envelope),
        'source_inventory': [
            dict(source)
            for source in envelope.get('source_inventory') or []
        ],
        'patches': [
            dict(patch)
            for patch in envelope.get('patches') or []
        ],
    }
    sources_by_id = {
        str(source.get('source_id') or ''): source
        for source in result['source_inventory']
    }
    patch_by_key = {
        str(patch.get('field_key') or ''): patch
        for patch in result['patches']
    }
    for field_key, proposals in proposals_by_key.items():
        proposal = _select_unambiguous_gis_proposal(
            [
                item
                for item in proposals
                if _proposal_is_semantically_compatible(
                    field_by_key[field_key],
                    item,
                )
            ]
        )
        patch = patch_by_key.get(field_key)
        if proposal is None or patch is None:
            continue
        value_origin = str(proposal.get('value_origin') or '')
        if not _proposal_may_replace_patch(proposal, patch):
            continue

        raw_source_id = str(proposal['source_id'])
        source_id = f'{raw_source_id}__{field_key}'
        source_locator = proposal['source_locator']
        source_domain = str(proposal.get('__source_domain') or 'derived')
        source = {
            'source_id': source_id,
            'source_type': (
                source_domain
                if source_domain in {'gis', 'web'}
                else 'knowledge_base'
                if source_domain == 'kb'
                else 'derived'
            ),
            'title': str(proposal.get('source_title') or source_id),
            'locator': (
                json.dumps(
                    source_locator,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if isinstance(source_locator, Mapping | list)
                else str(source_locator)
            ),
            'url': None,
        }
        existing = sources_by_id.get(source_id)
        if existing is None:
            result['source_inventory'].append(source)
            sources_by_id[source_id] = source
        elif existing != source:
            continue

        locator = _proposal_locator(
            proposal,
            source_domain=source_domain,
        )
        patch.update(
            {
                'value': proposal['value'],
                'unit': proposal.get('unit'),
                'status': 'filled',
                'value_origin': value_origin,
                'source_refs': [source_id],
                'source_locator': locator,
                'retrieval_note': str(proposal['retrieval_note']),
            }
        )
    return result


def _structured_proposals_by_field(
    next_batch: Mapping[str, Any],
    contributor_evidence: Sequence[Mapping[str, Any]],
    *,
    source_domains: set[str],
) -> dict[str, list[Mapping[str, Any]]]:
    allowed_keys = {
        str(field.get('field_key') or '')
        for field in next_batch.get('fields') or []
    }
    proposals_by_key: dict[str, list[Mapping[str, Any]]] = {}
    for evidence in contributor_evidence:
        source_domain = str(
            evidence.get('source_domain') or ''
        ).lower()
        if source_domain not in source_domains:
            continue
        for proposal in evidence.get('field_proposals') or []:
            if not isinstance(proposal, Mapping):
                continue
            field_key = str(proposal.get('field_key') or '')
            if field_key in allowed_keys:
                proposals_by_key.setdefault(field_key, []).append(
                    {
                        **dict(proposal),
                        '__source_domain': source_domain,
                    }
                )
    return proposals_by_key


def _proposal_is_semantically_compatible(
    field: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> bool:
    """Reject category errors while retaining explicit alternatives."""
    row_id = int(field.get('row_id') or 0)
    attribute_name = str(field.get('attribute_name') or '').casefold()
    value_kind = str(proposal.get('value_kind') or '').strip().lower()
    temporal_role = str(
        proposal.get('temporal_role') or ''
    ).strip().lower()
    entity_role = str(proposal.get('entity_role') or '').strip().lower()
    value_origin = str(proposal.get('value_origin') or '').strip().lower()
    relation = str(
        proposal.get('relation_to_object') or ''
    ).strip().lower()
    note = str(proposal.get('retrieval_note') or '').casefold()
    return all(
        (
            _resource_proposal_compatible(
                row_id=row_id,
                attribute_name=attribute_name,
                value_kind=value_kind,
                value_origin=value_origin,
                note=note,
            ),
            _plan_proposal_compatible(
                row_id=row_id,
                temporal_role=temporal_role,
                value_origin=value_origin,
            ),
            _entity_proposal_compatible(
                row_id=row_id,
                entity_role=entity_role,
                relation=relation,
                value_origin=value_origin,
                note=note,
            ),
            _synthesis_proposal_compatible(
                row_id=row_id,
                value_kind=value_kind,
            ),
        )
    )


def _resource_proposal_compatible(
    *,
    row_id: int,
    attribute_name: str,
    value_kind: str,
    value_origin: str,
    note: str,
) -> bool:
    if not 44 <= row_id <= 56:
        return True
    if (
        value_kind == 'prospectivity_score'
        or 'prospectivity' in note
        or 'перспективност' in note
    ):
        return False
    if (
        44 <= row_id <= 53
        and value_origin in {'calculated', 'analogue'}
        and not value_kind
    ):
        return False
    expected_by_attribute = {
        'значение': {'resource_quantity', 'resource_estimate'},
        'объем руды': {'ore_tonnage'},
        'объём руды': {'ore_tonnage'},
        'средние содержания': {'grade'},
        'глубина прогноза': {'depth'},
        'год оценки': {'assessment_year'},
        'документ': {'document_reference'},
    }
    expected = expected_by_attribute.get(attribute_name)
    return not (
        expected
        and value_kind
        and value_kind not in expected
        and not 54 <= row_id <= 56
    )


def _plan_proposal_compatible(
    *,
    row_id: int,
    temporal_role: str,
    value_origin: str,
) -> bool:
    if not 68 <= row_id <= 76:
        return True
    if temporal_role == 'historical_actual':
        return False
    if value_origin == 'direct':
        return temporal_role in {'current_plan', 'approved_plan'}
    if value_origin in {'calculated', 'analogue'}:
        return temporal_role in {'proposed_plan', 'current_plan'}
    return True


def _entity_proposal_compatible(
    *,
    row_id: int,
    entity_role: str,
    relation: str,
    value_origin: str,
    note: str,
) -> bool:
    if row_id in {54, 55, 56}:
        return True
    if (
        value_origin == 'direct'
        and relation in {'regional_context', 'deposit_analogue'}
        and _origin_from_explicit_basis(note) is None
    ):
        return False
    return not (
        value_origin == 'direct'
        and entity_role in {
            'regional_entity',
            'analogue_deposit',
            'other_object',
        }
    )


def _synthesis_proposal_compatible(
    *,
    row_id: int,
    value_kind: str,
) -> bool:
    if row_id not in {91, 92, 93, 98, 99} or not value_kind:
        return True
    return value_kind in {'hypothesis', 'synthesis', 'recommendation'}


def _proposal_may_replace_patch(
    proposal: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> bool:
    value_origin = str(proposal.get('value_origin') or '')
    return not (
        value_origin in {'calculated', 'analogue'}
        and patch.get('status') == 'filled'
        and str(patch.get('value_origin') or 'direct') == 'direct'
    )


def _select_unambiguous_gis_proposal(
    proposals: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    priority = {'direct': 0, 'calculated': 1, 'analogue': 2}
    ranked = [
        proposal
        for proposal in proposals
        if str(proposal.get('value_origin') or '') in priority
    ]
    if not ranked:
        return None
    best_priority = min(
        priority[str(proposal.get('value_origin'))]
        for proposal in ranked
    )
    best = [
        proposal
        for proposal in ranked
        if priority[str(proposal.get('value_origin'))] == best_priority
    ]
    unique_values = {
        json.dumps(
            {
                'value': proposal.get('value'),
                'unit': proposal.get('unit'),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for proposal in best
    }
    if len(unique_values) != 1:
        return None
    return best[0]


def _proposal_locator(
    proposal: Mapping[str, Any],
    *,
    source_domain: str = 'gis',
) -> Any:
    raw_locator = proposal.get('source_locator')
    metadata = {
        'relation_to_object': str(
            proposal.get('relation_to_object') or 'direct'
        ),
        'value_origin': str(proposal.get('value_origin') or ''),
        'evidence_authority': (
            'linked_gis_project'
            if source_domain == 'gis'
            else 'structured_contributor_proposal'
        ),
        'proposal_source_id': str(proposal.get('source_id') or ''),
        'value_kind': str(proposal.get('value_kind') or ''),
        'temporal_role': str(proposal.get('temporal_role') or ''),
        'entity_role': str(proposal.get('entity_role') or ''),
    }
    if isinstance(raw_locator, Mapping):
        return {**dict(raw_locator), **metadata}
    return {'locator': raw_locator, **metadata}


def bounded_text(value: str, *, max_chars: int) -> str:
    """Keep the beginning and provenance-rich tail of oversized evidence."""
    if len(value) <= max_chars:
        return value
    tail_chars = min(4_000, max_chars // 4)
    head_chars = max_chars - tail_chars
    removed = len(value) - max_chars
    return (
        f'{value[:head_chars]}\n\n'
        f'[... {removed} evidence characters omitted by orchestrator ...]\n\n'
        f'{value[-tail_chars:]}'
    )
