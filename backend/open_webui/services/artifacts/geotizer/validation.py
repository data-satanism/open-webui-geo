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


def resource_row_identity_conflicts(
    next_batch: Mapping[str, Any],
    patches: Sequence[Any],
) -> dict[int, dict[str, list[str]]]:
    """Rows whose filled patches disagree about which estimate they report.

    Row -> qualifier -> the two or more values, sorted. Returned as data rather
    than as sentences because two callers need it: this module turns it into
    violations, and `owner_envelope.refuse_incoherent_resource_rows` turns it
    into a row marked for expert review. Parsing the sentences back would be
    the same table written twice, one of the copies in a regex.

    Which rows and which keys come from `ESTIMATE_ROW_IDENTITY_QUALIFIERS`, so
    the identity a row is held to is the identity its `required_qualifiers`
    declare -- per row, which the previous single list could not express.
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
    violations.extend(_locator_ref_violations(index, patch, source_ids))
    return violations


def locator_source_refs(locator: Any) -> list[str]:
    """Every `source_ref` a locator records, at any depth.

    The same walk `owner_envelope._rename_locator_refs` performs, and for the
    same reason it had to become generic: a locator is a free-form record and a
    ref can be anywhere in it. `negative_findings[].source_ref`,
    `candidates[].source_ref` and `spatial_divergence.measured[].source_ref`
    are the three that exist today; walking the whole structure cannot fall
    behind the next one.
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
    """A ref recorded inside the locator must name a source the envelope has.

    `source_refs` on the patch has been checked against the inventory since the
    contract existed; the refs *inside* the locator never were, and they are
    the ones a reader follows to see the other side of a conflict or what a
    negative search actually consulted.

    Run `6e68eeec` is the measurement: eight refs across five cells resolved
    against nothing -- «vsluh-2007-07-03__geotizer_object.v1.r068.a05» on three
    `negative_findings`, two `candidates` on r081.a01, two on r087.a01. All
    eight are ids the owner cited without registering, so
    `merge_owner_envelopes` had no rename for them and they reached the
    finalized state naming sources that do not exist. `dangling_source_refs` in
    the render-readiness audit is the backstop that caught it, and a backstop
    firing means the gate upstream is missing.
    """
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


#: Words that mark a name as naming the whole licensed area rather than a part
#: of it. `site_name = "Лекын-Тальбейская площадь"` on row 50 of run
#: `f480a072` is the object, and the separator-and-case comparison below could
#: not see it: the object is registered as «Лекын_Талбейское», and
#: «Талбейское» and «Тальбейская площадь» do not normalise alike.
AREA_SCOPE_WORDS = ('площадь', 'месторождение', 'лицензионн', 'участок недр')

#: A subarea is numbered. «Участок 2», «Лекын-Тальбейский участок 2» — the
#: digit is what makes it a part, and its presence is what keeps this check
#: off a genuinely named subarea whose name happens to share the object's
#: leading word.
_SUBAREA_ORDINAL = re.compile(r'\d')


