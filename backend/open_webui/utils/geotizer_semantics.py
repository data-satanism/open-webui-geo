"""Versioned runtime semantics for high-risk GeoTeaser fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEMANTIC_POLICY_VERSION = 'geotizer_runtime_semantics.v0.2'

GEOLOGY_ENTITY_SCOPE_BY_ROW = {
    15: 'tectonic_domain',
    16: 'metallogenic_province',
    17: 'ore_district',
    18: 'ore_node',
    19: 'ore_field',
}

RESOURCE_ENTITY_SCOPE_BY_ROW = {
    44: 'ore_node',
    45: 'ore_field',
    46: 'licence_area',
    47: 'licence_area',
    48: 'licence_area',
    49: 'target_deposit',
    50: 'named_subarea',
    51: 'named_subarea',
    52: 'named_subarea',
    53: 'named_subarea',
    54: 'analogue_deposit',
    55: 'analogue_deposit',
    56: 'analogue_deposit',
}

RESOURCE_ESTIMATE_STATES_BY_ROW = {
    44: frozenset({'author_estimate', 'conditional_p1'}),
    45: frozenset({'author_estimate', 'conditional_p1'}),
    46: frozenset({'author_estimate'}),
    47: frozenset({'approved'}),
    48: frozenset({'current'}),
    49: frozenset({'target_plan'}),
    50: frozenset({'author_estimate', 'conditional_p1'}),
    51: frozenset({'author_estimate', 'conditional_p1'}),
    52: frozenset({'author_estimate', 'conditional_p1'}),
    53: frozenset({'author_estimate', 'conditional_p1'}),
    54: frozenset({'analogue'}),
    55: frozenset({'analogue'}),
    56: frozenset({'analogue'}),
}

ANALOGUE_RELATION_BY_ROW = {
    54: 'same_structure',
    55: 'neighbouring_structure',
    56: 'national_or_global_analogue',
}

GRR_WORK_STAGE_BY_ROW = {
    68: 'routes',
    69: 'trenches',
    70: 'drilling',
    71: 'geochemistry',
    72: 'geophysics',
    73: 'prospecting',
    74: 'evaluation',
    75: 'exploration',
    76: 'all_grr',
}

GRR_VALUE_KIND_BY_ATTRIBUTE = {
    'вид': frozenset({'planned_work'}),
    'объемы': frozenset({'planned_volume', 'planned_quantity'}),
    'объёмы': frozenset({'planned_volume', 'planned_quantity'}),
    'масштаб': frozenset({'planned_scale', 'sampling_grid'}),
    'стоимость': frozenset({'planned_cost'}),
    'срок': frozenset({'schedule'}),
    'документ': frozenset({'document_reference'}),
}

GIS_PROXY_VALUE_KINDS = frozenset(
    {
        'feature_elevation',
        'geometry_length',
        'geometry_area',
        'gis_feature_count',
    }
)


def semantic_hint(field: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact prompt-facing semantic contract for one field."""
    row_id = int(field.get('row_id') or 0)
    result: dict[str, Any] = {
        'policy_version': SEMANTIC_POLICY_VERSION,
    }
    if row_id in GEOLOGY_ENTITY_SCOPE_BY_ROW:
        result.update(
            {
                'semantic_family': 'geological_hierarchy',
                'required_entity_scope': GEOLOGY_ENTITY_SCOPE_BY_ROW[row_id],
                'allowed_value_origins': ['direct'],
            }
        )
    if row_id in RESOURCE_ENTITY_SCOPE_BY_ROW:
        result.update(
            {
                'semantic_family': ('resource_analogue' if row_id in ANALOGUE_RELATION_BY_ROW else 'resource_estimate'),
                'required_entity_scope': RESOURCE_ENTITY_SCOPE_BY_ROW[row_id],
                'allowed_estimate_states': sorted(RESOURCE_ESTIMATE_STATES_BY_ROW[row_id]),
                'required_qualifiers': [
                    'entity_id',
                    'entity_scope',
                    'estimate_state',
                    *(['analogue_relation'] if row_id in ANALOGUE_RELATION_BY_ROW else ['resource_estimate_id']),
                    *(['site_name'] if 50 <= row_id <= 53 else []),
                ],
            }
        )
        if row_id in ANALOGUE_RELATION_BY_ROW:
            result['required_analogue_relation'] = ANALOGUE_RELATION_BY_ROW[row_id]
            result['allowed_value_origins'] = ['analogue']
    if row_id in GRR_WORK_STAGE_BY_ROW:
        result.update(
            {
                'semantic_family': 'grr_plan',
                'required_work_stage': GRR_WORK_STAGE_BY_ROW[row_id],
                'allowed_value_kinds': sorted(
                    GRR_VALUE_KIND_BY_ATTRIBUTE.get(
                        str(field.get('attribute_name') or '').casefold(),
                        (),
                    )
                ),
                'source_priority': [
                    'project_document',
                    'technical_assignment',
                    'licence',
                    'presentation',
                ],
                'rules': [
                    'licence_term_is_not_work_calendar',
                    'gis_geometry_is_not_planned_volume',
                ],
            }
        )
    if row_id == 77:
        result.update(
            {
                'semantic_family': 'infrastructure_qualitative',
                'rules': ['gis_feature_count_is_not_direct_economic_development'],
            }
        )
    if row_id == 88:
        result.update(
            {
                'semantic_family': 'infrastructure_composite',
                'rules': ['line_intersection_does_not_prove_good_access'],
            }
        )
    return result
