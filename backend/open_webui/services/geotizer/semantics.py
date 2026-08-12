"""Versioned runtime semantics for high-risk GeoTeaser fields.

`implementation-steps.md` S1.3: the row tables move to GMM as versioned assets
and load with a hash and version check; `semantic_hint` stays here as the
executor. Before this they were transcribed into Python beside GMM's
`geotizer-runtime-semantics.v0.2.json`, which is exactly the two-copies problem
A-08 records -- with the aggravation that nothing could notice the drift, because
the transcription had no digest to check against.

The asset now travels with the runtime and is verified byte-for-byte on load, so
the only way the two disagree is a copy that refuses to load at all. What the
policy says about a row -- its entity scope, its estimate states, its work stage,
its analogue relation, its source priority and its negative cases -- is read from
the document rather than restated here.

Two tables stay in Python because the policy has no home for them: the mapping
from a Russian attribute name to the value kinds a ГРР plan cell may carry, and
the set of GIS proxy value kinds. Both are attribute-level and the policy is
row-level. Recorded as GMM attention register A-50 rather than bolted onto
someone else's contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import GeotizerOrchestrationError

ASSETS = Path(__file__).resolve().parent / 'assets'
POLICY_FILE = 'geotizer-runtime-semantics.v0.2.json'
PROVENANCE_FILE = 'provenance.json'

SEMANTIC_POLICY_VERSION = 'geotizer_runtime_semantics.v0.2'
POLICY_ID = 'geomas-geotizer-runtime-semantics'
POLICY_SCHEMA_VERSION = '0.2.0'


@lru_cache(maxsize=4)
def _load(assets_key: str) -> dict[str, Any]:
    assets = Path(assets_key)
    recorded = json.loads((assets / PROVENANCE_FILE).read_text(encoding='utf-8'))['files'].get(POLICY_FILE)
    if not recorded:
        raise GeotizerOrchestrationError(f'{POLICY_FILE} has no provenance record')
    raw = (assets / POLICY_FILE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != recorded['sha256']:
        raise GeotizerOrchestrationError(
            f'{POLICY_FILE} does not match its recorded digest; the copy has drifted from '
            f'{recorded["source_repository"]}'
        )
    document = json.loads(raw.decode('utf-8'))
    # The version check S1.3 asks for, separate from the digest: a byte-identical
    # copy of the wrong policy version is still the wrong policy.
    if document['policy_id'] != POLICY_ID or document['schema_version'] != POLICY_SCHEMA_VERSION:
        raise GeotizerOrchestrationError(
            f'{POLICY_FILE} is {document["policy_id"]}@{document["schema_version"]}, '
            f'not {POLICY_ID}@{POLICY_SCHEMA_VERSION}'
        )
    if len(document['row_semantics']) != recorded['row_semantics']:
        raise GeotizerOrchestrationError(f'{POLICY_FILE} row_semantics count does not match its provenance record')
    return document


def load_policy(assets: Path | None = None) -> dict[str, Any]:
    return _load(str(assets or ASSETS))


def _rows(entry: Mapping[str, Any]) -> list[int]:
    if 'rows' in entry:
        return [int(row) for row in entry['rows']]
    first, last = entry['row_range']
    return list(range(int(first), int(last) + 1))


@lru_cache(maxsize=4)
def _by_row(assets_key: str) -> dict[int, dict[str, Any]]:
    """One entry per row, with the row's own work stage resolved.

    `grr_plan` is written as a range plus an ordered `work_stages` list, so the
    stage for row 70 is the third of nine rather than a value on the row. The
    positional read is the only place this module interprets the document, and
    it is checked by `test_geotizer_semantics_asset.py`.
    """
    resolved: dict[int, dict[str, Any]] = {}
    for entry in _load(assets_key)['row_semantics']:
        rows = _rows(entry)
        stages = entry.get('work_stages') or ()
        if stages and len(stages) != len(rows):
            raise GeotizerOrchestrationError(
                f'{entry["semantic_family"]} names {len(stages)} work stages for {len(rows)} rows'
            )
        for index, row in enumerate(rows):
            resolved[row] = {**entry, 'work_stage': stages[index] if stages else None}
    return resolved


def row_semantics(row_id: int, assets: Path | None = None) -> dict[str, Any] | None:
    return _by_row(str(assets or ASSETS)).get(int(row_id))


def _scope_table(family: str) -> dict[int, str]:
    return {
        row: entry['entity_scopes'][0]
        for row, entry in _by_row(str(ASSETS)).items()
        if entry['semantic_family'] == family and entry.get('entity_scopes')
    }


def _families(*names: str) -> dict[int, dict[str, Any]]:
    return {row: entry for row, entry in _by_row(str(ASSETS)).items() if entry['semantic_family'] in names}


# Derived from the policy, not transcribed beside it. The names are unchanged so
# `project_evidence/proposals.py` and `artifacts/geotizer/validation.py` keep
# importing what they always did.
GEOLOGY_ENTITY_SCOPE_BY_ROW = _scope_table('geological_hierarchy')
RESOURCE_ENTITY_SCOPE_BY_ROW = {
    row: entry['entity_scopes'][0] for row, entry in _families('resource_estimate', 'resource_analogue').items()
}
RESOURCE_ESTIMATE_STATES_BY_ROW = {
    row: frozenset(entry['estimate_states'])
    for row, entry in _families('resource_estimate', 'resource_analogue').items()
    if entry.get('estimate_states')
}
ANALOGUE_RELATION_BY_ROW = {row: entry['analogue_relation'] for row, entry in _families('resource_analogue').items()}
GRR_WORK_STAGE_BY_ROW = {row: entry['work_stage'] for row, entry in _families('grr_plan').items()}

# Attribute-level, and the row-level policy has no home for either. GMM
# attention register A-50: proposing a place for them is an Ontology Approver
# decision, not something to add to another repository's contract in passing.
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
    entry = row_semantics(row_id)
    result: dict[str, Any] = {'policy_version': SEMANTIC_POLICY_VERSION}
    if entry is None:
        return result

    family = entry['semantic_family']
    result['semantic_family'] = family
    if entry.get('entity_scopes'):
        result['required_entity_scope'] = entry['entity_scopes'][0]
    result['allowed_value_origins'] = list(entry['allowed_value_origins'])
    result['source_priority'] = list(entry['source_priority'])
    if entry.get('negative_cases'):
        result['rules'] = list(entry['negative_cases'])

    if family in ('resource_estimate', 'resource_analogue'):
        result['allowed_estimate_states'] = sorted(entry['estimate_states'])
        result['required_qualifiers'] = [
            *entry['required_qualifiers'],
            *(['resource_estimate_id'] if family == 'resource_estimate' else []),
            # Rows 50-53 are the teaser's own subdivision into named sites, so
            # the site name is what tells two otherwise identical estimates apart.
            *(['site_name'] if 50 <= row_id <= 53 else []),
        ]
        if family == 'resource_analogue':
            result['required_analogue_relation'] = entry['analogue_relation']
    else:
        result['required_qualifiers'] = list(entry['required_qualifiers'])

    if family == 'grr_plan':
        result['required_work_stage'] = entry['work_stage']
        result['allowed_value_kinds'] = sorted(
            GRR_VALUE_KIND_BY_ATTRIBUTE.get(str(field.get('attribute_name') or '').casefold(), ())
        )

    return result


__all__ = [
    'ANALOGUE_RELATION_BY_ROW',
    'ASSETS',
    'GEOLOGY_ENTITY_SCOPE_BY_ROW',
    'GIS_PROXY_VALUE_KINDS',
    'GRR_VALUE_KIND_BY_ATTRIBUTE',
    'GRR_WORK_STAGE_BY_ROW',
    'POLICY_ID',
    'RESOURCE_ENTITY_SCOPE_BY_ROW',
    'RESOURCE_ESTIMATE_STATES_BY_ROW',
    'SEMANTIC_POLICY_VERSION',
    'load_policy',
    'row_semantics',
    'semantic_hint',
]
