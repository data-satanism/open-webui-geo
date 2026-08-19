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
weaker.

That argument was put to review and accepted: parity testing is the resolution,
and the copies stay. So the open question is no longer whether to delete them.
It is that the corpus reaches five of the eleven rules here -- every case runs
against `KB-LIC-LEGAL`, the one batch whose accepted envelope carries `filled`
patches, so the six that only bite on a resource, plan or assemble batch are
never exercised. Those six can drift from the server and nothing will say so.
Both repositories name them rather than counting them, and closing the gap means
walking the generator through four more batches in `gis_service`. GMM's
attention register carries it as A-57.
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

    `object_name` is optional because the GIS batch does not carry it and most
    callers have no reason to. Supplying it turns on the subarea check: rows
    50-53 are the teaser's own subdivision into named участки, and a
    `site_name` equal to the object is the licence area wearing a subarea's
    label. Absent, that one rule is skipped rather than guessed at.
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
    # `agent_contract_failed` joins them: the status means the run never got an
    # answer, so a value under it is a value from nowhere.
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
    object_name: str = '',
) -> list[str]:
    row_id = int(field.get('row_id') or 0)
    status = str(patch.get('status') or '')
    note = str(patch.get('retrieval_note') or '').casefold()
    origin = str(patch.get('value_origin') or 'direct')
    # Parsed, not guarded. `semantic = {}` for a string meant every semantic
    # rule silently skipped the four GIS layer reads -- the subarea rule, the
    # resource rules and the GRR stage rule all saw a field with no qualifiers
    # and passed it, which is a rule that stops running rather than a rule that
    # allows something.
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
        ),
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
    # Name the field, not only its position. The row contract these rules
    # enforce is already in the owner's prompt -- `semantic_hint` puts
    # `required_entity_scope`, `allowed_estimate_states`,
    # `required_qualifiers` and `required_analogue_relation` under
    # `field_semantics` from attempt 1 -- but `field_semantics` is keyed by
    # `field_key` and the violation is keyed by `patches[6]`. Acting on it
    # meant mapping an index back to a key and then looking the key up. On run
    # `6056e157` chunk 4/6 of `KB-RESOURCE-TECH` returned 48 of these and
    # repaired none of them.
    field_key = str(field.get('field_key') or '')
    if not field_key:
        return violations
    return [
        violation.replace(f'patches[{index}]', f'patches[{index}] {field_key}', 1)
        for violation in violations
    ]


#: The teaser's own subdivision of the licence area into named участки.
NAMED_SUBAREA_ROWS = range(50, 54)


def _normalized_site_name(value: str) -> str:
    """Comparison form: case and separator differences are not distinctions."""
    return ' '.join(str(value or '').replace('_', ' ').replace('-', ' ').casefold().split())


def _subarea_patch_violations(
    index: int,
    *,
    row_id: int,
    status: str,
    site_name: str,
    object_name: str,
) -> list[str]:
    """A subarea row must name a subarea, not the object.

    Rows 50-53 are участки 1-3 plus their total. The contract checked that
    `site_name` was *present* and never what it said, so on run `6056e157`
    rows 50, 51 and 52 each carried `site_name = "Лекын-Тальбейская площадь"`
    -- the licence area itself, `object_scope.object_name` verbatim -- across
    five attributes each. One area-level figure landed on three subarea rows,
    from three different press sources, and passed every check.

    This is not what `cohere_resource_estimate_proposals` guards. That
    collapses competing identities *within* one row; this is one figure spread
    *across* rows, which nothing saw.

    Compared on a normalised form, because `Лекын_Талбейское` and
    `Лекын-Тальбейская площадь` are the same area written two ways and a
    separator is not a distinction. Skipped entirely when the caller supplied
    no object name, rather than guessed at.
    """
    if status != 'filled' or row_id not in NAMED_SUBAREA_ROWS:
        return []
    # Every name the run knows the object by, not one of them. Run `92661b9b`
    # shipped `Участок 4` carrying «Лекын-Тальбейская площадь» -- the object,
    # verbatim -- three hours after this rule was deployed, because the name it
    # was handed was the request (`Лекын_Талбейское`) and the two do not
    # normalise alike. The previous round's comment said a check against the
    # request would match neither spelling; it did not follow that through to
    # the case where the request is the only name available.
    names = [object_name] if isinstance(object_name, str) else list(object_name)
    candidates = {_normalized_site_name(name) for name in names if str(name or '').strip()}
    if not candidates:
        return []
    # No separate guard for an absent `site_name`: it cannot equal a non-empty
    # object name, so the comparison below already lets it through, and
    # `_resource_patch_violations` refuses it on its own. Two violations for one
    # mistake is how a repair loop spends an attempt fixing the same thing
    # twice.
    if _normalized_site_name(site_name) not in candidates:
        return []
    return [
        f'patches[{index}] subarea row {row_id} names the object itself '
        f'({site_name!r}); rows {NAMED_SUBAREA_ROWS.start}-'
        f'{NAMED_SUBAREA_ROWS.stop - 1} are named subareas of it, so an '
        f'area-level figure belongs on the area row and not here'
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
    allowed_states = sorted(RESOURCE_ESTIMATE_STATES_BY_ROW[row_id])
    if not entity_id:
        violations.append(
            f'patches[{index}] resource field requires entity_id: set '
            f'source_locator.entity_id to the identifier of the '
            f'{expected_scope} this value belongs to'
        )
    if entity_scope != expected_scope:
        violations.append(
            f'patches[{index}] resource entity_scope must be {expected_scope}; '
            f'got {entity_scope or "(unset)"!r}'
        )
    if estimate_state not in RESOURCE_ESTIMATE_STATES_BY_ROW[row_id]:
        violations.append(
            f'patches[{index}] resource estimate_state is incompatible with '
            f'row {row_id}; allowed: {allowed_states}, got '
            f'{estimate_state or "(unset)"!r}'
        )
    if row_id <= 53 and not resource_estimate_id:
        violations.append(
            f'patches[{index}] resource row requires resource_estimate_id: set '
            'source_locator.resource_estimate_id so two estimates of the same '
            'entity stay distinguishable'
        )
    if 50 <= row_id <= 53 and not site_name:
        violations.append(
            f'patches[{index}] site resource row requires named site_name: set '
            'source_locator.site_name to the subarea this estimate covers'
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
            f'patches[{index}] analogue row requires value_origin=analogue; '
            f'got {origin or "(unset)"!r}'
        )
    if analogue_relation != ANALOGUE_RELATION_BY_ROW[row_id]:
        violations.append(
            f'patches[{index}] analogue relation is incompatible with row '
            f'{row_id}; required: '
            f'{ANALOGUE_RELATION_BY_ROW[row_id]!r}, got '
            f'{analogue_relation or "(unset)"!r}'
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
        # The same treatment the resource rules got, and for the same reason:
        # `KB-GRR-FACTORS 1/3` spent two attempts on this rule -- 18 violations
        # then 12, all of it this one line -- and the line never said which
        # stage row 68 wants. The owner was asked to guess a value the row
        # declares.
        violations.append(
            f'patches[{index}] GRR work_stage is incompatible with row {row_id}; '
            f'required: {GRR_WORK_STAGE_BY_ROW[row_id]!r}, got '
            f'{work_stage or "(unset)"!r}'
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
