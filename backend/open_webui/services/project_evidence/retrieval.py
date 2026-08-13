"""Pure, deterministic retrieval planning for GeoTeaser evidence queries."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

PLANNER_VERSION = 'geomas.retrieval_planner.v1'
RETRIEVAL_FAILURE_TYPES = frozenset(
    {
        'no_retrieval_hit',
        'insufficient_context',
        'conflicted',
        'unsafe_context',
        'retrieval_failed',
    }
)
_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'disregard\s+(the\s+)?(system|developer)\s+message',
        r'(system|developer)\s+prompt\s*:',
        r'call\s+(this\s+)?tool\b',
        r'игнорируй(те)?\s+(все\s+)?предыдущ',
        r'системн(ый|ое)\s+(промпт|сообщение)',
        r'вызови(те)?\s+инструмент',
    )
)
PLAN_SCHEMA = 'geomas.retrieval_plan.v1'
FIELD_KEY_PATTERN = re.compile(r'^geotizer_object\.v1\.r[0-9]{3}\.a[0-9]{2}$')

Intent = Literal[
    'direct_object',
    'licence_legal',
    'climate',
    'geology',
    'study',
    'resources',
    'technology',
    'grr',
    'infrastructure',
    'regional_context',
    'analogue_cohort',
]

TIER_RELATION = {
    'direct': 'direct',
    'regional_context': 'regional_context',
    'deposit_analogue': 'deposit_analogue',
}
TIER_TOP_K = {'direct': 10, 'regional_context': 7, 'deposit_analogue': 5}

FACETS_BY_INTENT: Mapping[str, tuple[str, ...]] = {
    'direct_object': (
        'Общие сведения (лицензия, положение, инфраструктура, физико-географические условия (рельеф, водн.режим, мерзлота и т.п.))',  # noqa: E501
        'Источники информации',
    ),
    'licence_legal': (
        'Общие сведения (лицензия, положение, инфраструктура, физико-географические условия (рельеф, водн.режим, мерзлота и т.п.))',  # noqa: E501
        'Источники информации',
    ),
    'climate': (
        'Climate',
        'Field season duration',
        'Physical and geographical conditions',
        'Sources of information',
    ),
    'geology': (
        'Геодинамические характеристики',
        'Геофизические характеристики',
        'Геохимические признаки',
        'Металлогенические характеристики',
        'Метаморфизм горных пород',
        'Метасоматические изменения',
        'Минералогические признаки',
        'Рудная формация/ Геолого-промышленный тип оруденения',
        'Рудные зоны / тела (морфология, размеры и условия залегания рудных зон и тел)',
        'Стратиграфия и типы пород',
        'Структурно-тектонические характеристики',
        'Условия формирования',
        'Источники информации',
    ),
    'study': (
        'Изученность – общая информация (объемы и виды работ)',
        'Геофизические характеристики',
        'Геохимические признаки',
        'Источники информации',
    ),
    'resources': (
        'Ресурсный потенциал',
        'Полезный компонент руд',
        'Рудные зоны / тела (морфология, размеры и условия залегания рудных зон и тел)',
        'Состав руд',
        'Минералогические признаки',
        'Источники информации',
    ),
    'technology': (
        'Технологические признаки / обогащение / горное дело',
        'Состав руд',
        'Полезный компонент руд',
        'Минералогические признаки',
        'Источники информации',
    ),
    'grr': (
        'Изученность – общая информация (объемы и виды работ)',
        'Источники информации',
    ),
    'infrastructure': (
        'Общие сведения (лицензия, положение, инфраструктура, физико-географические условия (рельеф, водн.режим, мерзлота и т.п.))',  # noqa: E501
    ),
    'regional_context': (
        'Геодинамические характеристики',
        'Металлогенические характеристики',
        'Стратиграфия и типы пород',
        'Структурно-тектонические характеристики',
    ),
    'analogue_cohort': (
        'Металлогенические характеристики',
        'Рудная формация/ Геолого-промышленный тип оруденения',
        'Условия формирования',
    ),
}

SOURCE_CLASSES_BY_INTENT: Mapping[str, tuple[str, ...]] = {
    'licence_legal': ('official_registry', 'licence_document', 'company_registry'),
    'climate': (
        'reference_book',
        'geological_report',
        'work_program',
        'licence_document',
    ),
    'geology': ('technical_report', 'geological_report', 'map_explanatory_note'),
    'study': ('technical_report', 'work_program', 'study_registry'),
    'resources': ('resource_statement', 'technical_report', 'reserve_protocol'),
    'technology': ('metallurgical_test_report', 'technical_report', 'feasibility_study'),
    'grr': ('work_program', 'technical_report', 'study_registry'),
    'infrastructure': ('technical_report', 'official_map', 'gis_project'),
}

NEGATIVE_CONSTRAINTS_BY_INTENT: Mapping[str, tuple[str, ...]] = {
    'direct_object': ('exclude_regional_or_analogue_fact_as_direct',),
    'licence_legal': (
        'require_exact_legal_entity_resolution',
        'exclude_name_only_company_match',
        'exclude_historical_fact_as_current_without_current_source',
    ),
    'climate': (
        'exclude_legal_registry_as_climate_authority',
        'exclude_analogue_climate_as_direct_object_fact',
        'require_object_or_regional_climate_relation',
    ),
    'geology': (
        'exclude_regional_structure_as_object_structure',
        'exclude_analogue_geology_as_direct',
    ),
    'study': (
        'separate_historical_actual_from_current_or_proposed_plan',
        'exclude_map_scale_as_survey_spacing',
    ),
    'resources': (
        'keep_resource_tuple_atomic',
        'exclude_study_method_as_resource_value',
        'exclude_other_object_or_other_grain_resource',
        'exclude_prospectivity_score_as_resource_quantity',
    ),
    'technology': (
        'exclude_exploration_method_as_processing_method',
        'exclude_mineral_presence_as_processing_result',
        'exclude_other_object_technology',
    ),
    'grr': (
        'keep_grr_row_atomic',
        'separate_completed_work_from_planned_work',
    ),
    'infrastructure': ('exclude_regional_infrastructure_as_object_fact',),
    'regional_context': ('never_promote_regional_context_to_direct_fact',),
    'analogue_cohort': ('never_promote_analogue_to_direct_fact',),
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return f'{prefix}-{_sha256(payload)[:24]}'


def normalize_term(value: str) -> str:
    normalized = unicodedata.normalize('NFKC', value)
    return ' '.join(normalized.strip().split())


def unique_terms(values: Sequence[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        term = normalize_term(raw)
        identity = term.casefold().replace('ё', 'е')
        if not term or identity in seen or len(term) > 160:
            continue
        seen.add(identity)
        result.append(term)
    return tuple(result)


def allowlisted_suggested_terms(suggested: Sequence[Any], allowlist: Sequence[str]) -> tuple[str, ...]:
    allowed = {normalize_term(value).casefold().replace('ё', 'е') for value in allowlist}
    return tuple(term for term in unique_terms(suggested) if term.casefold().replace('ё', 'е') in allowed)


def _field_intent(batch_id: str, field: Mapping[str, Any]) -> Intent:
    row_id = int(field.get('row_id') or 0)
    if batch_id == 'KB-LIC-LEGAL':
        return 'licence_legal'
    if batch_id == 'KB-GEO':
        return 'geology'
    if batch_id == 'KB-STUDY':
        return 'study'
    if batch_id == 'KB-RESOURCE-TECH':
        return 'resources' if row_id <= 57 else 'technology'
    if batch_id == 'KB-GRR-FACTORS':
        return 'grr'
    if batch_id == 'GIS-DC':
        return 'infrastructure'
    if batch_id == 'WEB-VERIFY':
        if row_id in {89, 90}:
            return 'climate'
        if 100 <= row_id <= 108:
            return 'licence_legal'
        return 'direct_object'
    return 'direct_object'


def _temporal_policy(intent: str) -> dict[str, Any]:
    if intent == 'licence_legal':
        return {
            'mode': 'current_authoritative',
            'allowed_roles': ['current_fact', 'historical_actual'],
            'currentness_required': True,
        }
    if intent == 'climate':
        return {
            'mode': 'regional_context_as_reported',
            'allowed_roles': ['current_fact', 'historical_actual', 'not_temporal'],
            'currentness_required': False,
        }
    if intent in {'study', 'grr'}:
        return {
            'mode': 'historical_and_current_separate',
            'allowed_roles': ['historical_actual', 'current_plan', 'approved_plan', 'proposed_plan'],
            'currentness_required': False,
        }
    if intent in {'resources', 'technology'}:
        return {
            'mode': 'as_reported',
            'allowed_roles': ['historical_actual', 'current_fact', 'not_temporal'],
            'currentness_required': False,
        }
    return {'mode': 'not_temporal', 'allowed_roles': ['not_temporal'], 'currentness_required': False}


def _field_terms(fields: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return unique_terms(
        [value for field in fields for value in (field.get('group'), field.get('element'), field.get('attribute_name'))]
    )


def _object_scope(
    knowledge_search_plan: Mapping[str, Any],
    *,
    fallback_object_name: str = '',
    fallback_project_id: str = '',
) -> dict[str, Any]:
    profile = knowledge_search_plan.get('object_profile')
    profile = profile if isinstance(profile, Mapping) else {}
    resolution = profile.get('project_resolution')
    resolution = resolution if isinstance(resolution, Mapping) else {}
    object_name = normalize_term(str(resolution.get('object_name') or fallback_object_name))
    if not object_name:
        raise ValueError('RetrievalPlan requires object_profile.project_resolution.object_name')
    project_id = normalize_term(str(resolution.get('project_id') or fallback_project_id))
    object_ids = unique_terms([object_name, project_id])
    return {'object_name': object_name, 'project_id': project_id, 'object_ids': list(object_ids)}


def _tier_specs(knowledge_search_plan: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_tiers = knowledge_search_plan.get('tiers')
    tiers = raw_tiers if isinstance(raw_tiers, Sequence) and not isinstance(raw_tiers, str | bytes) else []
    by_id = {
        str(tier.get('tier_id') or ''): tier
        for tier in tiers
        if isinstance(tier, Mapping) and str(tier.get('tier_id') or '') in TIER_RELATION
    }
    return tuple(
        {
            'tier_id': tier_id,
            'relation_to_object': TIER_RELATION[tier_id],
            'query_terms': list(unique_terms(list(by_id.get(tier_id, {}).get('query_terms') or []))),
            'enabled': bool(by_id.get(tier_id, {}).get('enabled', tier_id == 'direct')),
        }
        for tier_id in ('direct', 'regional_context', 'deposit_analogue')
    )


@dataclass(frozen=True)
class RetrievalPlan:
    plan_id: str
    query_id: str
    status: Literal['planned', 'disabled_no_terms']
    object_scope: Mapping[str, Any]
    field_keys: tuple[str, ...]
    intent: Intent
    tier_id: Literal['direct', 'regional_context', 'deposit_analogue']
    relation_to_object: Literal['direct', 'regional_context', 'deposit_analogue']
    domain_facets: tuple[str, ...]
    source_classes: tuple[str, ...]
    temporal_policy: Mapping[str, Any]
    must_terms: tuple[str, ...]
    should_terms: tuple[str, ...]
    exact_query: str
    filters: Mapping[str, Any]
    boosts: Mapping[str, float]
    negative_constraints: tuple[str, ...]
    top_k: int
    trace_context: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            'schema': PLAN_SCHEMA,
            'plan_id': self.plan_id,
            'query_id': self.query_id,
            'status': self.status,
            'object_scope': dict(self.object_scope),
            'field_keys': list(self.field_keys),
            'intent': self.intent,
            'tier_id': self.tier_id,
            'relation_to_object': self.relation_to_object,
            'domain_facets': list(self.domain_facets),
            'source_classes': list(self.source_classes),
            'temporal_policy': dict(self.temporal_policy),
            'must_terms': list(self.must_terms),
            'should_terms': list(self.should_terms),
            'exact_query': self.exact_query,
            'filters': dict(self.filters),
            'boosts': dict(self.boosts),
            'negative_constraints': list(self.negative_constraints),
            'top_k': self.top_k,
            'trace_context': dict(self.trace_context),
        }


def build_retrieval_plans(
    next_batch: Mapping[str, Any],
    knowledge_search_plan: Mapping[str, Any],
    *,
    run_id: str,
    object_name: str | None = None,
    project_id: str | None = None,
    index_version: str | None = None,
    collections: Sequence[str] = (),
    suggested_terms: Mapping[str, Sequence[Any]] | None = None,
) -> tuple[RetrievalPlan, ...]:
    batch_id = str(next_batch.get('batch_id') or '')
    if not batch_id:
        raise ValueError('RetrievalPlan requires batch_id')
    raw_fields = next_batch.get('fields')
    fields = [field for field in raw_fields or [] if isinstance(field, Mapping)]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for field in fields:
        field_key = str(field.get('field_key') or '')
        if FIELD_KEY_PATTERN.fullmatch(field_key):
            grouped[_field_intent(batch_id, field)].append(field)
    object_scope = _object_scope(
        knowledge_search_plan,
        fallback_object_name=object_name or '',
        fallback_project_id=project_id or '',
    )
    tier_specs = _tier_specs(knowledge_search_plan)
    plans: list[RetrievalPlan] = []
    for intent, intent_fields in sorted(grouped.items()):
        field_keys = tuple(sorted(str(field['field_key']) for field in intent_fields))
        field_terms = _field_terms(intent_fields)
        facets = tuple(sorted(FACETS_BY_INTENT[intent]))
        source_classes = tuple(SOURCE_CLASSES_BY_INTENT.get(intent, ()))
        optional_terms = allowlisted_suggested_terms(
            list((suggested_terms or {}).get(intent, ())),
            [*field_terms, *facets],
        )
        for tier in tier_specs:
            tier_id = str(tier['tier_id'])
            tier_terms = unique_terms(list(tier['query_terms']))
            enabled = bool(tier['enabled']) and (tier_id == 'direct' or bool(tier_terms))
            must_terms = tier_terms or tuple(object_scope['object_ids'])
            should_terms = unique_terms([*field_terms, *optional_terms])
            exact_query = ' | '.join([*must_terms, *should_terms])[:2000]
            filters: dict[str, Any] = {'access_scope': 'authorized'}
            if tier_id == 'direct':
                filters['object_ids'] = list(object_scope['object_ids'])
            if intent in {'licence_legal', 'climate'}:
                filters['source_class'] = list(source_classes)
            trace_context = {
                'run_id': str(run_id),
                'batch_id': batch_id,
                'index_version': index_version,
                'collections': list(unique_terms(list(collections))),
                'planner_version': PLANNER_VERSION,
            }
            identity = {
                'object_scope': object_scope,
                'field_keys': field_keys,
                'intent': intent,
                'tier_id': tier_id,
                'must_terms': must_terms,
                'should_terms': should_terms,
                'filters': filters,
                'index_version': index_version,
            }
            plan = RetrievalPlan(
                plan_id=_stable_id(
                    'rag-plan', {key: value for key, value in identity.items() if key != 'index_version'}
                ),
                query_id=_stable_id('rag-query', identity),
                status='planned' if enabled else 'disabled_no_terms',
                object_scope=object_scope,
                field_keys=field_keys,
                intent=intent,  # type: ignore[arg-type]
                tier_id=tier_id,  # type: ignore[arg-type]
                relation_to_object=str(  # type: ignore[arg-type]
                    tier['relation_to_object']
                ),
                domain_facets=facets,
                source_classes=source_classes,
                temporal_policy=_temporal_policy(intent),
                must_terms=must_terms,
                should_terms=should_terms,
                exact_query=exact_query,
                filters=filters,
                boosts={'domain_facets': 1.25, 'source_classes': 1.15, 'temporal_roles': 1.1},
                negative_constraints=NEGATIVE_CONSTRAINTS_BY_INTENT.get(intent, ()),
                top_k=TIER_TOP_K[tier_id],
                trace_context=trace_context,
            )
            violations = validate_retrieval_plan(plan.as_dict())
            if violations:
                raise ValueError('; '.join(violations))
            plans.append(plan)
    return tuple(plans)


def validate_retrieval_plan(  # noqa: C901 - explicit contract audit
    plan: Mapping[str, Any],
) -> tuple[str, ...]:
    violations: list[str] = []
    if plan.get('schema') != PLAN_SCHEMA:
        violations.append('schema must be geomas.retrieval_plan.v1')
    if not re.fullmatch(r'rag-plan-[0-9a-f]{24}', str(plan.get('plan_id') or '')):
        violations.append('plan_id is invalid')
    if not re.fullmatch(r'rag-query-[0-9a-f]{24}', str(plan.get('query_id') or '')):
        violations.append('query_id is invalid')
    field_keys = plan.get('field_keys') or []
    if not field_keys or any(not FIELD_KEY_PATTERN.fullmatch(str(value)) for value in field_keys):
        violations.append('field_keys must contain full GeoTeaser keys')
    tier = str(plan.get('tier_id') or '')
    if tier not in TIER_RELATION or plan.get('relation_to_object') != TIER_RELATION.get(tier):
        violations.append('tier and relation_to_object are inconsistent')
    filters = plan.get('filters')
    filters = filters if isinstance(filters, Mapping) else {}
    allowed_filters = {'access_scope', 'object_ids', 'document_id', 'document_version', 'source_class'}
    foreign_filters = set(filters) - allowed_filters
    if foreign_filters:
        violations.append(f'filters contain non-allowlisted keys: {sorted(foreign_filters)}')
    if 'domain_facets' in filters:
        violations.append('domain_facets must be soft boosts, not strict filters')
    if filters.get('access_scope') != 'authorized':
        violations.append('filters.access_scope must be authorized')
    object_scope = plan.get('object_scope')
    object_scope = object_scope if isinstance(object_scope, Mapping) else {}
    if not str(object_scope.get('object_name') or '').strip():
        violations.append('object_scope.object_name is required')
    if tier == 'direct' and not filters.get('object_ids'):
        violations.append('direct tier requires filters.object_ids')
    top_k = plan.get('top_k')
    if not isinstance(top_k, int) or not 1 <= top_k <= 50:
        violations.append('top_k must be within 1..50')
    must_terms = tuple(str(value) for value in plan.get('must_terms') or [])
    should_terms = tuple(str(value) for value in plan.get('should_terms') or [])
    expected_query = ' | '.join([*must_terms, *should_terms])[:2000]
    if not str(plan.get('exact_query') or '').strip():
        violations.append('exact_query is required')
    elif plan.get('exact_query') != expected_query:
        violations.append('exact_query must be derived from must_terms + should_terms')
    trace_context = plan.get('trace_context')
    trace_context = trace_context if isinstance(trace_context, Mapping) else {}
    identity = {
        'object_scope': dict(object_scope),
        'field_keys': tuple(str(value) for value in field_keys),
        'intent': str(plan.get('intent') or ''),
        'tier_id': tier,
        'must_terms': must_terms,
        'should_terms': should_terms,
        'filters': dict(filters),
        'index_version': trace_context.get('index_version'),
    }
    expected_plan_id = _stable_id(
        'rag-plan',
        {key: value for key, value in identity.items() if key != 'index_version'},
    )
    expected_query_id = _stable_id('rag-query', identity)
    if plan.get('plan_id') != expected_plan_id:
        violations.append('plan_id does not match plan content')
    if plan.get('query_id') != expected_query_id:
        violations.append('query_id does not match executable query content')
    return tuple(violations)


def unsafe_retrieval_context_reasons(text: str) -> tuple[str, ...]:
    """Detect explicit instruction-like payloads in retrieved source text."""

    return tuple(
        f'prompt_injection_pattern_{index}'
        for index, pattern in enumerate(_INJECTION_PATTERNS, start=1)
        if pattern.search(str(text))
    )


def evidence_chain_violations(proposal: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the stable evidence chain required for a KB factual fill."""

    locator = proposal.get('source_locator')
    if not isinstance(locator, Mapping):
        return ('source_locator must be an object for KB evidence',)
    violations: list[str] = []
    for key in ('document_id', 'document_version'):
        if not str(locator.get(key) or '').strip():
            violations.append(f'source_locator.{key} is required')
    if locator.get('page') in (None, '', -1, '-1', 'unknown'):
        violations.append('source_locator.page must resolve to a page')
    if not str(locator.get('section_path') or locator.get('section') or '').strip():
        violations.append('source_locator.section_path is required')
    if not str(locator.get('child_chunk_id') or locator.get('chunk_id') or '').strip():
        violations.append('source_locator.child_chunk_id is required')
    if not str(proposal.get('query_id') or '').strip():
        violations.append('query_id is required')
    if not str(proposal.get('retrieval_plan_id') or '').strip():
        violations.append('retrieval_plan_id is required')
    excerpt = locator.get('retrieved_excerpt')
    if excerpt not in (None, ''):
        violations.extend(unsafe_retrieval_context_reasons(str(excerpt)))
    return tuple(violations)


