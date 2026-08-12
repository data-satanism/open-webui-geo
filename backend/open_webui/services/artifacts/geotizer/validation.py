"""Local copies of the GIS submission rules, held to the server by a corpus.

Marked `DELETE` in `GMM/operations/gt-conv-01/semantic-diff.json`, on the
grounds that a hand-written copy of someone else's rules drifts and nothing
notices. That was true: `assets/geotizer-validation-parity.v1.json` -- the
verdicts `gis_service` returns for twenty-two envelopes -- found four
source-inventory shapes this module accepted and the server refused.

They are not deleted, and the reason is worth stating rather than assuming.
These rules run inside the owner retry loop: per candidate during salvage,
again on each merge, and once per one-field probe. Replacing them with
`action=validate_batch` would put a network round trip in each of those places
and make salvage fail whenever GIS is briefly unreachable, which is the outage
salvage exists to survive. `submit_batch` already validates before it persists,
so the round trip buys no safety at the boundary either.

What the copies were missing was not deletion but a way to notice drift.
`test_geotizer_validation_parity.py` runs every corpus case against this module
on every build, in both directions: never stricter than the server, never
weaker. Whether to remove them anyway is a Runtime Owner decision, recorded in
GMM's attention register.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from ...geotizer.errors import GeotizerOrchestrationError
from ...geotizer.semantics import (
    ANALOGUE_RELATION_BY_ROW,
    GRR_WORK_STAGE_BY_ROW,
    RESOURCE_ENTITY_SCOPE_BY_ROW,
    RESOURCE_ESTIMATE_STATES_BY_ROW,
)
from ...core.vocabulary import (
    ALLOWED_FIELD_STATUSES,
    ALLOWED_VALUE_ORIGINS,
    REQUIRED_SOURCE_FIELDS,
    _is_negative_value_marker,
)


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
    field_by_key = {str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []}
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
    violations.extend(
        _resource_row_consistency_violations(
            next_batch,
            patches,
        )
    )
    return tuple(violations)


def _resource_row_consistency_violations(
    next_batch: Mapping[str, Any],
    patches: Sequence[Any],
) -> list[str]:
    field_by_key = {str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []}
    values_by_row: dict[int, dict[str, set[str]]] = {}
    for patch in patches:
        if not isinstance(patch, Mapping) or patch.get('status') != 'filled':
            continue
        field = field_by_key.get(str(patch.get('field_key') or ''))
        row_id = int(field.get('row_id') or 0) if field else 0
        if not 44 <= row_id <= 56:
            continue
        locator = patch.get('source_locator')
        semantic = locator if isinstance(locator, Mapping) else {}
        row_values = values_by_row.setdefault(
            row_id,
            {
                'entity_id': set(),
                'entity_scope': set(),
                'estimate_state': set(),
                'resource_estimate_id': set(),
                'analogue_relation': set(),
            },
        )
        for key in row_values:
            value = str(semantic.get(key) or '').strip()
            if value:
                row_values[key].add(value)

    violations: list[str] = []
    for row_id, qualifiers in values_by_row.items():
        required = (
            ('entity_id', 'entity_scope', 'estimate_state', 'analogue_relation')
            if row_id in ANALOGUE_RELATION_BY_ROW
            else (
                'entity_id',
                'entity_scope',
                'estimate_state',
                'resource_estimate_id',
            )
        )
        for qualifier in required:
            values = qualifiers[qualifier]
            if len(values) > 1:
                violations.append(f'resource row {row_id} mixes {qualifier}: {sorted(values)}')
    return violations


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
    """Collect registered source ids and check each entry against the schema.

    This used to harvest source_id and validate nothing else, so an entry
    missing source_type or title passed every local check -- the per-attempt
    check, salvage, both merge checks and submission -- and was rejected by the
    GIS service with HTTP 422 after the whole batch had been built.

    The parity corpus in `assets/geotizer-validation-parity.v1.json` caught it:
    four of its twenty-two cases were accepted here and refused by the server.
    The implementation below is the production Tool's, which fixed this before
    the repository did; adopting it is the direction GMM's attention register
    records as A-04.
    """
    if not isinstance(inventory, list):
        return set(), ['source_inventory must be an array']

    source_ids: set[str] = set()
    violations: list[str] = []
    for index, source in enumerate(inventory):
        if not isinstance(source, Mapping):
            violations.append(f'source_inventory[{index}] must be an object')
            continue
        source_id = str(source.get('source_id') or '').strip()
        if not source_id:
            violations.append(f'source_inventory[{index}].source_id is required')
            continue
        missing = [field for field in REQUIRED_SOURCE_FIELDS if not str(source.get(field) or '').strip()]
        if missing:
            violations.append(f'source_inventory[{index}] ({source_id}) is missing {", ".join(missing)}')
        source_ids.add(source_id)
    return source_ids, violations


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
    if status == 'filled' and _is_negative_value_marker(value):
        violations.append(f'patches[{index}] negative marker cannot use status=filled')
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
    value_origin = str(raw_value_origin or 'direct') if status == 'filled' else raw_value_origin
    violations: list[str] = []
    if status == 'filled' and value_origin not in ALLOWED_VALUE_ORIGINS:
        violations.append(f'patches[{index}].value_origin is unsupported: {value_origin}')
    if status != 'filled' and raw_value_origin is not None:
        violations.append(f'patches[{index}] {status} must use value_origin=null')
    if (
        status == 'filled'
        and value_origin in {'calculated', 'analogue'}
        and not str(patch.get('retrieval_note') or '').strip()
    ):
        violations.append(f'patches[{index}] {value_origin} requires retrieval_note')
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
    entity_id = str(semantic.get('entity_id') or '').strip()
    entity_scope = str(semantic.get('entity_scope') or '').casefold().strip()
    estimate_state = str(semantic.get('estimate_state') or '').casefold().strip()
    resource_estimate_id = str(semantic.get('resource_estimate_id') or '').strip()
    site_name = str(semantic.get('site_name') or '').strip()
    analogue_relation = str(semantic.get('analogue_relation') or '').casefold().strip()
    work_stage = str(semantic.get('work_stage') or '').casefold().strip()
    source_class = str(semantic.get('source_class') or '').casefold().strip()
    return [
        *_resource_patch_violations(
            index,
            row_id=row_id,
            status=status,
            value_kind=value_kind,
            origin=origin,
            entity_id=entity_id,
            entity_scope=entity_scope,
            estimate_state=estimate_state,
            resource_estimate_id=resource_estimate_id,
            site_name=site_name,
            analogue_relation=analogue_relation,
            note=note,
        ),
        *_plan_patch_violations(
            index,
            row_id=row_id,
            status=status,
            temporal_role=temporal_role,
            origin=origin,
            work_stage=work_stage,
            source_class=source_class,
            semantic=semantic,
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
    origin: str,
    entity_id: str,
    entity_scope: str,
    estimate_state: str,
    resource_estimate_id: str,
    site_name: str,
    analogue_relation: str,
    note: str,
) -> list[str]:
    if status != 'filled' or not 44 <= row_id <= 56:
        return []
    violations: list[str] = []
    if value_kind == 'prospectivity_score' or 'prospectivity' in note or 'перспективност' in note:
        violations.append(f'patches[{index}] prospectivity score cannot fill a resource field')
    expected_scope = RESOURCE_ENTITY_SCOPE_BY_ROW[row_id]
    if not entity_id:
        violations.append(f'patches[{index}] resource field requires entity_id')
    if entity_scope != expected_scope:
        violations.append(f'patches[{index}] resource entity_scope must be {expected_scope}')
    if estimate_state not in RESOURCE_ESTIMATE_STATES_BY_ROW[row_id]:
        violations.append(f'patches[{index}] resource estimate_state is incompatible with row {row_id}')
    if row_id <= 53 and not resource_estimate_id:
        violations.append(f'patches[{index}] resource row requires resource_estimate_id')
    if 50 <= row_id <= 53 and not site_name:
        violations.append(f'patches[{index}] site resource row requires named site_name')
    violations.extend(
        _resource_analogue_patch_violations(
            index,
            row_id=row_id,
            origin=origin,
            analogue_relation=analogue_relation,
        )
    )
    return violations


def _resource_analogue_patch_violations(
    index: int,
    *,
    row_id: int,
    origin: str,
    analogue_relation: str,
) -> list[str]:
    if row_id not in ANALOGUE_RELATION_BY_ROW:
        if origin == 'analogue':
            return [f'patches[{index}] analogue cannot auto-fill a direct resource row']
        return []
    violations: list[str] = []
    if origin != 'analogue':
        violations.append(f'patches[{index}] analogue row requires value_origin=analogue')
    if analogue_relation != ANALOGUE_RELATION_BY_ROW[row_id]:
        violations.append(f'patches[{index}] analogue relation is incompatible with row {row_id}')
    return violations


def _plan_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    temporal_role: str,
    origin: str,
    work_stage: str,
    source_class: str,
    semantic: Mapping[str, Any],
    note: str,
) -> list[str]:
    if status != 'filled' or not 68 <= row_id <= 76:
        return []
    violations: list[str] = []
    if work_stage != GRR_WORK_STAGE_BY_ROW[row_id]:
        violations.append(f'patches[{index}] GRR work_stage is incompatible with row {row_id}')
    locator_text = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    if (source_class == 'licence' or 'licence_term_phase_allocation' in locator_text) and str(
        semantic.get('value_kind') or ''
    ) == 'schedule':
        violations.append(f'patches[{index}] licence term cannot define a GRR work calendar')
    if temporal_role == 'historical_actual':
        violations.append(f'patches[{index}] historical work cannot be a current plan')
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
    if origin == 'direct' and any(marker in note for marker in historical_markers):
        violations.append(f'patches[{index}] historical evidence cannot be a direct current plan')
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
            violations.append(f'patches[{index}] expert review requires a visible hypothesis')
        elif 'гипотеза для проверки:' not in value.casefold():
            violations.append(f'patches[{index}] review value must start with a checkable hypothesis')
    if row_id in {98, 99} and status == 'filled':
        if not isinstance(value, str) or len(value.strip()) < 120:
            violations.append(f'patches[{index}] conclusion/comment is not substantive')
    return violations


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
