"""Local copies of the GIS submission rules, held to the server by a corpus."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any
from ...geotizer.errors import GeotizerOrchestrationError
from ...geotizer.semantics import (
    ANALOGUE_RELATION_BY_ROW,
    ESTIMATE_ROW_IDENTITY_QUALIFIERS,
    GRR_WORK_STAGE_BY_ROW,
    RESOURCE_ENTITY_SCOPE_BY_ROW,
    RESOURCE_ESTIMATE_STATES_BY_ROW,
    RESOURCE_UNIT_FAMILIES,
    RESOURCE_UNIT_FAMILY_BY_VALUE_KIND,
    RESOURCE_VALUE_KIND_BY_ATTRIBUTE,
)
from ...core.text import locator_map
from ...core.vocabulary import (
    ALLOWED_FIELD_STATUSES,
    ALLOWED_VALUE_ORIGINS,
    REQUIRED_SOURCE_FIELDS,
    _is_negative_value_marker,
)


def validate_owner_envelope(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    object_name: str | Sequence[str] = '',
) -> tuple[str, ...]:
    """Return deterministic preflight violations for an owner envelope.

    `object_name` is the object's name, or several names for it. When it is
    empty, the check that a subarea row (rows 50-53) does not name the whole
    object is skipped.
    """
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
                        object_name=object_name,
                    )
                )
    violations.extend(
        _resource_row_consistency_violations(
            next_batch,
            patches,
        )
    )
    return tuple(violations)


def resource_row_identity_conflicts(
    next_batch: Mapping[str, Any],
    patches: Sequence[Any],
) -> dict[int, dict[str, list[str]]]:
    """Rows whose filled patches disagree about which estimate they report.

    Returns row -> qualifier -> the two or more distinct values, sorted, for the
    rows and qualifier keys listed in `ESTIMATE_ROW_IDENTITY_QUALIFIERS`.
    """
    field_by_key = {str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []}
    values_by_row: dict[int, dict[str, set[str]]] = {}
    for patch in patches:
        if not isinstance(patch, Mapping) or patch.get('status') != 'filled':
            continue
        field = field_by_key.get(str(patch.get('field_key') or ''))
        row_id = int(field.get('row_id') or 0) if field else 0
        qualifiers = ESTIMATE_ROW_IDENTITY_QUALIFIERS.get(row_id)
        if not qualifiers:
            continue
        locator = patch.get('source_locator')
        semantic = locator if isinstance(locator, Mapping) else {}
        row_values = values_by_row.setdefault(row_id, {key: set() for key in qualifiers})
        for key in qualifiers:
            value = str(semantic.get(key) or '').strip()
            if value:
                row_values[key].add(value)

    return {
        row_id: {
            qualifier: sorted(values)
            for qualifier, values in sorted(row_values.items())
            if len(values) > 1
        }
        for row_id, row_values in sorted(values_by_row.items())
        if any(len(values) > 1 for values in row_values.values())
    }


def _resource_row_consistency_violations(
    next_batch: Mapping[str, Any],
    patches: Sequence[Any],
) -> list[str]:
    return [
        f'resource row {row_id} mixes {qualifier}: {values}'
        for row_id, conflicts in resource_row_identity_conflicts(next_batch, patches).items()
        for qualifier, values in conflicts.items()
    ]


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

    Every entry must be an object with a `source_id` and a non-empty value for
    each of `REQUIRED_SOURCE_FIELDS`.
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
    if (
        status in {'not_found', 'not_applicable', 'conflicted', 'agent_contract_failed'}
        and value is not None
    ):
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
    violations.extend(_locator_ref_violations(index, patch, source_ids))
    return violations


def locator_source_refs(locator: Any) -> list[str]:
    """Every `source_ref` a locator records, at any depth.

    Collects every string under a `source_ref` key and every string item of a
    `source_refs` list, walking nested mappings and lists.
    """
    found: list[str] = []
    if isinstance(locator, Mapping):
        for key, value in locator.items():
            if key == 'source_ref' and isinstance(value, str):
                found.append(value)
            elif key == 'source_refs' and isinstance(value, list):
                found.extend(item for item in value if isinstance(item, str))
                found.extend(
                    ref
                    for item in value
                    if not isinstance(item, str)
                    for ref in locator_source_refs(item)
                )
            else:
                found.extend(locator_source_refs(value))
    elif isinstance(locator, list):
        for item in locator:
            found.extend(locator_source_refs(item))
    return found


def _locator_ref_violations(
    index: int,
    patch: Mapping[str, Any],
    source_ids: set[str],
) -> list[str]:
    """A ref recorded inside the locator must name a source the envelope has."""
    unknown = sorted(
        {
            ref
            for ref in locator_source_refs(patch.get('source_locator'))
            if ref not in source_ids
        }
    )
    if not unknown:
        return []
    return [
        f'patches[{index}] source_locator records unregistered source_refs: {unknown}; '
        'add them to source_inventory or remove the reference'
    ]


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
    object_name: str = '',
) -> list[str]:
    row_id = int(field.get('row_id') or 0)
    status = str(patch.get('status') or '')
    note = str(patch.get('retrieval_note') or '').casefold()
    origin = str(patch.get('value_origin') or 'direct')
    semantic = locator_map(patch.get('source_locator'))
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
    violations = [
        *_subarea_patch_violations(
            index,
            row_id=row_id,
            status=status,
            site_name=site_name,
            object_name=object_name,
            value=patch.get('value'),
        ),
        *_resource_patch_violations(
            index,
            row_id=row_id,
            status=status,
            attribute_name=str(field.get('attribute_name') or ''),
            unit=str(patch.get('unit') or ''),
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
    field_key = str(field.get('field_key') or '')
    if not field_key:
        return violations
    return [
        violation.replace(f'patches[{index}]', f'patches[{index}] {field_key}', 1)
        for violation in violations
    ]


NAMED_SUBAREA_ROWS = range(50, 54)


def _normalized_site_name(value: str) -> str:
    """Comparison form: case and separator differences are not distinctions."""
    return ' '.join(str(value or '').replace('_', ' ').replace('-', ' ').casefold().split())


AREA_SCOPE_WORDS = ('площадь', 'месторождение', 'лицензионн', 'участок недр')

_SUBAREA_ORDINAL = re.compile(r'\d')


def _names_the_whole_area(site_name: str, candidates: set[str]) -> bool:
    """True when `site_name` is the object under a different ending.

    All three must hold: the name carries no digit, its first normalised word is
    the first word of one of `candidates`, and it contains one of
    `AREA_SCOPE_WORDS`.
    """
    tokens = _normalized_site_name(site_name).split()
    if not tokens or _SUBAREA_ORDINAL.search(site_name):
        return False
    leading = {name.split()[0] for name in candidates if name.split()}
    if tokens[0] not in leading:
        return False
    return any(word in _normalized_site_name(site_name) for word in AREA_SCOPE_WORDS)


def _subarea_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    site_name: str,
    object_name: str,
    value: Any = None,
) -> list[str]:
    """A subarea row must name a subarea, not the object.

    Applies to filled patches on `NAMED_SUBAREA_ROWS`. A cell value equal to its
    own `site_name` is refused first, with or without an object name. A
    `site_name` that equals one of the object's names, or names the whole area
    (`_names_the_whole_area`), is refused only when `object_name` is supplied.
    Names are compared in `_normalized_site_name` form.
    """
    if status != 'filled' or row_id not in NAMED_SUBAREA_ROWS:
        return []
    if _normalized_site_name(str(value or '')) and _normalized_site_name(
        str(value or '')
    ) == _normalized_site_name(site_name):
        return [
            _with_exit(
                f'patches[{index}] subarea row {row_id} repeats its own site '
                f'name ({site_name!r}) as the cell value; the row already says '
                f'which subarea it is, and the cell is asked for what was '
                f'measured there',
                condition=NO_NAMED_SUBAREAS_RU,
            )
        ]
    names = [object_name] if isinstance(object_name, str) else list(object_name)
    candidates = {_normalized_site_name(name) for name in names if str(name or '').strip()}
    if not candidates:
        return []
    if _normalized_site_name(site_name) not in candidates and not _names_the_whole_area(
        site_name, candidates
    ):
        return []
    return [
        _with_exit(
            f'patches[{index}] subarea row {row_id} names the object itself '
            f'({site_name!r}); rows {NAMED_SUBAREA_ROWS.start}-'
            f'{NAMED_SUBAREA_ROWS.stop - 1} are named subareas of it, so an '
            f'area-level figure belongs on the area row and not here',
            condition=NO_NAMED_SUBAREAS_RU,
        )
    ]


NO_VALUE_SATISFIES_EXIT_RU = (
    'Если {condition}, подходящего значения не существует: верните '
    'status: not_applicable с причиной, а не другое значение.'
)


def _with_exit(violation: str, *, condition: str) -> str:
    """A refusal that can be unsatisfiable, with the status that closes it."""
    return f'{violation}. {NO_VALUE_SATISFIES_EXIT_RU.format(condition=condition)}'


NO_NAMED_SUBAREAS_RU = 'у объекта нет именованных участков'
NO_ESTIMATE_IN_STATE_RU = 'у объекта нет оценки в допустимом для этой строки состоянии'
NO_ANALOGUE_RU = 'для объекта нет объекта-аналога'
NO_WORK_AT_STAGE_RU = 'у объекта нет работ этой стадии'
NO_ENTITY_AT_SCOPE_RU = 'у объекта нет сущности этого уровня с оценкой'
NO_ESTIMATE_TO_IDENTIFY_RU = 'по объекту нет оценки, которую можно было бы идентифицировать'


def _resource_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    attribute_name: str,
    unit: str,
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
    violations.extend(
        _resource_unit_violations(
            index,
            attribute_name=attribute_name,
            value_kind=value_kind,
            unit=unit,
        )
    )
    expected_scope = RESOURCE_ENTITY_SCOPE_BY_ROW[row_id]
    allowed_states = sorted(RESOURCE_ESTIMATE_STATES_BY_ROW[row_id])
    if not entity_id:
        violations.append(
            _with_exit(
                f'patches[{index}] resource field requires entity_id: set '
                f'source_locator.entity_id to the identifier of the '
                f'{expected_scope} this value belongs to',
                condition=NO_ENTITY_AT_SCOPE_RU,
            )
        )
    if entity_scope != expected_scope:
        violations.append(
            _with_exit(
                f'patches[{index}] resource entity_scope must be '
                f'{expected_scope}; got {entity_scope or "(unset)"!r}',
                condition=NO_ENTITY_AT_SCOPE_RU,
            )
        )
    if estimate_state not in RESOURCE_ESTIMATE_STATES_BY_ROW[row_id]:
        violations.append(
            _with_exit(
                f'patches[{index}] resource estimate_state is incompatible '
                f'with row {row_id}; allowed: {allowed_states}, got '
                f'{estimate_state or "(unset)"!r}',
                condition=NO_ESTIMATE_IN_STATE_RU,
            )
        )
    if row_id <= 53 and not resource_estimate_id:
        violations.append(
            _with_exit(
                f'patches[{index}] resource row requires resource_estimate_id: '
                'set source_locator.resource_estimate_id so two estimates of '
                'the same entity stay distinguishable',
                condition=NO_ESTIMATE_TO_IDENTIFY_RU,
            )
        )
    if 50 <= row_id <= 53 and not site_name:
        violations.append(
            _with_exit(
                f'patches[{index}] site resource row requires named '
                f'site_name: set source_locator.site_name to the subarea this '
                f'estimate covers',
                condition=NO_NAMED_SUBAREAS_RU,
            )
        )
    violations.extend(
        _resource_analogue_patch_violations(
            index,
            row_id=row_id,
            origin=origin,
            analogue_relation=analogue_relation,
        )
    )
    return violations


def _resource_unit_violations(
    index: int,
    *,
    attribute_name: str,
    value_kind: str,
    unit: str,
) -> list[str]:
    """The quantity a resource cell asks for, and the dimension it comes in.

    A `value_kind` outside the kinds `RESOURCE_VALUE_KIND_BY_ATTRIBUTE` lists for
    the attribute is refused, and no unit check follows. A unit is refused only
    when `RESOURCE_UNIT_FAMILIES` recognises it and its family is not one the
    value kind, or when it is absent any kind the attribute accepts, is measured
    in. An absent `value_kind` and an unlisted unit are not refused.
    """
    expected_kinds = RESOURCE_VALUE_KIND_BY_ATTRIBUTE.get(
        attribute_name.casefold().strip()
    )
    if not expected_kinds:
        return []
    violations: list[str] = []
    if value_kind and value_kind not in expected_kinds:
        violations.append(
            f'patches[{index}] value_kind {value_kind!r} does not answer '
            f'{attribute_name.strip()!r}; this cell takes '
            f'{sorted(expected_kinds)}'
        )
        return violations
    families = {
        RESOURCE_UNIT_FAMILY_BY_VALUE_KIND[kind]
        for kind in ({value_kind} if value_kind else expected_kinds)
        if kind in RESOURCE_UNIT_FAMILY_BY_VALUE_KIND
    }
    seen = RESOURCE_UNIT_FAMILIES.get(unit.strip().casefold())
    if families and seen is not None and seen not in families:
        violations.append(
            f'patches[{index}] unit {unit.strip()!r} is {seen} and '
            f'{attribute_name.strip()!r} is measured in '
            f'{" or ".join(sorted(families))}'
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
        violations.append(
            _with_exit(
                f'patches[{index}] analogue row requires '
                f'value_origin=analogue; got {origin or "(unset)"!r}',
                condition=NO_ANALOGUE_RU,
            )
        )
    if analogue_relation != ANALOGUE_RELATION_BY_ROW[row_id]:
        violations.append(
            _with_exit(
                f'patches[{index}] analogue relation is incompatible with '
                f'row {row_id}; required: '
                f'{ANALOGUE_RELATION_BY_ROW[row_id]!r}, got '
                f'{analogue_relation or "(unset)"!r}',
                condition=NO_ANALOGUE_RU,
            )
        )
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
        violations.append(
            _with_exit(
                f'patches[{index}] GRR work_stage is incompatible with row '
                f'{row_id}; required: {GRR_WORK_STAGE_BY_ROW[row_id]!r}, got '
                f'{work_stage or "(unset)"!r}',
                condition=NO_WORK_AT_STAGE_RU,
            )
        )
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
    if origin == 'direct' and _note_dates_itself_before_the_plan(note):
        violations.append(f'patches[{index}] historical evidence cannot be a direct current plan')
    return violations


_HISTORICAL_WORDS = ('historical', 'историческ')

_PLAN_NOTE_PAST_YEAR = re.compile(r'\b(19\d{2}|20[01]\d)\b')


def _note_dates_itself_before_the_plan(note: str) -> bool:
    """Whether a retrieval note describes work that is already done.

    True when the note contains one of `_HISTORICAL_WORDS` or a year matched by
    `_PLAN_NOTE_PAST_YEAR`.
    """
    return bool(
        any(word in note for word in _HISTORICAL_WORDS)
        or _PLAN_NOTE_PAST_YEAR.search(note)
    )


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