def normalize_negative_search_notes(
    raw_notes: Any,
    plans: Sequence[RetrievalPlan],
    *,
    allowed_field_keys: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Accept only negative decisions that reproduce an executable plan."""

    if not isinstance(raw_notes, Sequence) or isinstance(raw_notes, str | bytes):
        return ()
    plan_by_query = {plan.query_id: plan for plan in plans if plan.status == 'planned'}
    allowed_fields = set(map(str, allowed_field_keys))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_notes:
        if not isinstance(raw, Mapping):
            continue
        query_id = str(raw.get('query_id') or '')
        plan = plan_by_query.get(query_id)
        exhausted_tiers = [str(value) for value in raw.get('exhausted_tiers') or []]
        collections = [str(value) for value in raw.get('collections') or [] if str(value)]
        result = str(raw.get('result') or '')
        field_key = str(raw.get('field_key') or '')
        if (
            plan is None
            or field_key not in allowed_fields
            or field_key not in plan.field_keys
            or str(raw.get('retrieval_plan_id') or '') != plan.plan_id
            or str(raw.get('exact_query') or '') != plan.exact_query
            or raw.get('filters') != dict(plan.filters)
            or raw.get('index_version') != plan.trace_context.get('index_version')
            or plan.tier_id not in exhausted_tiers
            or not collections
            or result not in RETRIEVAL_FAILURE_TYPES
        ):
            continue
        note = {
            'field_key': field_key,
            'query_id': query_id,
            'retrieval_plan_id': plan.plan_id,
            'exact_query': plan.exact_query,
            'filters': dict(plan.filters),
            'collections': list(unique_terms(collections)),
            'index_version': plan.trace_context.get('index_version'),
            'exhausted_tiers': list(unique_terms(exhausted_tiers)),
            'result': result,
        }
        identity = json.dumps(note, ensure_ascii=False, sort_keys=True)
        if identity not in seen:
            seen.add(identity)
            normalized.append(note)
    return tuple(normalized)


def _metadata_values(value: Any) -> set[str]:
    if value in (None, ''):
        return set()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in value.split(',')]
        value = parsed
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return {str(item).strip() for item in value if str(item).strip()}
    return {str(value).strip()}


def _metadata_matches_plan(metadata: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    filters = plan.get('filters')
    filters = filters if isinstance(filters, Mapping) else {}
    object_filter = {normalize_term(str(value)) for value in filters.get('object_ids') or []}
    metadata_object_ids = {normalize_term(value) for value in _metadata_values(metadata.get('object_ids'))}
    if object_filter and not object_filter.intersection(metadata_object_ids):
        return False
    for filter_key, metadata_key in (
        ('document_id', 'document_id'),
        ('document_version', 'document_version'),
    ):
        expected = str(filters.get(filter_key) or '')
        if expected and str(metadata.get(metadata_key) or '') != expected:
            return False
    source_classes = {str(value) for value in filters.get('source_class') or []}
    if source_classes and str(metadata.get('source_class') or '') not in source_classes:
        return False
    temporal = plan.get('temporal_policy')
    temporal = temporal if isinstance(temporal, Mapping) else {}
    if temporal.get('currentness_required'):
        allowed_roles = {str(value) for value in temporal.get('allowed_roles') or []}
        if str(metadata.get('temporal_role') or '') not in allowed_roles:
            return False
    return True


def build_grounded_retrieval_trace(  # noqa: C901 - explicit trace policy
    plan: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    *,
    collections: Sequence[str],
    backend_path: Sequence[str],
    backend_failures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Filter retrieval output and expose only safe, lineage-complete hits."""

    plan_violations = validate_retrieval_plan(plan)
    if plan_violations:
        raise ValueError('; '.join(plan_violations))
    result = result or {}
    raw_documents = result.get('documents') or []
    raw_metadatas = result.get('metadatas') or []
    raw_scores = result.get('distances') or []
    documents = raw_documents[0] if raw_documents and isinstance(raw_documents[0], list) else raw_documents
    metadatas = raw_metadatas[0] if raw_metadatas and isinstance(raw_metadatas[0], list) else raw_metadatas
    scores = raw_scores[0] if raw_scores and isinstance(raw_scores[0], list) else raw_scores
    hits: list[dict[str, Any]] = []
    rejected = {
        'strict_filter': 0,
        'unresolved_lineage': 0,
        'unsafe_context': 0,
        'malformed_backend_result': 0,
    }
    # Every document this loop drops is counted, and `failure_type` is derived
    # from those counts. A backend that returns fewer metadata rows than
    # documents would otherwise have its extra documents dropped by `zip`
    # without appearing in any count -- the trace would read `no_retrieval_hit`
    # while evidence was discarded. Counted, not raised: a short result is a
    # backend hiccup, and failing the run would trade lost evidence for an
    # outage.
    rejected['malformed_backend_result'] = abs(len(documents) - len(metadatas))
    for index, (document, raw_metadata) in enumerate(zip(documents, metadatas)):
        metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        if not _metadata_matches_plan(metadata, plan):
            rejected['strict_filter'] += 1
            continue
        locator = {
            'document_id': metadata.get('document_id'),
            'document_version': metadata.get('document_version'),
            'page': metadata.get('page'),
            'section_path': metadata.get('section_path'),
            'child_chunk_id': metadata.get('child_chunk_id'),
            'query_id': plan['query_id'],
            'retrieval_plan_id': plan['plan_id'],
        }
        probe = {
            'query_id': plan['query_id'],
            'retrieval_plan_id': plan['plan_id'],
            'source_locator': locator,
        }
        lineage_violations = evidence_chain_violations(probe)
        if lineage_violations:
            rejected['unresolved_lineage'] += 1
            continue
        unsafe_reasons = unsafe_retrieval_context_reasons(str(document))
        if unsafe_reasons:
            rejected['unsafe_context'] += 1
            continue
        hits.append(
            {
                'rank': len(hits) + 1,
                'score': scores[index] if index < len(scores) else None,
                'content': str(document),
                'source_locator': locator,
                'domain_facets': sorted(_metadata_values(metadata.get('domain_facets'))),
                'source_class': str(metadata.get('source_class') or ''),
                'temporal_role': str(metadata.get('temporal_role') or ''),
            }
        )
        if len(hits) >= int(plan['top_k']):
            break
    if hits:
        failure_type = None
    elif any(bool(value.get('terminal')) for value in backend_failures):
        failure_type = 'retrieval_failed'
    elif rejected['unsafe_context']:
        failure_type = 'unsafe_context'
    elif rejected['unresolved_lineage'] or rejected['strict_filter']:
        failure_type = 'insufficient_context'
    elif rejected['malformed_backend_result']:
        # Nothing was retrievable and the backend's own result did not line up.
        # That is not "no hit"; it is a result nobody can read.
        failure_type = 'retrieval_failed'
    else:
        failure_type = 'no_retrieval_hit'
    return {
        'schema': 'geomas.retrieval_trace.v1',
        'plan_id': plan['plan_id'],
        'query_id': plan['query_id'],
        'exact_query': plan['exact_query'],
        'filters': dict(plan.get('filters') or {}),
        'collections': list(unique_terms(list(collections))),
        'index_version': (plan.get('trace_context') or {}).get('index_version'),
        'backend_path': list(backend_path),
        'backend_failures': [dict(value) for value in backend_failures],
        'failure_type': failure_type,
        'rejected': rejected,
        'hits': hits,
    }


def normalize_retrieval_traces(
    raw_traces: Any,
    plans: Sequence[RetrievalPlan],
) -> tuple[dict[str, Any], ...]:
    """Validate traces copied verbatim from the typed retrieval gateway."""

    if not isinstance(raw_traces, Sequence) or isinstance(raw_traces, str | bytes):
        return ()
    plan_by_query = {plan.query_id: plan for plan in plans if plan.status == 'planned'}
    normalized: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    for raw in raw_traces:
        if not isinstance(raw, Mapping):
            continue
        query_id = str(raw.get('query_id') or '')
        plan = plan_by_query.get(query_id)
        failure_type = raw.get('failure_type')
        collections = [str(value) for value in raw.get('collections') or [] if str(value)]
        if (
            plan is None
            or query_id in seen_queries
            or raw.get('schema') != 'geomas.retrieval_trace.v1'
            or str(raw.get('plan_id') or '') != plan.plan_id
            or str(raw.get('exact_query') or '') != plan.exact_query
            or raw.get('filters') != dict(plan.filters)
            or raw.get('index_version') != plan.trace_context.get('index_version')
            or not collections
            or failure_type not in {None, *RETRIEVAL_FAILURE_TYPES}
        ):
            continue
        hits: list[dict[str, Any]] = []
        raw_hits = raw.get('hits')
        if not isinstance(raw_hits, Sequence) or isinstance(raw_hits, str | bytes):
            continue
        valid = True
        for rank, raw_hit in enumerate(raw_hits, start=1):
            if not isinstance(raw_hit, Mapping):
                valid = False
                break
            locator = raw_hit.get('source_locator')
            probe = {
                'query_id': query_id,
                'retrieval_plan_id': plan.plan_id,
                'source_locator': locator,
            }
            if (
                evidence_chain_violations(probe)
                or not isinstance(locator, Mapping)
                or str(locator.get('query_id') or '') != query_id
                or str(locator.get('retrieval_plan_id') or '') != plan.plan_id
                or unsafe_retrieval_context_reasons(str(raw_hit.get('content') or ''))
            ):
                valid = False
                break
            hits.append(
                {
                    'rank': rank,
                    'score': raw_hit.get('score'),
                    'content': str(raw_hit.get('content') or ''),
                    'source_locator': dict(locator),
                    'domain_facets': list(raw_hit.get('domain_facets') or []),
                    'source_class': str(raw_hit.get('source_class') or ''),
                    'temporal_role': str(raw_hit.get('temporal_role') or ''),
                }
            )
        if not valid or (failure_type is None) != bool(hits):
            continue
        trace = {
            'schema': 'geomas.retrieval_trace.v1',
            'plan_id': plan.plan_id,
            'query_id': query_id,
            'exact_query': plan.exact_query,
            'filters': dict(plan.filters),
            'collections': list(unique_terms(collections)),
            'index_version': plan.trace_context.get('index_version'),
            'backend_path': [str(value) for value in raw.get('backend_path') or []],
            'backend_failures': [
                dict(value) for value in raw.get('backend_failures') or [] if isinstance(value, Mapping)
            ],
            'failure_type': failure_type,
            'rejected': dict(raw.get('rejected') or {}),
            'hits': hits,
        }
        seen_queries.add(query_id)
        normalized.append(trace)
    return tuple(normalized)


def evidence_locator_identity(locator: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """Return the stable locator key used for source resolution."""

    page = locator.get('page')
    return (
        str(locator.get('document_id') or ''),
        str(locator.get('document_version') or ''),
        str(page if page is not None else ''),
        str(locator.get('section_path') or locator.get('section') or ''),
        str(locator.get('child_chunk_id') or locator.get('chunk_id') or ''),
    )
