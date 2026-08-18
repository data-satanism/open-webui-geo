"""Evidence normalisation, source selection and conflict resolution.

CORE-BOUNDARY-01 action 1. Keys on evidence, not on a GeoTeaser cell: nothing
here may import an artefact module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from ..geotizer.errors import GeotizerOrchestrationError
from ..geotizer.semantics import (
    ANALOGUE_RELATION_BY_ROW,
    GEOLOGY_ENTITY_SCOPE_BY_ROW,
    GIS_PROXY_VALUE_KINDS,
    GRR_VALUE_KIND_BY_ATTRIBUTE,
    GRR_WORK_STAGE_BY_ROW,
    RESOURCE_ENTITY_SCOPE_BY_ROW,
    RESOURCE_ESTIMATE_STATES_BY_ROW,
)
from .retrieval import (
    evidence_chain_violations,
    evidence_locator_identity,
)
from ..core.text import bounded_text, extract_json_object
from ..core.vocabulary import (
    ALLOWED_VALUE_ORIGINS,
    _is_negative_value_marker,
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
    entity_id: str = ''
    entity_scope: str = ''
    estimate_state: str = ''
    resource_estimate_id: str = ''
    site_name: str = ''
    analogue_relation: str = ''
    work_stage: str = ''
    source_class: str = ''
    source_document_id: str = ''
    source_url: str = ''
    query_id: str = ''
    retrieval_plan_id: str = ''

    def as_dict(self) -> dict[str, Any]:
        result = {
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
            'entity_id': self.entity_id,
            'entity_scope': self.entity_scope,
            'estimate_state': self.estimate_state,
            'resource_estimate_id': self.resource_estimate_id,
            'site_name': self.site_name,
            'analogue_relation': self.analogue_relation,
            'work_stage': self.work_stage,
            'source_class': self.source_class,
            'source_document_id': self.source_document_id,
            'source_url': self.source_url,
        }
        if self.query_id:
            result['query_id'] = self.query_id
        if self.retrieval_plan_id:
            result['retrieval_plan_id'] = self.retrieval_plan_id
        return result


def normalize_gis_field_proposals(
    raw_output: str,
    *,
    allowed_field_keys: Sequence[str],
    allowed_query_ids: Sequence[str] | None = None,
) -> tuple[GisFieldProposal, ...]:
    """Decode valid GIS proposals and ignore foreign or untraceable claims."""
    try:
        payload = extract_json_object(raw_output)
    except GeotizerOrchestrationError:
        return ()
    raw_proposals = payload.get('field_proposals')
    if not isinstance(raw_proposals, Sequence) or isinstance(raw_proposals, str | bytes):
        return ()

    allowed = {str(field_key) for field_key in allowed_field_keys}
    allowed_queries = {str(query_id) for query_id in allowed_query_ids} if allowed_query_ids is not None else None
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
        query_id = str(raw.get('query_id') or '')
        retrieval_plan_id = str(raw.get('retrieval_plan_id') or '')
        value = raw.get('value')
        if (
            field_key not in allowed
            or value in (None, '')
            or _is_negative_value_marker(value)
            or value_origin not in ALLOWED_VALUE_ORIGINS
            or not source_id
            or source_locator in (None, '', {}, [])
            or (allowed_queries is not None and query_id not in allowed_queries)
            or (value_origin in {'calculated', 'analogue'} and not retrieval_note)
        ):
            continue
        relation_to_object = str(
            raw.get('relation_to_object') or ('deposit_analogue' if value_origin == 'analogue' else 'direct')
        )
        proposal = GisFieldProposal(
            field_key=field_key,
            value=value,
            unit=(str(raw.get('unit')) if raw.get('unit') is not None else None),
            value_origin=value_origin,  # type: ignore[arg-type]
            relation_to_object=relation_to_object,
            source_id=source_id,
            source_title=str(raw.get('source_title') or source_id),
            source_locator=source_locator,
            retrieval_note=retrieval_note,
            value_kind=str(raw.get('value_kind') or '').strip(),
            temporal_role=str(raw.get('temporal_role') or '').strip(),
            entity_role=str(raw.get('entity_role') or '').strip(),
            entity_id=str(raw.get('entity_id') or '').strip(),
            entity_scope=str(raw.get('entity_scope') or '').strip(),
            estimate_state=str(raw.get('estimate_state') or '').strip(),
            resource_estimate_id=str(raw.get('resource_estimate_id') or '').strip(),
            site_name=str(raw.get('site_name') or '').strip(),
            analogue_relation=str(raw.get('analogue_relation') or '').strip(),
            work_stage=str(raw.get('work_stage') or '').strip(),
            source_class=str(raw.get('source_class') or '').strip(),
            source_document_id=str(raw.get('source_document_id') or '').strip(),
            source_url=str(raw.get('source_url') or '').strip(),
            query_id=query_id,
            retrieval_plan_id=retrieval_plan_id,
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
    if not isinstance(raw_evidence, Sequence) or isinstance(raw_evidence, str | bytes):
        raw_evidence = []
    evidence = tuple(dict(item) for item in raw_evidence[:20] if isinstance(item, Mapping))
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
        diagnostics = ('GIS descriptors were ignored because no exact GIS evidence locator was supplied.',)
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
    regional_terms = _normalized_terms([*profile.location_terms, *profile.geology_terms])
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
                    'May support object-specific factual fields when the source explicitly identifies this object.'
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
            ('Absence of a directly named collection is not proof that the knowledge base has no relevant evidence.'),
            ('Search enabled tiers in order: direct, regional_context, deposit_analogue.'),
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
        'source_inventory': [dict(source) for source in envelope.get('source_inventory') or []],
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    missing = [
        patch for patch in repaired['patches'] if patch.get('status') == 'not_found' and patch.get('source_refs') == []
    ]
    if not missing:
        return repaired

    chunk = next_batch.get('owner_chunk') or {}
    chunk_index = int(chunk.get('index') or 1)
    chunk_total = int(chunk.get('total') or 1)
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    source_id = f'derived-negative-{batch_id.lower()}-part-{chunk_index}-attempt-{attempt}'
    existing_ids = {str(source.get('source_id') or '') for source in repaired['source_inventory']}
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
                f'run_id={run_id}; batch_id={batch_id}; owner_chunk={chunk_index}/{chunk_total}; attempt={attempt}'
            ),
            'url': None,
        }
    )
    for patch in missing:
        patch['source_refs'] = [source_id]
    return repaired


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
            fact_index = ((row_id - 91) * 3 + _attribute_ordinal(attribute)) % len(facts)
            fact = facts[fact_index]
            validation = {
                91: (
                    'Проверить, создаёт ли это ограничение для ресурсов, технологии, сроков или инфраструктуры проекта.'
                ),
                92: ('Проверить, повышает ли это достоверность модели, извлечение или доступность объекта.'),
                93: (
                    'Проверить, позволяет ли это расширить минерализованный '
                    'контур или перевести ресурсы в более высокую категорию.'
                ),
            }[row_id]
            return f'ГИПОТЕЗА ДЛЯ ПРОВЕРКИ: {direction} — {fact}. {validation}'
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
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
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
        normalized['negative_search_precedence'] = 'A knowledge-base or web miss cannot negate a confirmed GIS fact.'
    elif source_domain == 'vision':
        normalized['relation_to_object'] = str(item.get('relation_to_object') or 'project_specific_source')
        normalized['evidence_authority'] = 'project_visual_evidence'
        normalized['negative_search_precedence'] = (
            'Visual evidence is calculated or analogue evidence and never overrides a direct object fact.'
        )
    else:
        normalized['relation_to_object'] = str(item.get('relation_to_object') or 'source_declared')
        normalized['evidence_authority'] = str(item.get('evidence_authority') or 'contributor')
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
    field_by_key = {str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []}
    result = {
        **dict(envelope),
        'source_inventory': [dict(source) for source in envelope.get('source_inventory') or []],
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    sources_by_id = {str(source.get('source_id') or ''): source for source in result['source_inventory']}
    patch_by_key = {str(patch.get('field_key') or ''): patch for patch in result['patches']}
    for field_key, proposals in proposals_by_key.items():
        patch = patch_by_key.get(field_key)
        if patch is None:
            continue
        compatible = [
            item
            for item in proposals
            if _proposal_is_semantically_compatible(
                field_by_key[field_key],
                item,
            )
        ]
        best = _best_origin_proposals(compatible)
        if not best:
            continue
        identities = {_proposal_value_identity(proposal) for proposal in best}
        if len(identities) > 1:
            candidates = []
            for proposal in best:
                ref = _register_structured_source(
                    proposal,
                    field_key=field_key,
                    result=result,
                    sources_by_id=sources_by_id,
                )
                if not ref:
                    continue
                candidates.append(
                    _conflict_candidate(
                        value=proposal.get('value'),
                        unit=proposal.get('unit'),
                        value_origin=proposal.get('value_origin'),
                        source_ref=ref,
                        locator=proposal.get('source_locator'),
                    )
                )
            conflict_refs = [candidate['source_ref'] for candidate in candidates]
            if conflict_refs:
                winner, trace = resolve_by_source_authority(candidates, sources_by_id)
                locator = {
                    'policy': 'direct_disagreement_is_conflicted',
                    'candidate_locators': [proposal.get('source_locator') for proposal in best],
                    'candidates': candidates,
                }
                if trace:
                    locator['selection_trace'] = trace
                if winner is not None:
                    patch.update(
                        {
                            'value': winner['value'],
                            'unit': winner['unit'],
                            'status': 'filled',
                            'value_origin': winner['value_origin'] or 'direct',
                            'source_refs': conflict_refs,
                            'source_locator': {**locator, 'policy': 'resolved_by_source_authority'},
                            'retrieval_note': (
                                'Источники разошлись; значение выбрано по иерархии '
                                'источников. Отклонённые значения сохранены.'
                            ),
                        }
                    )
                    continue
                patch.update(
                    {
                        'value': None,
                        'unit': None,
                        'status': 'conflicted',
                        'value_origin': None,
                        'source_refs': conflict_refs,
                        'source_locator': locator,
                        'retrieval_note': (
                            'Conflicting equal-priority structured claims were '
                            'preserved; no value was selected automatically.'
                        ),
                    }
                )
            continue

        proposal = best[0]
        value_origin = str(proposal.get('value_origin') or '')
        if not _proposal_may_replace_patch(proposal, patch):
            continue

        source_domain = str(proposal.get('__source_domain') or 'derived')
        source_id = _register_structured_source(
            proposal,
            field_key=field_key,
            result=result,
            sources_by_id=sources_by_id,
        )
        if not source_id:
            continue

        if (
            patch.get('status') == 'filled'
            and str(patch.get('value_origin') or 'direct') == 'direct'
            and value_origin == 'direct'
        ):
            owner_identity = json.dumps(
                {
                    'value': patch.get('value'),
                    'unit': patch.get('unit'),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            proposal_identity = _proposal_value_identity(proposal)
            if owner_identity != proposal_identity:
                candidates = [
                    _conflict_candidate(
                        value=patch.get('value'),
                        unit=patch.get('unit'),
                        value_origin=patch.get('value_origin') or 'direct',
                        source_ref=next(iter(patch.get('source_refs') or []), ''),
                        locator=patch.get('source_locator'),
                    ),
                    _conflict_candidate(
                        value=proposal.get('value'),
                        unit=proposal.get('unit'),
                        value_origin=value_origin,
                        source_ref=source_id,
                        locator=proposal.get('source_locator'),
                    ),
                ]
                refs = list(dict.fromkeys([*list(patch.get('source_refs') or []), source_id]))
                winner, trace = resolve_by_source_authority(candidates, sources_by_id)
                locator = {
                    'policy': 'direct_disagreement_is_conflicted',
                    'owner_locator': patch.get('source_locator'),
                    'proposal_locator': proposal.get('source_locator'),
                    'candidates': candidates,
                }
                if trace:
                    locator['selection_trace'] = trace
                if winner is not None:
                    patch.update(
                        {
                            'value': winner['value'],
                            'unit': winner['unit'],
                            'status': 'filled',
                            'value_origin': winner['value_origin'] or 'direct',
                            'source_refs': refs,
                            'source_locator': {**locator, 'policy': 'resolved_by_source_authority'},
                            'retrieval_note': (
                                'Источники разошлись; значение выбрано по иерархии '
                                'источников. Отклонённое значение сохранено.'
                            ),
                        }
                    )
                    continue
                patch.update(
                    {
                        'value': None,
                        'unit': None,
                        'status': 'conflicted',
                        'value_origin': None,
                        'source_refs': refs,
                        'source_locator': locator,
                        'retrieval_note': (
                            'The owner direct value conflicts with a structured '
                            'direct contributor claim; both sources are kept.'
                        ),
                    }
                )
                continue
            patch['source_refs'] = list(dict.fromkeys([*list(patch.get('source_refs') or []), source_id]))
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


def _proposal_source_url(proposal: Mapping[str, Any]) -> str | None:
    candidates = [proposal.get('source_url')]
    locator = proposal.get('source_locator')
    if isinstance(locator, Mapping):
        candidates.extend(
            locator.get(key)
            for key in (
                'retrievable_url',
                'download_url',
                'collection_or_url',
                'url',
            )
        )
    for candidate in candidates:
        value = str(candidate or '').strip()
        if value.startswith(('http://', 'https://', '/api/')):
            return value
    return None


def _register_structured_source(
    proposal: Mapping[str, Any],
    *,
    field_key: str,
    result: dict[str, Any],
    sources_by_id: dict[str, Mapping[str, Any]],
) -> str | None:
    raw_source_id = str(proposal.get('source_id') or '')
    if not raw_source_id:
        return None
    source_id = f'{raw_source_id}__{field_key}'
    source_locator = proposal.get('source_locator')
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
        'url': _proposal_source_url(proposal),
    }
    existing = sources_by_id.get(source_id)
    if existing is None:
        result['source_inventory'].append(source)
        sources_by_id[source_id] = source
    elif dict(existing) != source:
        return None
    return source_id


def _structured_proposals_by_field(
    next_batch: Mapping[str, Any],
    contributor_evidence: Sequence[Mapping[str, Any]],
    *,
    source_domains: set[str],
) -> dict[str, list[Mapping[str, Any]]]:
    allowed_keys = {str(field.get('field_key') or '') for field in next_batch.get('fields') or []}
    proposals_by_key: dict[str, list[Mapping[str, Any]]] = {}
    for evidence in contributor_evidence:
        source_domain = str(evidence.get('source_domain') or '').lower()
        if source_domain not in source_domains:
            continue
        allowed_query_ids = (
            {str(value) for value in evidence.get('allowed_query_ids') or []}
            if 'allowed_query_ids' in evidence
            else None
        )
        plan_by_query = {
            str(plan.get('query_id') or ''): str(plan.get('plan_id') or '')
            for plan in evidence.get('retrieval_plans') or []
            if isinstance(plan, Mapping)
        }
        resolved_hit_locators = {
            (
                str(trace.get('query_id') or ''),
                evidence_locator_identity(hit.get('source_locator') or {}),
            ): {
                'rank': hit.get('rank'),
                'score': hit.get('score'),
                'backend_path': list(trace.get('backend_path') or []),
                'collections': list(trace.get('collections') or []),
                'index_version': trace.get('index_version'),
                'exact_query': str(trace.get('exact_query') or ''),
                'top_k_count': len(trace.get('hits') or []),
                'trace_sha256': hashlib.sha256(
                    json.dumps(
                        {
                            'plan_id': trace.get('plan_id'),
                            'query_id': trace.get('query_id'),
                            'source_locators': [
                                item.get('source_locator')
                                for item in trace.get('hits') or []
                                if isinstance(item, Mapping)
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode('utf-8')
                ).hexdigest(),
            }
            for trace in evidence.get('retrieval_traces') or []
            if isinstance(trace, Mapping)
            for hit in trace.get('hits') or []
            if isinstance(hit, Mapping) and isinstance(hit.get('source_locator'), Mapping)
        }
        for proposal in evidence.get('field_proposals') or []:
            if not isinstance(proposal, Mapping):
                continue
            field_key = str(proposal.get('field_key') or '')
            if allowed_query_ids is not None and str(proposal.get('query_id') or '') not in allowed_query_ids:
                continue
            if plan_by_query and plan_by_query.get(str(proposal.get('query_id') or '')) != str(
                proposal.get('retrieval_plan_id') or ''
            ):
                continue
            if source_domain == 'kb' and plan_by_query and evidence_chain_violations(proposal):
                continue
            if (
                source_domain == 'kb'
                and plan_by_query
                and (
                    str(proposal.get('query_id') or ''),
                    evidence_locator_identity(proposal.get('source_locator') or {}),
                )
                not in resolved_hit_locators
            ):
                continue
            if field_key in allowed_keys:
                resolution_key = (
                    str(proposal.get('query_id') or ''),
                    evidence_locator_identity(proposal.get('source_locator') or {}),
                )
                proposals_by_key.setdefault(field_key, []).append(
                    {
                        **dict(proposal),
                        '__source_domain': source_domain,
                        '__retrieval_attribution': resolved_hit_locators.get(
                            resolution_key,
                            {},
                        ),
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
    temporal_role = str(proposal.get('temporal_role') or '').strip().lower()
    entity_role = str(proposal.get('entity_role') or '').strip().lower()
    value_origin = str(proposal.get('value_origin') or '').strip().lower()
    relation = str(proposal.get('relation_to_object') or '').strip().lower()
    note = str(proposal.get('retrieval_note') or '').casefold()
    source_domain = str(proposal.get('__source_domain') or '').strip().lower()
    entity_id = str(proposal.get('entity_id') or '').strip()
    entity_scope = str(proposal.get('entity_scope') or '').strip().lower()
    estimate_state = str(proposal.get('estimate_state') or '').strip().lower()
    resource_estimate_id = str(proposal.get('resource_estimate_id') or '').strip()
    site_name = str(proposal.get('site_name') or '').strip()
    analogue_relation = str(proposal.get('analogue_relation') or '').strip().lower()
    work_stage = str(proposal.get('work_stage') or '').strip().lower()
    source_class = str(proposal.get('source_class') or '').strip().lower()
    source_document_id = str(proposal.get('source_document_id') or '').strip()
    return all(
        (
            _geology_proposal_compatible(
                row_id=row_id,
                value_origin=value_origin,
                entity_id=entity_id,
                entity_scope=entity_scope,
                source_domain=source_domain,
                source_document_id=source_document_id,
            ),
            _resource_proposal_compatible(
                row_id=row_id,
                attribute_name=attribute_name,
                value_kind=value_kind,
                value_origin=value_origin,
                entity_role=entity_role,
                entity_id=entity_id,
                entity_scope=entity_scope,
                estimate_state=estimate_state,
                resource_estimate_id=resource_estimate_id,
                site_name=site_name,
                analogue_relation=analogue_relation,
                source_document_id=source_document_id,
                note=note,
            ),
            _plan_proposal_compatible(
                row_id=row_id,
                attribute_name=attribute_name,
                value_kind=value_kind,
                temporal_role=temporal_role,
                value_origin=value_origin,
                work_stage=work_stage,
                source_class=source_class,
                proposal=proposal,
            ),
            _entity_proposal_compatible(
                row_id=row_id,
                entity_role=entity_role,
                relation=relation,
                value_origin=value_origin,
                note=note,
            ),
            _infrastructure_proposal_compatible(
                row_id=row_id,
                attribute_name=attribute_name,
                source_domain=source_domain,
                value_kind=value_kind,
            ),
            _synthesis_proposal_compatible(
                row_id=row_id,
                value_kind=value_kind,
            ),
        )
    )


def _geology_proposal_compatible(
    *,
    row_id: int,
    value_origin: str,
    entity_id: str,
    entity_scope: str,
    source_domain: str,
    source_document_id: str,
) -> bool:
    expected_scope = GEOLOGY_ENTITY_SCOPE_BY_ROW.get(row_id)
    if expected_scope is None:
        return True
    if value_origin != 'direct':
        return False
    if not entity_id or entity_scope != expected_scope:
        return False
    return source_domain == 'gis' or bool(source_document_id)


def _resource_proposal_compatible(
    *,
    row_id: int,
    attribute_name: str,
    value_kind: str,
    value_origin: str,
    entity_role: str,
    entity_id: str,
    entity_scope: str,
    estimate_state: str,
    resource_estimate_id: str,
    site_name: str,
    analogue_relation: str,
    source_document_id: str,
    note: str,
) -> bool:
    if not 44 <= row_id <= 56:
        return True
    if value_kind == 'prospectivity_score' or 'prospectivity' in note or 'перспективност' in note:
        return False
    if 44 <= row_id <= 53 and value_origin in {'calculated', 'analogue'} and not value_kind:
        return False
    if not _resource_proposal_identity_compatible(
        row_id=row_id,
        entity_id=entity_id,
        entity_scope=entity_scope,
        estimate_state=estimate_state,
        resource_estimate_id=resource_estimate_id,
        site_name=site_name,
        source_document_id=source_document_id,
    ):
        return False
    if row_id in ANALOGUE_RELATION_BY_ROW:
        return (
            value_origin == 'analogue'
            and entity_role == 'analogue_deposit'
            and analogue_relation == ANALOGUE_RELATION_BY_ROW[row_id]
        )
    if value_origin == 'analogue':
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
    return not (expected and value_kind and value_kind not in expected and not 54 <= row_id <= 56)


def _resource_proposal_identity_compatible(
    *,
    row_id: int,
    entity_id: str,
    entity_scope: str,
    estimate_state: str,
    resource_estimate_id: str,
    site_name: str,
    source_document_id: str,
) -> bool:
    if not entity_id or entity_scope != RESOURCE_ENTITY_SCOPE_BY_ROW[row_id]:
        return False
    if estimate_state not in RESOURCE_ESTIMATE_STATES_BY_ROW[row_id]:
        return False
    if not source_document_id:
        return False
    if row_id <= 53 and not resource_estimate_id:
        return False
    return not (50 <= row_id <= 53 and not site_name)


def _plan_proposal_compatible(
    *,
    row_id: int,
    attribute_name: str,
    value_kind: str,
    temporal_role: str,
    value_origin: str,
    work_stage: str,
    source_class: str,
    proposal: Mapping[str, Any],
) -> bool:
    if not 68 <= row_id <= 76:
        return True
    expected_value_kinds = GRR_VALUE_KIND_BY_ATTRIBUTE.get(attribute_name)
    if expected_value_kinds and value_kind not in expected_value_kinds:
        return False
    if work_stage != GRR_WORK_STAGE_BY_ROW[row_id]:
        return False
    if value_kind in GIS_PROXY_VALUE_KINDS:
        return False
    if temporal_role == 'historical_actual':
        return False
    locator = proposal.get('source_locator')
    locator_text = json.dumps(
        locator,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    if value_kind == 'schedule' and (source_class == 'licence' or 'licence_term_phase_allocation' in locator_text):
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
        return not (entity_role == 'target_object' or relation == 'direct')
    if (
        value_origin == 'direct'
        and relation in {'regional_context', 'deposit_analogue'}
        and _origin_from_explicit_basis(note) is None
    ):
        return False
    return not (
        value_origin == 'direct'
        and entity_role
        in {
            'regional_entity',
            'analogue_deposit',
            'other_object',
        }
    )


def _infrastructure_proposal_compatible(
    *,
    row_id: int,
    attribute_name: str,
    source_domain: str,
    value_kind: str,
) -> bool:
    if row_id == 77 and source_domain == 'gis':
        return False
    if row_id == 88 and source_domain == 'gis':
        if attribute_name in {'характер', 'характеристика'}:
            return False
        if value_kind == 'transport_access_character':
            return False
    return True


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


def _best_origin_proposals(
    proposals: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    priority = {'direct': 0, 'calculated': 1, 'analogue': 2}
    ranked = [proposal for proposal in proposals if str(proposal.get('value_origin') or '') in priority]
    if not ranked:
        return []
    best_priority = min(priority[str(proposal.get('value_origin'))] for proposal in ranked)
    return [proposal for proposal in ranked if priority[str(proposal.get('value_origin'))] == best_priority]


#: Source classes a value may be adjudicated between, weakest first.
#:
#: Only two ranks, and deliberately so. The specialist prompts have said
#: "registries over snippets, WEB last" as prose since the beginning, and prose
#: does not adjudicate a conflict -- run `6056e157` finished with 25 conflicts
#: and every one of them reads "both sources are kept". This encodes the half
#: of that sentence the data can settle and no more.
#:
#: Measured on that run: 24 of the 25 conflicts have two sides of different
#: `source_type` -- 12 gis/web, 7 knowledge_base/web, 5 gis/knowledge_base, and
#: 1 web against web. `WEB last` decides the 19 that pit web against a document
#: or a measurement. The 5 gis-against-document pairs are not decided here,
#: because which wins depends on the field family -- GIS is authoritative for a
#: geometry and a licence document is authoritative for a licence number -- and
#: that is the question standing with the domain reviewer. Guessing it would put
#: a value in the card that nobody chose, which is the failure conflicts exist
#: to prevent.
WEB_SOURCE_TYPES = frozenset({'web'})
PRIMARY_SOURCE_TYPES = frozenset({'gis', 'knowledge_base', 'datacube'})


def _source_type_of(source_ref: str, sources_by_id: Mapping[str, Any]) -> str:
    source = sources_by_id.get(source_ref)
    return str((source or {}).get('source_type') or '')


def resolve_by_source_authority(
    candidates: Sequence[Mapping[str, Any]],
    sources_by_id: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str]:
    """Pick a winner when the hierarchy settles it, and say why either way.

    Returns `(winner, reason)`. `winner` is `None` when the conflict stands,
    and `reason` is recorded on the patch as `selection_trace` in both cases --
    a resolution nobody can audit is worse than a conflict, and a conflict with
    no reason is what this run produced 25 of.

    Settles exactly one shape: a single non-web primary source against one or
    more web sources. Two primaries disagreeing is a real disagreement between
    two things entitled to be believed, and web against web is two snippets.
    """
    if len(candidates) < 2:
        return None, ''
    by_rank: dict[str, list[Mapping[str, Any]]] = {'primary': [], 'web': [], 'other': []}
    for candidate in candidates:
        source_type = _source_type_of(str(candidate.get('source_ref') or ''), sources_by_id)
        if source_type in PRIMARY_SOURCE_TYPES:
            by_rank['primary'].append(candidate)
        elif source_type in WEB_SOURCE_TYPES:
            by_rank['web'].append(candidate)
        else:
            by_rank['other'].append(candidate)

    if by_rank['other'] or not by_rank['web']:
        return None, ''
    if len(by_rank['primary']) != 1:
        if not by_rank['primary']:
            return None, (
                f'Не разрешено правилом: все {len(by_rank["web"])} источника — WEB.'
            )
        return None, (
            f'Не разрешено правилом: {len(by_rank["primary"])} первичных источника '
            f'расходятся между собой; выбор за экспертом.'
        )
    winner = by_rank['primary'][0]
    winning_type = _source_type_of(str(winner.get('source_ref') or ''), sources_by_id)
    return winner, (
        f'Разрешено правилом источников: значение из {winning_type} принято, '
        f'{len(by_rank["web"])} WEB-значение(й) отклонено(ы) и сохранено(ы) '
        f'в source_locator.candidates.'
    )


def _conflict_candidate(
    *,
    value: Any,
    unit: Any,
    value_origin: Any,
    source_ref: str,
    locator: Any,
) -> dict[str, Any]:
    """One side of a conflict: the value, and where it came from.

    A `conflicted` cell must carry `value=null` -- the contract says so and the
    audit depends on it, because a conflict is precisely the state where no
    value has been chosen. Both conflict paths satisfied that by discarding the
    competing values outright, keeping only the sources and their locators.

    On run `6056e157` that emptied all 25 conflicted cells: two sources, two
    locators, and no record anywhere of what the two sources actually said. The
    values existed in scope at the moment the conflict was formed and were
    dropped there.

    Everything downstream assumes otherwise. `geoteaser-fill` tells the model
    that `state.json` holds every conflict "with its competing values"; the
    orchestration prompt's INV-6 and OUT-3 require reporting "value A with
    source, value B with source"; and the four-status guidance says a conflict
    needs a person to choose. None of that is possible from a pair of
    locators, and the only remaining way to see the two values is to open both
    sources by hand.

    So the values are recorded beside the patch rather than in it: the cell
    stays `value=null`, and `source_locator.candidates` carries each side with
    the source_ref and locator that produced it.
    """
    return {
        'value': value,
        'unit': unit,
        'value_origin': str(value_origin) if value_origin else None,
        'source_ref': source_ref,
        'locator': locator,
    }


def _proposal_value_identity(proposal: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            'value': proposal.get('value'),
            'unit': proposal.get('unit'),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _proposal_locator(
    proposal: Mapping[str, Any],
    *,
    source_domain: str = 'gis',
) -> Any:
    raw_locator = proposal.get('source_locator')
    metadata = {
        'relation_to_object': str(proposal.get('relation_to_object') or 'direct'),
        'value_origin': str(proposal.get('value_origin') or ''),
        'evidence_authority': ('linked_gis_project' if source_domain == 'gis' else 'structured_contributor_proposal'),
        'proposal_source_id': str(proposal.get('source_id') or ''),
        'value_kind': str(proposal.get('value_kind') or ''),
        'temporal_role': str(proposal.get('temporal_role') or ''),
        'entity_role': str(proposal.get('entity_role') or ''),
        'entity_id': str(proposal.get('entity_id') or ''),
        'entity_scope': str(proposal.get('entity_scope') or ''),
        'estimate_state': str(proposal.get('estimate_state') or ''),
        'resource_estimate_id': str(proposal.get('resource_estimate_id') or ''),
        'site_name': str(proposal.get('site_name') or ''),
        'analogue_relation': str(proposal.get('analogue_relation') or ''),
        'work_stage': str(proposal.get('work_stage') or ''),
        'source_class': str(proposal.get('source_class') or ''),
        'source_document_id': str(proposal.get('source_document_id') or ''),
    }
    if proposal.get('query_id'):
        metadata['query_id'] = str(proposal['query_id'])
    if proposal.get('retrieval_plan_id'):
        metadata['retrieval_plan_id'] = str(proposal['retrieval_plan_id'])
    attribution = proposal.get('__retrieval_attribution')
    if isinstance(attribution, Mapping) and attribution:
        metadata['retrieval_rank'] = attribution.get('rank')
        metadata['retrieval_score'] = attribution.get('score')
        metadata['retrieval_backend_path'] = list(attribution.get('backend_path') or [])
        metadata['retrieval_collections'] = list(attribution.get('collections') or [])
        metadata['retrieval_index_version'] = attribution.get('index_version')
        metadata['retrieval_exact_query'] = str(attribution.get('exact_query') or '')
        metadata['retrieval_top_k_count'] = attribution.get('top_k_count')
        metadata['retrieval_trace_sha256'] = str(attribution.get('trace_sha256') or '')
    if isinstance(raw_locator, Mapping):
        return {**dict(raw_locator), **metadata}
    return {'locator': raw_locator, **metadata}