def _names_the_whole_area(site_name: str, candidates: set[str]) -> bool:
    """True when `site_name` is the object under a different ending.

    The exact comparison catches «Лекын-Тальбейская площадь» against
    «Лекын-Тальбейская площадь» and misses it against «Лекын_Талбейское»,
    which is how run `f480a072` put a 1976 area-level report on the «Участок
    1» row while the rule that exists for exactly that was watching.

    Russian morphology is why: the endings differ, the stem does not. Rather
    than stem — which needs a dictionary this service has no business carrying
    — this asks three questions that are cheap and specific. Does the name
    start with the same word the object does? Does it carry a word that marks
    a whole area? And does it lack the digit that a numbered part would have?

    All three, so «Лекын-Тальбейский участок 2» is left alone: it starts the
    same way and it is numbered, which makes it a part and not the whole.
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
    # The row's own label is not a value. Run `f480a072` put «Участок 4» in
    # r053's «значение» cell, which asks for a resource figure: the row is
    # «Участок 4 - ресурсы (условные P1)» and its `site_name` is «Участок 4»,
    # so the cell restates the row's identity and reports nothing. Checked
    # before everything else, because it needs no object name to compare
    # against and it is a different mistake with a different repair --
    # reporting the other one would send the fix to the wrong place.
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


#: What to do when the row's contract can be satisfied by no value at all.
#:
#: Run `06fec58d` lost 25 cells to this. Its owner wrote the object's own name
#: into the subarea rows 50-53, was refused three times with a message saying
#: exactly what was wrong and never what was right, and the chunk ended
#: `agent_contract_failed`. The object has no named subareas, so no value
#: satisfies those rows: the only answer that closes them is a status, and the
#: feedback did not say which. Run `94124958`, same build, same batch, answered
#: `not_applicable` and kept the chunk. That difference is most of 191 against
#: 207.
#:
#: The rule is not weakened -- `06fec58d`'s owner was wrong and the refusal was
#: right. What failed is the repair loop, which spent three attempts and 63 KB
#: re-sending a message that could not lead anywhere.
#:
#: This is the `work_stage` shape for the third time: there the model was told
#: which qualifier and not where to put it, here which value is wrong and not
#: which status is right.
NO_VALUE_SATISFIES_EXIT_RU = (
    'Если {condition}, подходящего значения не существует: верните '
    'status: not_applicable с причиной, а не другое значение.'
)


def _with_exit(violation: str, *, condition: str) -> str:
    """A refusal that can be unsatisfiable, with the status that closes it."""
    return f'{violation}. {NO_VALUE_SATISFIES_EXIT_RU.format(condition=condition)}'


#: The condition under which each unsatisfiable family has no answer.
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

    «Значение» and «объем руды» sit on the same row and are not the same
    number. One is what the deposit contains and the other is how much rock
    holds it, and both are quoted in млн т, so nothing about the value or its
    unit distinguishes them -- run `973999df` is what that costs, with a metal
    mass standing where an ore tonnage belongs. The value kind is the only
    thing that can tell them apart, and this is where it is made to.

    Two checks, and they fail differently on purpose:

    The value kind is refused when it contradicts the attribute. `ore_tonnage`
    in «значение» is a mismatch the cell cannot absorb.

    The unit is refused only when this side recognises it *and* it belongs to
    another dimension -- a grade in тонны, a depth in г/т. An unlisted unit is
    not evidence of anything; refusing it would reject a correct value for
    being spelled unusually, and `RESOURCE_UNITS_BY_FAMILY` says in as many
    words that it is not exhaustive.

    An absent value kind is not refused here yet. Until this round the
    resource rows never told the model that `value_kind` was wanted --
    `semantic_hint` emitted `allowed_value_kinds` for the GRR plan rows and
    for nothing else -- so requiring it would refuse owners for omitting a
    field they were never asked for. Requiring it is the next round's change,
    once a run shows the hint arriving.
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
        # The same treatment the resource rules got, and for the same reason:
        # `KB-GRR-FACTORS 1/3` spent two attempts on this rule -- 18 violations
        # then 12, all of it this one line -- and the line never said which
        # stage row 68 wants. The owner was asked to guess a value the row
        # declares.
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


#: A note that says in words that its evidence is historical. Unambiguous in
#: both languages, so they stay substrings.
_HISTORICAL_WORDS = ('historical', 'историческ')

#: And a note that dates its evidence before the plan. A whole token, which is
#: the whole of the change: the markers were the bare substrings `197`, `198`,
#: `199`, `200` and `201`, and a bare substring is not a year.
#:
#: What they matched instead, on rows 68-76 of the exported runs: a run id.
#: Fourteen accepted cells of run `e4368779` carry «Восстановлено из ранее
#: завершённого прогона 8b3cd8a2-aefa-45f4-8148-25d5a1970293» in their note,
#: and `197` is inside that uuid. They also match «стр. 200», «201 млн» and
#: «1 200 м». Row 68's fifth attribute is «срок», so a note about a schedule is
#: where a page number and a duration are most likely to be.
#:
#: `выполнен` and `проведен` went with them. Both are tense-neutral stems:
#: «срок выполнения работ» is the standard name for a *planned* period and
#: «работы будут проведены» is future, while the completed-work note they were
#: meant to catch dates itself and is caught by the year. Three cells of run
#: `d0a464be` -- r068.a05, r069.a05, r070.a05, all «срок» -- were refused three
#: times each with this violation and repaired none of them, which is what a
#: rule that cannot be satisfied looks like from the owner's side.
_PLAN_NOTE_PAST_YEAR = re.compile(r'\b(19\d{2}|20[01]\d)\b')


def _note_dates_itself_before_the_plan(note: str) -> bool:
    """Whether a retrieval note describes work that is already done.

    Read on the note, which is prose the model writes to say where it looked,
    and so a weak signal by construction. The strong one is `temporal_role`,
    which the contract requires on rows 68-76 and which the check above reads
    -- and which is unset on 32 of the 70 marker-carrying plan cells in the
    exported corpus, so it is not doing the work either. Both facts are GMM
    attention register A-87; this function only stops the false half.
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
