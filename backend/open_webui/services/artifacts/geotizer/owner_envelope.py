"""The GeoTeaser owner envelope: batching, extraction, merge and repair.

GeoTeaser-specific logic lives here and nowhere else.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Literal
from ...geotizer.errors import GeotizerOrchestrationError
from ...geotizer.semantics import (
    canonical_unit,
    states_a_conversion,
    unit_named_in_locator,
    ABSOLUTE_AGE_FIELD_KEYS,
    ELEMENT_FIELD_KEYS,
    GRR_WORK_STAGE_BY_ROW,
    MINERAL_FIELD_KEYS,
    ORE_TONNAGE_ATTRIBUTES,
    expects_a_number,
    is_a_work_year,
    names_a_mineral,
    names_an_element,
    semantic_hint,
    states_metal_mass,
    states_no_quantity,
)
from ...project_evidence.resource_coherence import _resource_row
from ...project_evidence.retrieval import (
    build_retrieval_plans,
)
from .validation import (
    _contract_violations,
    _partition_violations,
    locator_source_refs,
    resource_row_identity_conflicts,
    validate_owner_envelope,
)
from ...core.vocabulary import _is_negative_value_marker
from ...core.tasks import (
    AgentTask,
)
from ...core.text import (
    _decode_embedded_objects,
    _is_nonstring_sequence,
    _strip_json_fence,
    bounded_text,
    extract_json_object,
    locator_map,
)
from ...project_evidence.proposals import (
    _review_hypothesis,
    normalize_contributor_evidence,
)


RUN_NOTE_KEY_SAMPLE = 6


def cells_note(template: str, field_keys: Sequence[str], **fields: Any) -> dict[str, Any]:
    """One rule's verdict on some cells, before it is a sentence.

    Returns the template, the cell keys and the format fields.
    `render_run_notes` renders the notes of one template and one set of field
    values as a single sentence for the whole run, so two notes are the same
    rule exactly when the same template produced them.
    """
    return {
        'template': template,
        'field_keys': [str(field_key) for field_key in field_keys],
        'fields': dict(fields),
    }


def render_run_notes(notes: Sequence[Any]) -> list[str]:
    """One sentence per rule per run, in the order the rules first fired.

    Notes from `cells_note` are grouped by template and field values, and the
    template is formatted with `count` and at most `RUN_NOTE_KEY_SAMPLE`
    sorted `keys`. Any other note is rendered as its stripped string,
    deduplicated.
    """
    rendered: list[str] = []
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for note in notes:
        if not isinstance(note, Mapping) or 'template' not in note:
            text = str(note).strip()
            if text and text not in rendered:
                rendered.append(text)
            continue
        fields = dict(note.get('fields') or {})
        key = (str(note['template']), tuple(sorted((k, str(v)) for k, v in fields.items())))
        entry = grouped.get(key)
        if entry is None:
            entry = {'template': str(note['template']), 'fields': fields, 'field_keys': []}
            grouped[key] = entry
            order.append(key)
        for field_key in note.get('field_keys') or ():
            if field_key not in entry['field_keys']:
                entry['field_keys'].append(str(field_key))
    for key in order:
        entry = grouped[key]
        keys = sorted(entry['field_keys'])
        listed = ', '.join(keys[:RUN_NOTE_KEY_SAMPLE])
        rendered.append(
            entry['template'].format(
                count=len(keys),
                keys=f'{listed}{"…" if len(keys) > RUN_NOTE_KEY_SAMPLE else ""}',
                **entry['fields'],
            )
        )
    return rendered


def execution_mode_for_task(
    task: AgentTask,
) -> Literal[
    'specialist_contributor',
    'specialist_owner_completion',
    'tool_free_owner',
]:
    """Keep state-changing tools outside every bounded owner decision.

    Returns `tool_free_owner` for the `skilled` agent's owner task,
    `specialist_owner_completion` for any other owner task, and
    `specialist_contributor` for a contributor.
    """
    if task.role == 'owner' and task.agent == 'skilled':
        return 'tool_free_owner'
    if task.role == 'owner':
        return 'specialist_owner_completion'
    return 'specialist_contributor'


def build_batch_tasks(next_batch: Mapping[str, Any]) -> tuple[AgentTask, ...]:
    """Plan contributor calls before the single exact owner call.

    Returns one contributor task per evidence route satisfied by
    `contributor_call`, then the owner task. The producer is passed verbatim
    into `AgentTask.agent` and is not validated here. Raises
    `GeotizerOrchestrationError` when `batch_id` or `producer` is missing, or
    a contributor route id is empty or repeated.
    """
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
                agent=producer,
                producer=producer,
                role='contributor',
                task_id=route_id,
                payload=dict(route),
            )
        )

    tasks.append(
        AgentTask(
            agent=owner,
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


def _rename_locator_refs(locator: Any, renamed_refs: Mapping[str, str]) -> Any:
    """Point every recorded ref in a locator at the id the merged state holds."""
    if isinstance(locator, Mapping):
        renamed: dict[str, Any] = {}
        for key, value in locator.items():
            if key == 'source_ref' and isinstance(value, str):
                renamed[key] = renamed_refs.get(value, value)
            elif key == 'source_refs' and isinstance(value, list):
                renamed[key] = [
                    renamed_refs.get(item, item) if isinstance(item, str) else _rename_locator_refs(item, renamed_refs)
                    for item in value
                ]
            else:
                renamed[key] = _rename_locator_refs(value, renamed_refs)
        return renamed
    if isinstance(locator, list):
        return [_rename_locator_refs(item, renamed_refs) for item in locator]
    return locator


INCOHERENT_ESTIMATE_ROW_TRACE = 'resource_row_reports_more_than_one_estimate'


def refuse_incoherent_resource_rows(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Mark a row that reports two estimates; do not end the run over it.

    Each `filled` cell of a resource row that `resource_row_identity_conflicts`
    reports becomes `requires_expert_review`: its value names the conflicting
    identities and quotes the value the cell carried, `value_origin` is
    cleared, and `source_locator.coherence_refusal` is set to
    `INCOHERENT_ESTIMATE_ROW_TRACE`. Returns the envelope and one run note per
    conflicting row.
    """
    conflicts = resource_row_identity_conflicts(next_batch, envelope.get('patches') or [])
    if not conflicts:
        return dict(envelope), []

    row_by_key = {
        str(field.get('field_key') or ''): int(field.get('row_id') or 0)
        for field in next_batch.get('fields') or []
    }
    notes: list[str] = []
    marked: list[dict[str, Any]] = []
    for raw_patch in envelope.get('patches') or []:
        patch = dict(raw_patch) if isinstance(raw_patch, Mapping) else raw_patch
        row_id = row_by_key.get(str(patch.get('field_key') or '')) if isinstance(patch, Mapping) else None
        if not isinstance(patch, Mapping) or row_id not in conflicts or patch.get('status') != 'filled':
            marked.append(patch)
            continue
        stated = '; '.join(
            f'{qualifier}: {", ".join(values)}'
            for qualifier, values in conflicts[row_id].items()
        )
        found = str(patch.get('value') or '').strip()
        patch['status'] = 'requires_expert_review'
        patch['value'] = (
            f'ТРЕБУЕТСЯ ПРОВЕРКА ЭКСПЕРТА: строка {row_id} собрана из более чем одной '
            f'оценки ({stated}). Найденное значение этой ячейки: {found or "—"}. '
            'Атрибуты разных оценок нельзя читать как одну строку, поэтому значение '
            'не опубликовано как подтверждённое.'
        )
        patch['value_origin'] = None
        locator = patch.get('source_locator')
        patch['source_locator'] = {
            **(locator if isinstance(locator, Mapping) else {'original_locator': locator}),
            'coherence_refusal': INCOHERENT_ESTIMATE_ROW_TRACE,
        }
        marked.append(patch)

    for row_id, row_conflicts in conflicts.items():
        stated = '; '.join(
            f'{qualifier}: {", ".join(values)}'
            for qualifier, values in row_conflicts.items()
        )
        notes.append(
            cells_note(
                'Строка ресурсов {row_id}: атрибуты относятся к разным оценкам '
                '({stated}). Строка помечена как требующая проверки эксперта; '
                'остальные строки заполнены.',
                (),
                row_id=row_id,
                stated=stated,
            )
        )
    return {**envelope, 'patches': marked}, notes


NEGATIVE_SEARCH_WHERE_RU = 'Где искали: {where}.'
NEGATIVE_FINDING_NOTE_RU = ' Результат поиска: {findings}.'


EMPTY_CELL_STATUSES = ('not_found', 'not_applicable')

EMPTY_CELL_REASON_PREFIX_RU = {
    'not_found': 'Значение не найдено.',
    'not_applicable': 'Строка неприменима к этому объекту.',
}

PROJECTED_REASON_STATUS_KEY = 'projected_reason_for'

INVALID_SCOPE_REASON_RU = (
    'Поиск выполнен в области, не являющейся коллекцией базы знаний. '
    'База знаний не открывалась; значение не искали.'
)


def state_the_negative_search(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Give an empty cell the reason the state already holds for it.

    A patch with a status in `EMPTY_CELL_STATUSES`, no `retrieval_note`, and a
    locator naming where the search went gets a note composed from the
    locator: the status's prefix, where it searched and, when present, what
    its `negative_findings` returned. The status the note was written for is
    stamped under `PROJECTED_REASON_STATUS_KEY`. Any other patch is left
    unchanged. Returns the envelope and a run note listing the repaired cells.
    """
    patches = envelope.get('patches') or []
    if not patches:
        return dict(envelope), []

    written: list[str] = []
    projected: list[dict[str, Any]] = []
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            projected.append(raw_patch)
            continue
        patch = dict(raw_patch)
        status = str(patch.get('status') or '')
        if status not in EMPTY_CELL_STATUSES or str(patch.get('retrieval_note') or '').strip():
            projected.append(patch)
            continue
        locator = patch.get('source_locator')
        semantic = locator if isinstance(locator, Mapping) else {}
        where = str(semantic.get('page_or_chunk_or_layer_or_feature_or_query') or '').strip()
        if not where:
            projected.append(patch)
            continue
        note = (
            f'{EMPTY_CELL_REASON_PREFIX_RU[status]} '
            f'{NEGATIVE_SEARCH_WHERE_RU.format(where=where)}'
        )
        findings = [
            str((finding.get('locator') or {}).get('page_chunk_section') or '').strip()
            for finding in semantic.get('negative_findings') or []
            if isinstance(finding, Mapping) and isinstance(finding.get('locator'), Mapping)
        ]
        findings = [finding for finding in findings if finding]
        if findings:
            note += NEGATIVE_FINDING_NOTE_RU.format(findings='; '.join(dict.fromkeys(findings)))
        patch['retrieval_note'] = note
        stamped = locator_map(locator)
        stamped[PROJECTED_REASON_STATUS_KEY] = status
        patch['source_locator'] = stamped
        written.append(str(patch.get('field_key') or ''))
        projected.append(patch)

    if not written:
        return dict(envelope), []
    return (
        {**envelope, 'patches': projected},
        [
            cells_note(
                'Причина восстановлена на {count} ячейках: примечание было '
                'пустым, причина взята из source_locator ({keys}).',
                written,
            )
        ],
    )


UNREGISTERED_LOCATOR_REF_TYPE = 'derived'


def register_locator_only_sources(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    run_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Give every ref recorded inside a locator a source it can resolve against.

    Each ref that `locator_source_refs` finds in a patch's `source_locator`
    and that is not in the inventory is registered as a source of type
    `UNREGISTERED_LOCATOR_REF_TYPE`, whose title and locator say who cited it
    and where. Returns the envelope and a run note listing the registered
    refs.
    """
    patches = envelope.get('patches') or []
    if not patches:
        return dict(envelope), []
    inventory = [dict(source) for source in envelope.get('source_inventory') or []]
    known = {str(source.get('source_id') or '') for source in inventory}
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    chunk = next_batch.get('owner_chunk') or {}

    registered: list[str] = []
    for patch in patches:
        if not isinstance(patch, Mapping):
            continue
        field_key = str(patch.get('field_key') or '')
        for ref in locator_source_refs(patch.get('source_locator')):
            if not ref or ref in known:
                continue
            known.add(ref)
            registered.append(ref)
            inventory.append(
                {
                    'source_id': ref,
                    'source_type': UNREGISTERED_LOCATOR_REF_TYPE,
                    'title': (
                        f'{producer} cited {ref} in source_locator without registering it'
                    ),
                    'locator': (
                        f'run_id={run_id}; batch_id={batch_id}; '
                        f'owner_chunk={int(chunk.get("index") or 1)}/'
                        f'{int(chunk.get("total") or 1)}; field_key={field_key}'
                    ),
                    'url': None,
                }
            )
    if not registered:
        return dict(envelope), []
    return (
        {**envelope, 'source_inventory': inventory},
        [
            cells_note(
                '{count} источников процитированы в source_locator и не '
                'зарегистрированы владельцем — зарегистрированы как derived, '
                'чтобы ссылки разрешались ({keys}).',
                registered,
            )
        ],
    )


def merge_owner_envelopes(
    next_batch: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Merge validated chunk envelopes into one atomic GIS batch submission.

    Each chunk's sources are renamed `<batch_id>__part_<n>__<source_id>`, with
    the batch id lower-cased and a numeric suffix on a collision, and every
    `source_refs` entry and locator ref follows the rename.
    `refuse_incoherent_resource_rows` runs on each chunk and on the merged
    envelope. Returns the submission and the run notes the merge produced;
    the notes are not part of the envelope. Raises
    `GeotizerOrchestrationError` when chunks and envelopes are not one
    non-empty partition, or when a chunk or the merged envelope fails
    `validate_owner_envelope`.
    """
    if len(chunks) != len(envelopes) or not chunks:
        raise GeotizerOrchestrationError('Owner chunks and envelopes must form one non-empty partition')

    sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    patches: list[dict[str, Any]] = []
    coherence_notes: list[str] = []
    for chunk_index, (chunk, envelope) in enumerate(
        zip(chunks, envelopes, strict=True),
        start=1,
    ):
        envelope, chunk_notes = refuse_incoherent_resource_rows(chunk, envelope)
        coherence_notes.extend(chunk_notes)
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
            patch['source_locator'] = _rename_locator_refs(patch.get('source_locator'), renamed_refs)
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
    merged, merged_notes = refuse_incoherent_resource_rows(next_batch, merged)
    for note in merged_notes:
        if note not in coherence_notes:
            coherence_notes.append(note)
    violations = validate_owner_envelope(next_batch, merged)
    if violations:
        raise GeotizerOrchestrationError('; '.join(violations))
    return merged, coherence_notes


EMPTY_RESPONSE = 'empty'
UNPARSEABLE_RESPONSE = 'unparseable'
PARSED_RESPONSE = 'parsed'


def _owner_failure_sentence(
    attempts: int,
    attempt_diagnostics: Sequence[Mapping[str, Any]],
    specialist_failures: Sequence[Mapping[str, Any]] = (),
    stopped_by_deadline: bool = False,
    unactionable_feedback: bool = False,
) -> str:
    """Say which way the owner failed.

    The first case that applies wins: the fill deadline was reached before
    any call, a specialist reported its own failure, the same violations came
    back on consecutive attempts, every attempt was empty, no attempt held a
    usable envelope, and otherwise the envelope failed the field contract.
    """
    if stopped_by_deadline:
        return (
            'The fill deadline was reached before these fields were '
            'requested, so no specialist and no owner call was made for them. '
            'This is a run that ran out of wall-clock time, not a run whose '
            'evidence was refused -- rerunning the object is what recovers '
            'them.'
        )
    if specialist_failures:
        return specialist_failure_sentence(specialist_failures)
    modes = [str(item.get('response_mode') or '') for item in attempt_diagnostics]
    plural = 'attempt' if attempts == 1 else 'attempts'
    if unactionable_feedback:
        return (
            'The owner reached the field contract and was refused with the '
            f'same violations on {attempts} consecutive {plural}, so the loop '
            'stopped rather than spend a third. This is unactionable feedback '
            'rather than a contract failure: the objection is stated and the '
            'answer that would satisfy it is not, so re-running the object '
            'repeats it. Read the violations below and give the rule an exit.'
        )
    if modes and all(mode == EMPTY_RESPONSE for mode in modes):
        return (
            'Specialist evidence was requested, but the owner returned no '
            f'output at all on {attempts} consecutive {plural}. The field '
            'contract was never reached, so this is a specialist-call failure '
            'rather than a rejected answer.'
        )
    if modes and all(mode != PARSED_RESPONSE for mode in modes):
        return (
            'Specialist evidence was requested, but no owner response in '
            f'{attempts} {plural} contained a usable envelope. The field '
            'contract was never reached; see `text_prefix` in the attempt '
            'diagnostics for what was written instead.'
        )
    return (
        'Specialist evidence was requested, but the owner response did not '
        f'satisfy the deterministic field contract after {attempts} {plural}.'
    )


AGENT_FAILURE_STATUS = 'agent_contract_failed'
EXPERT_REVIEW_STATUS = 'requires_expert_review'


def failure_status_for(next_batch: Mapping[str, Any]) -> str:
    """Which status this run's fallback patches may carry.

    `ASSEMBLE` always gets `EXPERT_REVIEW_STATUS`. Any other batch gets
    `AGENT_FAILURE_STATUS` when its `accepted_field_statuses` lists it, and
    `EXPERT_REVIEW_STATUS` otherwise.
    """
    if str(next_batch.get('batch_id') or '') == 'ASSEMBLE':
        return EXPERT_REVIEW_STATUS
    accepted = next_batch.get('accepted_field_statuses')
    if isinstance(accepted, Sequence) and not isinstance(accepted, (str, bytes)):
        if AGENT_FAILURE_STATUS in {str(item) for item in accepted}:
            return AGENT_FAILURE_STATUS
    return EXPERT_REVIEW_STATUS


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
    scope_name: Sequence[str] | str = '',
    specialist_failures: Sequence[Mapping[str, Any]] = (),
    ended_in_specialist_failure: bool = True,
    stopped_by_deadline: bool = False,
    unactionable_feedback: bool = False,
) -> dict[str, Any]:
    """Fail closed while preserving individually valid owner decisions.

    Every field of the chunk gets a fallback patch with the failure status,
    no value, and a retrieval note stating the failure and whether any
    violation names that cell; in `ASSEMBLE` the value is a review
    hypothesis. Valid per-field patches from `candidate_envelopes` then
    replace their fallback. `feedback` is the last attempt's violations and
    `feedback_by_attempt` is every attempt's.
    """
    chunk = next_batch.get('owner_chunk') or {}
    chunk_index = int(chunk.get('index') or 1)
    chunk_total = int(chunk.get('total') or 1)
    batch_id = str(next_batch.get('batch_id') or '')
    producer = str(next_batch.get('producer') or '')
    failure_status = failure_status_for(next_batch)
    source_id = f'orchestration-review-{batch_id.lower()}-part-{chunk_index}'
    locator = f'run_id={run_id}; batch_id={batch_id}; owner_chunk={chunk_index}/{chunk_total}; attempts={attempts}'
    feedback_text = bounded_text(
        json.dumps(list(feedback), ensure_ascii=False),
        max_chars=1200,
    )
    failure_sentence = _owner_failure_sentence(
        attempts,
        attempt_diagnostics,
        specialist_failures if ended_in_specialist_failure else (),
        stopped_by_deadline,
        unactionable_feedback=unactionable_feedback,
    )
    feedback_clause = '' if stopped_by_deadline else f' Validation feedback: {feedback_text}'

    chunk_field_keys = [
        str(item.get('field_key') or '') for item in next_batch.get('fields') or []
    ]

    def _names(field_key: str, violation: Any) -> bool:
        """Whether `violation` is about `field_key`, and not about a longer key
        that begins with it.
        """
        if not field_key:
            return False
        return re.search(re.escape(field_key) + r'(?![\w.])', str(violation)) is not None

    def _scope_clause(field_key: str) -> str:
        """The clause saying whether any of the chunk's violations is about THIS cell.

        One sentence when violations name this cell, another when they name
        only other cells, and a third when none names any cell. Empty for a
        deadline stop or an empty key.
        """
        if stopped_by_deadline or not field_key:
            return ''
        own = [item for item in feedback if _names(field_key, item)]
        if own:
            named = bounded_text(json.dumps(own, ensure_ascii=False), max_chars=600)
            return f' Violations naming this cell: {named}.'
        if any(
            _names(other, item) for item in feedback for other in chunk_field_keys
        ):
            return (
                ' No violation names this cell: the chunk answer was refused as '
                'a whole, and the objections below are about other cells in it.'
            )
        return (
            ' No violation names any cell: the chunk failed before its answer '
            'was checked cell by cell.'
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
                'status': failure_status,
                'source_refs': [source_id],
                'source_locator': {
                    'run_id': run_id,
                    'batch_id': batch_id,
                    'owner_chunk': f'{chunk_index}/{chunk_total}',
                    'attempts': attempts,
                    'owner_attempt_diagnostics': [dict(item) for item in attempt_diagnostics],
                    'owner_attempt_feedback': [dict(item) for item in feedback_by_attempt],
                    'specialist_failures': [dict(item) for item in specialist_failures],
                    'stopped_by': 'fill_deadline' if stopped_by_deadline else None,
                },
                'retrieval_note': (
                    failure_sentence
                    + _scope_clause(str(field.get('field_key') or ''))
                    + feedback_clause
                ),
            }
            for field in next_batch.get('fields') or []
        ],
    }
    if batch_id == 'ASSEMBLE':
        for field, patch in zip(
            next_batch.get('fields') or [],
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
        object_name=scope_name or [object_name],
    )


def _salvage_owner_candidates(
    next_batch: Mapping[str, Any],
    fallback: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    object_name: Sequence[str] | str = '',
) -> dict[str, Any]:
    """Keep valid per-field patches even when the complete envelope is invalid.

    Candidates are read from the latest attempt back, and the first valid
    patch per field wins. A patch is accepted when every ref it cites is in
    its candidate's inventory and it passes `validate_owner_envelope` as a
    one-field batch with `object_name`. Accepted sources are renamed
    `salvage-<batch_id>-attempt-<n>__<ref>`, and the fallback's
    contract-failure marks are removed. In `ASSEMBLE`, a
    `requires_expert_review` patch without a value is not salvaged.
    """
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
            if validate_owner_envelope(one_field_batch, one_field_envelope, object_name=object_name):
                continue
            _drop_contract_failure_marks(patch_by_key[field_key])
            patch_by_key[field_key].update(patch)
            result['source_inventory'].extend(sources)
            accepted.add(field_key)
    return result


SALVAGED_CELL_STRIPPED_KEYS = (
    'owner_attempt_feedback',
    'owner_attempt_diagnostics',
    'specialist_failures',
    'stopped_by',
    'attempts',
)


def _drop_contract_failure_marks(patch: dict[str, Any]) -> None:
    """Take the refusal marks off a cell salvage has just accepted a value for.

    Removes `SALVAGED_CELL_STRIPPED_KEYS` from the patch's `source_locator` in
    place. A non-mapping locator is left unchanged.
    """
    locator = patch.get('source_locator')
    if not isinstance(locator, MutableMapping):
        return
    for key in SALVAGED_CELL_STRIPPED_KEYS:
        locator.pop(key, None)


def normalise_patch_locators(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Parse the string form of `source_locator` where the envelope enters.

    A string locator is replaced by `locator_map` of it. An absent locator
    stays absent, and a locator of any other shape stays as it is. Returns a
    new envelope mapping.
    """
    patches = envelope.get('patches')
    if not _is_nonstring_sequence(patches):
        return dict(envelope)
    rewritten = []
    changed = False
    for patch in patches:
        if isinstance(patch, Mapping) and isinstance(patch.get('source_locator'), str):
            rewritten.append({**dict(patch), 'source_locator': locator_map(patch['source_locator'])})
            changed = True
        else:
            rewritten.append(patch)
    if not changed:
        return dict(envelope)
    return {**dict(envelope), 'patches': rewritten}


def extract_owner_envelope(
    text: str,
    next_batch: Mapping[str, Any],
) -> dict[str, Any]:
    """Select one structurally exact owner envelope among incidental JSON objects."""
    try:
        return normalise_patch_locators(extract_json_object(text))
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
            return normalise_patch_locators(next(iter(unique.values())))
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
        ranked.append((recognized, -index, normalise_patch_locators(recovered)))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


PREVIOUS_OUTPUT_CAP = 2000

_VIOLATION_TARGET = re.compile(r'patches\[(\d+)\]')

_VIOLATION_PREFIX = re.compile(r'^patches\[\d+\]\s*(?:\S+\.\S+)?\s*')


MAX_RECORDED_QUERIES = 400


def record_retrieval_queries(
    query_log: list[dict[str, Any]] | None,
    plans: Sequence[Any],
    *,
    batch_id: str,
    chunk: Any,
    agent: str,
) -> None:
    """Record what a specialist was planned to search, so a run can be compared.

    Appends one entry per plan to `query_log`: batch, chunk, agent,
    `query_id`, `status`, `tier_id`, `exact_query`, `must_terms` and
    `should_terms`. Does nothing when `query_log` is None. At
    `MAX_RECORDED_QUERIES` entries it stops and appends one
    `{'truncated': True, 'recorded': MAX_RECORDED_QUERIES}` entry.
    """
    if query_log is None:
        return
    for plan in plans:
        if len(query_log) >= MAX_RECORDED_QUERIES:
            if not any(item.get('truncated') for item in query_log):
                query_log.append({'truncated': True, 'recorded': MAX_RECORDED_QUERIES})
            return
        query_log.append(
            {
                'batch_id': batch_id,
                'chunk': (
                    f'{chunk.get("index")}/{chunk.get("total")}'
                    if isinstance(chunk, Mapping)
                    else None
                ),
                'agent': agent,
                'query_id': getattr(plan, 'query_id', ''),
                'status': getattr(plan, 'status', ''),
                'tier_id': getattr(plan, 'tier_id', ''),
                'exact_query': getattr(plan, 'exact_query', ''),
                'must_terms': list(getattr(plan, 'must_terms', ()) or ()),
                'should_terms': list(getattr(plan, 'should_terms', ()) or ()),
            }
        )


def grouped_repair_feedback(feedback: Any) -> Any:
    """The same violations, collapsed to one entry per distinct rule.

    A violation addressed `patches[N]` is grouped by its text with the
    `patches[N] <field_key>` prefix stripped, as
    `{'patches': [N, ...], 'violation': rule}`; any other violation is
    deduplicated as plain text. When nothing collapses, the list is returned
    ungrouped. A string is treated as a one-item list, and an empty or
    non-sequence value is returned as is.
    """
    if isinstance(feedback, str):
        feedback = [feedback]
    if not isinstance(feedback, Sequence) or not feedback:
        return feedback
    grouped: dict[str, list[int]] = {}
    order: list[str] = []
    for item in feedback:
        text = str(item)
        match = _VIOLATION_TARGET.match(text)
        if match is None:
            if text not in grouped:
                grouped[text] = []
                order.append(text)
            continue
        rule = _VIOLATION_PREFIX.sub('', text, count=1).strip()
        if rule not in grouped:
            grouped[rule] = []
            order.append(rule)
        grouped[rule].append(int(match.group(1)))
    if len(order) == len(feedback):
        return list(feedback)
    return [
        {'patches': grouped[rule], 'violation': rule} if grouped[rule] else rule
        for rule in order
    ]


def bounded_previous_output(previous_output: str, feedback: Any) -> Any:
    """The failed draft, cut down to the patches the violations name.

    Returns `note` and `patches_named_by_feedback`: the patches at the
    `patches[N]` indices the feedback names, with whole patches dropped from
    the end until the selection fits `PREVIOUS_OUTPUT_CAP` or one remains.
    The note says how many are shown and that the owner must return one
    patch per field. Falls back to `_capped` text when no violation names a
    patch, no patches can be parsed from the draft, or no named index exists
    in it. A blank or non-string draft is returned unchanged.
    """
    if not isinstance(previous_output, str) or not previous_output.strip():
        return previous_output
    indices = _violation_patch_indices(feedback)
    patches = _previous_patches(previous_output)
    if not indices or patches is None:
        return _capped(previous_output)

    selected = [
        {'index': index, 'patch': patches[index]}
        for index in sorted(indices)
        if 0 <= index < len(patches)
    ]
    if not selected:
        return _capped(previous_output)

    kept = selected
    while len(kept) > 1 and len(json.dumps(kept, ensure_ascii=False)) > PREVIOUS_OUTPUT_CAP:
        kept = kept[:-1]
    return {
        'note': (
            f'Showing {len(kept)} of the {len(selected)} patches named by '
            f'repair_feedback, out of {len(patches)} in the previous attempt '
            f'({len(previous_output)} characters). Return the complete array '
            f'of one patch per field in batch.fields, not only these. Every '
            f'patch named by repair_feedback needs the same correction '
            f'whether or not it is shown here.'
        ),
        'patches_named_by_feedback': kept,
    }


def _violation_patch_indices(feedback: Any) -> set[int]:
    if isinstance(feedback, str):
        feedback = [feedback]
    if not isinstance(feedback, Sequence):
        return set()
    return {
        int(match.group(1))
        for item in feedback
        for match in _VIOLATION_TARGET.finditer(str(item))
    }


def _previous_patches(previous_output: str) -> list[Any] | None:
    for candidate in _owner_payload_candidates(previous_output):
        patches = candidate.get('patches')
        if isinstance(patches, list) and patches:
            return patches
    return None


def _capped(previous_output: str) -> str:
    """Head and tail, with the omitted middle counted rather than elided.

    Text within `PREVIOUS_OUTPUT_CAP` is returned unchanged.
    """
    if len(previous_output) <= PREVIOUS_OUTPUT_CAP:
        return previous_output
    half = PREVIOUS_OUTPUT_CAP // 2
    omitted = len(previous_output) - 2 * half
    return f'{previous_output[:half]}\n\n[... {omitted} characters omitted ...]\n\n{previous_output[-half:]}'


SPECIALIST_FAILED_MARKER = 'specialist_failed'

MAX_CONSECUTIVE_SPECIALIST_FAILURES = 2


def specialist_failure_signal(text: Any) -> dict[str, Any] | None:
    """The specialist saying its own call failed, or None.

    Only a JSON payload whose own `status` is `SPECIALIST_FAILED_MARKER`
    counts. Returns `agent`, `code`, `detail` (bounded to 400 characters),
    `retryable` (True, False, or None when the payload does not state it),
    and the `usage` and `reasoning_only` keys from `_specialist_usage`.
    """
    rendered = text if isinstance(text, str) else str(text or '')
    if SPECIALIST_FAILED_MARKER not in rendered:
        return None
    for root in _owner_payload_roots(_strip_json_fence(rendered)):
        if not isinstance(root, Mapping):
            continue
        if str(root.get('status') or '') != SPECIALIST_FAILED_MARKER:
            continue
        return {
            'agent': str(root.get('agent') or ''),
            'code': str(root.get('code') or ''),
            'detail': bounded_text(str(root.get('detail') or ''), max_chars=400),
            'retryable': (
                root.get('retryable')
                if isinstance(root.get('retryable'), bool) else None
            ),
            **_specialist_usage(root.get('usage')),
        }
    return None


SPECIALIST_USAGE_KEYS = (
    'finish_reason',
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
    'reasoning_tokens',
)


ORCHESTRATOR_ROUND_KEYS = (
    *SPECIALIST_USAGE_KEYS,
    'content_chars',
    'reasoning_chars',
    'tool_call_count',
    'compacted_chars',
)


def _specialist_usage(usage: Any) -> dict[str, Any]:
    """The envelope's own usage block, reduced to `SPECIALIST_USAGE_KEYS`.

    Returns `usage`, holding the keys whose value is not None, and
    `reasoning_only`; `{}` when no such key is present. An absent key stays
    absent.
    """
    if not isinstance(usage, Mapping):
        return {}
    read = {
        key: usage[key]
        for key in SPECIALIST_USAGE_KEYS
        if usage.get(key) is not None
    }
    if not read:
        return {}
    return {'usage': read, 'reasoning_only': _is_reasoning_only(read)}


def _is_reasoning_only(usage: Mapping[str, Any]) -> bool:
    """Whether `reasoning_tokens` is a number above zero.

    A usage block without `reasoning_tokens` yields False.
    """
    tokens = usage.get('reasoning_tokens')
    return isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and tokens > 0


MAX_RECORDED_SPECIALIST_ROUNDS = 500


def chunk_marker(value: Any, *, batch_id: str = '') -> dict[str, Any] | None:
    """The one shape a chunk is written in, from either shape it arrives in.

    Accepts a mapping with `index`, `total` and `batch_id`, an int index, or a
    string `'i/n'` or `'i'`, and returns `index`, plus `total` and `batch_id`
    when known. Returns None for a boolean or any value without an integer
    index. `normalize_chunk_marker` in `gis_service`'s
    `arcgis_mcp/geotizer/core.py` is the same function on the other side of
    the boundary.
    """
    index: Any = None
    total: Any = None
    if isinstance(value, Mapping):
        index, total = value.get('index'), value.get('total')
        batch_id = str(value.get('batch_id') or batch_id)
    elif isinstance(value, bool):
        return None
    elif isinstance(value, int):
        index = value
    elif isinstance(value, str):
        halves = value.split('/')
        if len(halves) == 2 and all(half.strip().isdigit() for half in halves):
            index, total = int(halves[0]), int(halves[1])
        elif value.strip().isdigit():
            index = int(value.strip())
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    marker: dict[str, Any] = {'index': index}
    if isinstance(total, int) and not isinstance(total, bool):
        marker['total'] = total
    if batch_id:
        marker['batch_id'] = str(batch_id)
    return marker


def stamp_chunk_provenance(
    envelope: Mapping[str, Any],
    *,
    chunk: Any,
    failures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Put the chunk, and what it failed to hear, on every cell it owned.

    Every patch, whatever its status, gets `owner_chunk` (the `chunk_marker`)
    and, when there are failures, `evidence_incomplete`: the distinct
    agent/code pairs, sorted. No status or value changes. The envelope is
    returned unchanged when there is neither a marker nor a failure.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope)
    marker = chunk_marker(chunk, batch_id=str(envelope.get('batch_id') or ''))
    missing = []
    for failure in failures or ():
        if not isinstance(failure, Mapping):
            continue
        record = {
            'agent': str(failure.get('agent') or ''),
            'code': str(failure.get('code') or ''),
        }
        if (record['agent'] or record['code']) and record not in missing:
            missing.append(record)
    missing.sort(key=lambda item: (item['agent'], item['code']))
    if marker is None and not missing:
        return dict(envelope)
    stamped = []
    for patch in patches:
        if not isinstance(patch, Mapping):
            stamped.append(patch)
            continue
        entry = dict(patch)
        if marker is not None:
            entry['owner_chunk'] = dict(marker)
        if missing:
            entry['evidence_incomplete'] = [dict(item) for item in missing]
        stamped.append(entry)
    return {**envelope, 'patches': stamped}


def specialist_round_record(
    signal: Mapping[str, Any],
    *,
    role: str,
    batch_id: str,
    chunk: Any = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """One specialist round that reported its own failure, placed in the run.

    Carries `role`, `batch_id`, `agent` and `code`; `retryable` only when the
    signal states a bool; `chunk` and `attempt` when given; and `usage`,
    `reasoning_only` and `detail` when non-empty.
    """
    record = {
        'role': role,
        'batch_id': batch_id,
        'agent': str(signal.get('agent') or ''),
        'code': str(signal.get('code') or ''),
    }
    if isinstance(signal.get('retryable'), bool):
        record['retryable'] = signal['retryable']
    if chunk is not None:
        record['chunk'] = chunk
    if attempt is not None:
        record['attempt'] = attempt
    for key in ('usage', 'reasoning_only', 'detail'):
        if signal.get(key) not in (None, '', {}):
            record[key] = signal[key]
    return record


class SpecialistRoundLog:
    """Every failed round counted; a bounded prefix of them kept.

    `records` keeps the first `cap` failure records. The counts (`issued`, by
    code, by agent, by chunk, `reasoning_only`, `unattributed`) cover every
    failure and are not bounded. `observe_round` also keeps every round,
    failed or not, for `usage_stats`.
    """

    def __init__(self, *, cap: int = MAX_RECORDED_SPECIALIST_ROUNDS) -> None:
        self.cap = cap
        self.records: list[dict[str, Any]] = []
        self._issued = 0
        self._rounds: list[dict[str, Any]] = []
        self._round_source = 'specialist_calls'
        self._by_code: dict[str, int] = {}
        self._by_agent: dict[str, int] = {}
        self._reasoning_only = 0
        self._by_chunk: dict[tuple[str, int], list[dict[str, str]]] = {}
        self._unattributed = 0

    def add(self, record: Mapping[str, Any]) -> None:
        """Count it, then keep it if there is room. Never the other way round."""
        self._issued += 1
        code = str(record.get('code') or '')
        agent = str(record.get('agent') or '')
        marker = chunk_marker(record.get('chunk'), batch_id=str(record.get('batch_id') or ''))
        if marker is not None:
            key = (str(record.get('batch_id') or ''), marker['index'])
            self._by_chunk.setdefault(key, []).append({'agent': agent, 'code': code})
        self._by_code[code] = self._by_code.get(code, 0) + 1
        self._by_agent[agent] = self._by_agent.get(agent, 0) + 1
        if record.get('reasoning_only'):
            self._reasoning_only += 1
        elif not record.get('usage'):
            self._unattributed += 1
        if len(self.records) < self.cap:
            self.records.append(dict(record))

    @property
    def issued(self) -> int:
        return self._issued

    @property
    def dropped(self) -> int:
        return self._issued - len(self.records)

    def observe_round(
        self,
        *,
        agent: str,
        batch_id: str,
        chunk: Any = None,
        outcome: str,
        usage: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
    ) -> None:
        """One specialist round, whatever it did.

        The single entry point per round: it records the round and, when
        `failure` is given, passes it to `add`. From `usage` it keeps numeric
        `SPECIALIST_USAGE_KEYS` values and a non-empty string `finish_reason`.
        """
        entry: dict[str, Any] = {
            'agent': str(agent or ''),
            'batch_id': str(batch_id or ''),
            'outcome': str(outcome or ''),
        }
        marker = chunk_marker(chunk, batch_id=str(batch_id or ''))
        if marker is not None:
            entry['chunk'] = marker
        for key in SPECIALIST_USAGE_KEYS:
            value = (usage or {}).get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[key] = value
            elif key == 'finish_reason' and isinstance(value, str) and value:
                entry[key] = value
        self._rounds.append(entry)
        if failure is not None:
            self.add(failure)

    @staticmethod
    def _percentiles(values: Sequence[float]) -> dict[str, Any]:
        """p50 / p90 / p99 / max over the whole population, never a sample.

        Nearest-rank on the sorted values, with `n` and `min`; `{}` when there
        are no values.
        """
        ordered = sorted(values)
        if not ordered:
            return {}

        def at(fraction: float) -> float:
            rank = max(1, math.ceil(fraction * len(ordered)))
            return ordered[min(rank, len(ordered)) - 1]

        return {
            'n': len(ordered),
            'min': ordered[0],
            'p50': at(0.50),
            'p90': at(0.90),
            'p99': at(0.99),
            'max': ordered[-1],
        }

    def absorb_orchestrator_rounds(self, rounds: Sequence[Mapping[str, Any]]) -> int:
        """Take the orchestrator's own per-round records and measure from them.

        The orchestrator's per-model-round records replace the per-call
        rounds, and `usage_stats` then reports `source: orchestrator_rounds`.
        Each record keeps `agent`, `outcome`, `batch_id`, numeric
        `ORCHESTRATOR_ROUND_KEYS` values, a non-empty `finish_reason` and a
        boolean `measured`. Returns how many were absorbed; with none, the
        rounds are left unchanged and 0 is returned.
        """
        taken = [entry for entry in rounds if isinstance(entry, Mapping)]
        if not taken:
            return 0
        absorbed: list[dict[str, Any]] = []
        for entry in taken:
            record: dict[str, Any] = {
                'agent': str(entry.get('agent') or ''),
                'outcome': str(entry.get('outcome') or ''),
                'batch_id': str(entry.get('batch_id') or ''),
            }
            for key in ORCHESTRATOR_ROUND_KEYS:
                value = entry.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    record[key] = value
                elif key == 'finish_reason' and isinstance(value, str) and value:
                    record[key] = value
            if isinstance(entry.get('measured'), bool):
                record['measured'] = entry['measured']
            absorbed.append(record)
        self._rounds = absorbed
        self._round_source = 'orchestrator_rounds'
        return len(self._rounds)

    def usage_stats(self) -> dict[str, Any]:
        """What a round costs, split by outcome, agent and batch.

        Every round is included; nothing is sampled. Each block gives
        `rounds`, `measured`, `unmeasured`, `prompt_tokens` and
        `completion_tokens` percentiles, and `finish_reasons`. `source` names
        the population, `specialist_calls` or `orchestrator_rounds`. Returns
        `{}` when no round was observed.
        """
        if not self._rounds:
            return {}

        def was_measured(round_record: Mapping[str, Any]) -> bool:
            """The recorder's own verdict when it gave one, else the numbers.

            A boolean `measured` flag wins; otherwise a round is measured when
            it carries `completion_tokens` or `prompt_tokens`.
            """
            flag = round_record.get('measured')
            if isinstance(flag, bool):
                return flag
            return 'completion_tokens' in round_record or 'prompt_tokens' in round_record

        def summarise(rounds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
            measured = [r for r in rounds if was_measured(r)]
            block: dict[str, Any] = {
                'rounds': len(rounds),
                'measured': len(measured),
                'unmeasured': len(rounds) - len(measured),
            }
            for key in ('prompt_tokens', 'completion_tokens'):
                values = [r[key] for r in rounds if isinstance(r.get(key), (int, float))]
                if values:
                    block[key] = self._percentiles(values)
            reasons = sorted({
                str(r['finish_reason']) for r in rounds if r.get('finish_reason')
            })
            if reasons:
                block['finish_reasons'] = reasons
            return block

        by_outcome: dict[str, Any] = {}
        for outcome in sorted({r['outcome'] for r in self._rounds}):
            by_outcome[outcome] = summarise(
                [r for r in self._rounds if r['outcome'] == outcome]
            )
        return {
            'rounds': len(self._rounds),
            'source': self._round_source,
            'by_outcome': by_outcome,
            'by_agent': {
                agent: summarise([r for r in self._rounds if r['agent'] == agent])
                for agent in sorted({r['agent'] for r in self._rounds})
            },
            'by_batch': {
                batch: summarise([r for r in self._rounds if r['batch_id'] == batch])
                for batch in sorted({r['batch_id'] for r in self._rounds})
            },
        }

    def rounds(self) -> list[dict[str, Any]]:
        """The per-round records themselves, uncapped."""
        return [dict(entry) for entry in self._rounds]

    def failures_for(self, batch_id: str, chunk_index: int) -> list[dict[str, str]]:
        """Every failure recorded for this batch and chunk, as agent/code pairs.

        Read from the uncapped index, so the answer does not change when a
        long run truncates the kept list. Distinct pairs, sorted by agent and
        then code.
        """
        seen: list[dict[str, str]] = []
        for entry in self._by_chunk.get((str(batch_id), int(chunk_index)), ()):
            if entry not in seen:
                seen.append(entry)
        return sorted(seen, key=lambda item: (item['agent'], item['code']))

    def stats(self) -> dict[str, Any]:
        """The counts a reader needs, and what the cap did to the list.

        `issued` is every failed round and `recorded` is how many are kept;
        `dropped`, `truncated` and `cap` describe the bound. `by_code`,
        `by_agent`, `reasoning_only` and `unattributed` (failures with no usage
        block) are over the issued population. Returns `{}` when nothing was
        issued.
        """
        if not self._issued:
            return {}
        return {
            'issued': self._issued,
            'recorded': len(self.records),
            'dropped': self.dropped,
            'truncated': self.dropped > 0,
            'cap': self.cap,
            'by_code': dict(sorted(self._by_code.items())),
            'by_agent': dict(sorted(self._by_agent.items())),
            'reasoning_only': self._reasoning_only,
            'unattributed': self._unattributed,
        }


def specialist_failure_sentence(signals: Sequence[Mapping[str, Any]]) -> str:
    """What to tell a reader whose batch died in the specialist, not the owner."""
    last = signals[-1]
    agent = last.get('agent') or 'specialist'
    code = last.get('code') or 'unknown'
    attempts = len(signals)
    plural = 'attempt' if attempts == 1 else 'attempts'
    detail = str(last.get('detail') or '').strip()
    sentence = (
        f'The {agent} specialist reported {code} on {attempts} consecutive '
        f'{plural} and returned no evidence. The owner contract was never '
        'reached and the owner prompt is not where this failed.'
    )
    return f'{sentence} Specialist detail: {detail}' if detail else sentence


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


LICENCE_AREA_ENTITY_SOURCE = 'object_scope.licence_id'

LICENCE_AREA_ENTITY_NOTE_RU = (
    'Лицензионная площадь этого запуска. Идентичность взята из привязки '
    'области: это тот же номер лицензии, по которому построен контур объекта.'
)


def entity_inventory(object_scope: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The entities this run has already resolved, with where each came from.

    One `licence_area` entry when `object_scope` has a `licence_id`, named by
    its `object_name` or else the id, with `derived_from` and a note; `[]`
    otherwise.
    """
    scope = object_scope or {}
    if not isinstance(scope, Mapping):
        return []
    licence_id = str(scope.get('licence_id') or '').strip()
    if not licence_id:
        return []
    return [
        {
            'entity_scope': 'licence_area',
            'entity_id': licence_id,
            'entity_name': str(scope.get('object_name') or '').strip() or licence_id,
            'derived_from': LICENCE_AREA_ENTITY_SOURCE,
            'note': LICENCE_AREA_ENTITY_NOTE_RU,
        }
    ]


def _batch_needs_an_entity(next_batch: Mapping[str, Any]) -> bool:
    """Whether any field in this chunk is required to name an entity scope.

    Read from `semantic_hint(field)['required_entity_scope']`.
    """
    return any(
        semantic_hint(field).get('required_entity_scope')
        for field in next_batch.get('fields') or []
    )


def compact_batch_context(
    next_batch: Mapping[str, Any],
    *,
    owner_agent: str,
    object_name: str,
    run_id: str,
    datacube: Mapping[str, Any] | None,
    contributor_evidence: Sequence[Mapping[str, Any]],
    object_scope: Mapping[str, Any] | None = None,
    knowledge_search_plan: Mapping[str, Any] | None = None,
    rag_v2_enabled: bool = False,
    rag_v2_collections: Sequence[str] = (),
    rag_v2_index_version: str | None = None,
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded context an owner needs; omit unrelated run state.

    Retrieval plans are built only when RAG v2 is enabled, a knowledge search
    plan is given, and `owner_agent`, the owner `AgentTask`'s agent, is `kb`.
    `entity_inventory` is present only when a field of the chunk needs an
    entity scope, and is empty rather than absent when the scope resolved
    nothing.
    """
    retrieval_plans = (
        build_retrieval_plans(
            next_batch,
            knowledge_search_plan,
            run_id=run_id,
            object_name=object_name,
            index_version=rag_v2_index_version,
            collections=rag_v2_collections,
        )
        if rag_v2_enabled and knowledge_search_plan and owner_agent == 'kb'
        else ()
    )
    entity_scoped = _batch_needs_an_entity(next_batch)
    return {
        'object_name': object_name,
        'run_id': run_id,
        'batch': dict(next_batch),
        **(
            {'entity_inventory': entity_inventory(object_scope)}
            if entity_scoped
            else {}
        ),
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


_DOMAIN_TO_SOURCE_TYPE = {
    'gis': 'gis',
    'web': 'web',
    'kb': 'knowledge_base',
    'knowledge_base': 'knowledge_base',
    'vision': 'vision',
}


_VALUELESS_STATUSES = frozenset({'not_found', 'not_applicable', 'conflicted'})


_RULE_EXCLUSION = re.compile(r"""rule\s+['"`]([a-z_]{4,})['"`]""", re.I)


def classify_rule_excluded_patches(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A value a rule refused is not a value nobody found.

    A `not_found` patch whose note says a value was excluded by
    `rule '<name>'` moves to `requires_expert_review` when the row declares
    that rule in `semantic_hint(field)['rules']`. Its note becomes
    `POLICY_EXCLUSION_NOTE_RU`, and `source_locator.if_not_why_not` names the
    rule and keeps the specialist's note, bounded to 600 characters. Returns
    the envelope and a run note per moved cell.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    notes: list[str] = []
    field_by_key = {
        str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []
    }
    for index, patch in enumerate(repaired['patches']):
        if patch.get('status') != 'not_found':
            continue
        note = str(patch.get('retrieval_note') or '')
        match = _RULE_EXCLUSION.search(note)
        if match is None:
            continue
        rule = match.group(1)
        field = field_by_key.get(str(patch.get('field_key') or ''))
        if field is None or rule not in set(semantic_hint(field).get('rules') or ()):
            continue

        field_key = str(patch.get('field_key') or f'patches[{index}]')
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': rule,
            'stated_reason': POLICY_EXCLUSION_NOTE_RU,
            'specialist_note': bounded_text(note, max_chars=600),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
        patch['retrieval_note'] = POLICY_EXCLUSION_NOTE_RU
        patch['status'] = 'requires_expert_review'
        notes.append(
            cells_note(
                '{count} ячеек: значение отклонено правилом {rule!r}, а не '
                'отсутствует — статус изменён с not_found на '
                'requires_expert_review ({keys}).',
                [field_key],
                rule=rule,
            )
        )
    return repaired, notes


POLICY_EXCLUSION_NOTE_RU = (
    'Значение найдено и отклонено правилом этой строки: строка объявляет '
    'такой случай недопустимым. Найденное значение и точная формулировка '
    'специалиста сохранены в записи о происхождении значения.'
)


LONE_SOURCE_REFUSED_FOR_RESOURCES = frozenset({'web'})


LONE_WEB_RESOURCE_RULE = 'resource_estimate_needs_more_than_a_press_number'

LONE_WEB_RESOURCE_REASON_RU = (
    'Оценка ресурсов не принята: единственный источник — публикация в СМИ или '
    'на сайте компании, без категории запасов, даты оценки, автора и метода '
    'подсчёта. Значение сохранено и ждёт подтверждения по отчётному источнику.'
)


def refuse_lone_web_resource_values(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A resource estimate whose only source is a press article is not one.

    A `filled` resource-row patch whose refs all resolve to sources of a type
    in `LONE_SOURCE_REFUSED_FOR_RESOURCES` moves to `requires_expert_review`
    with value, unit and value origin cleared. The refused value is kept in
    `source_locator.candidates`, and `if_not_why_not` names
    `LONE_WEB_RESOURCE_RULE` with the patch's note, or else
    `LONE_WEB_RESOURCE_REASON_RU`, as `stated_reason`. Returns the envelope
    and a run note.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope), []
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    source_types = {
        str(source.get('source_id') or ''): str(source.get('source_type') or '')
        for source in envelope.get('source_inventory') or []
        if isinstance(source, Mapping)
    }
    refused: list[str] = []
    for patch in repaired['patches']:
        field_key = str(patch.get('field_key') or '')
        if patch.get('status') != 'filled' or _resource_row(field_key) is None:
            continue
        refs = [str(ref) for ref in patch.get('source_refs') or []]
        types = {source_types.get(ref, '') for ref in refs}
        if not refs or not types <= LONE_SOURCE_REFUSED_FOR_RESOURCES:
            continue

        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': LONE_WEB_RESOURCE_RULE,
            'stated_reason': bounded_text(
                str(patch.get('retrieval_note') or '').strip()
                or LONE_WEB_RESOURCE_REASON_RU,
                max_chars=600,
            ),
            'decided_by': 'policy',
        }
        locator['candidates'] = [
            *(locator.get('candidates') or []),
            {
                'value': patch.get('value'),
                'unit': patch.get('unit'),
                'value_origin': patch.get('value_origin'),
                'source_ref': next(iter(refs), ''),
                'locator': _locator_without_bookkeeping(patch.get('source_locator')),
            },
        ]
        locator['selection_trace'] = (
            'Отклонено правилом источников: ресурсная оценка не принимается по '
            'единственному WEB-источнику — у публикации нет категории запасов, '
            'даты оценки, автора и метода подсчёта. Значение сохранено в '
            'source_locator.candidates для решения эксперта.'
        )
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        refused.append(field_key)
    if not refused:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ресурсных ячеек: значение по единственному WEB-источнику '
            'отклонено правилом {rule!r} и передано эксперту ({keys}).',
            refused,
            rule=LONE_WEB_RESOURCE_RULE,
        )
    ]


ABSENT_SPATIAL_LAYER_RULE = 'spatial_question_needs_a_spatial_answer'

ABSENT_SPATIAL_LAYER_REASON_RU = (
    'Строка требует пространственного измерения, а в GIS-проекте нет слоя, по '
    'которому его можно выполнить. Заявленное значение сохранено и ждёт '
    'проверки эксперта.'
)

ABSENCE_TRACE_RU = {
    'layer_not_found': (
        'Пространственный вопрос без пространственного ответа: в GIS-проекте '
        'нет слоя «{labels}», поэтому расстояние не измерено. Значение из '
        'документа или WEB сохранено в source_locator.candidates и не '
        'принято как измерение.'
    ),
    'layer_lacks_required_attribute': (
        'Слой «{labels}» в GIS-проекте есть, и объекты в нём есть, но в нём '
        'нет колонок, из которых строится значение этой строки. Строка '
        'спрашивает атрибут, которого в данных нет: это дефект данных, а не '
        'отсутствие работ на объекте. Значение из документа или WEB сохранено '
        'в source_locator.candidates и не принято как измерение.'
    ),
    'only_the_source_feature_in_layer': (
        'Слой «{labels}» в GIS-проекте есть, и единственный объект в нём — сам '
        'объект отчёта. Других объектов этой роли в проекте нет: это истинное '
        'отсутствие, а не дефект данных и не отсутствие слоя. Значение из '
        'документа или WEB сохранено в source_locator.candidates и не принято '
        'как измерение.'
    ),
}

UNNAMED_ABSENCE_NOTE_RU = (
    '{count} ячеек: строку закрывает {code}; значение отклонено правилом '
    '{rule!r} и передано эксперту ({keys}).'
)

ABSENCE_TRACE_TAIL_RU = (
    ' Значение из документа или WEB сохранено в source_locator.candidates и '
    'не принято как измерение.'
)

ABSENCE_NOTE_RU = {
    'layer_not_found': (
        '{count} инфраструктурных ячеек: в проекте нет слоя для измерения, '
        'значение из документа отклонено правилом {rule!r} и передано эксперту '
        '({keys}).'
    ),
    'layer_lacks_required_attribute': (
        '{count} ячеек: слой в проекте есть, объекты в нём есть, но нет '
        'колонок, из которых строится значение строки; значение отклонено '
        'правилом {rule!r} и передано эксперту ({keys}).'
    ),
    'only_the_source_feature_in_layer': (
        '{count} ячеек: слой в проекте есть, и единственный объект в нём — сам '
        'объект отчёта, других объектов этой роли в проекте нет; значение '
        'отклонено правилом {rule!r} и передано эксперту ({keys}).'
    ),
}


def refuse_prose_in_numeric_rows(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A row that asks for a quantity may not be answered with a sentence.

    A `filled` patch in a row that `expects_a_number`, whose value
    `states_no_quantity`, moves to `requires_expert_review` and keeps its
    value. Its note becomes `NON_NUMERIC_IN_NUMERIC_ROW_RU`, and
    `if_not_why_not` records the same sentence and the refused text, bounded
    to 600 characters. Returns the envelope and a run note per cell.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    notes: list[str] = []
    field_by_key = {
        str(field.get('field_key') or ''): field for field in next_batch.get('fields') or []
    }
    for index, patch in enumerate(repaired['patches']):
        if patch.get('status') != 'filled':
            continue
        field = field_by_key.get(str(patch.get('field_key') or ''))
        if field is None or not expects_a_number(field):
            continue
        value = patch.get('value')
        if not states_no_quantity(value):
            continue

        field_key = str(patch.get('field_key') or f'patches[{index}]')
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'non_numeric_value_in_numeric_row',
            'attribute': str(field.get('attribute_name') or ''),
            'stated_reason': NON_NUMERIC_IN_NUMERIC_ROW_RU,
            'refused_text': bounded_text(str(value), max_chars=600),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
        patch['retrieval_note'] = NON_NUMERIC_IN_NUMERIC_ROW_RU
        patch['status'] = EXPERT_REVIEW_STATUS
        notes.append(
            cells_note(
                '{count} ячеек: строка ожидает число, а получила текст — '
                'статус изменён с filled на requires_expert_review, '
                'значение сохранено для эксперта ({keys}).',
                [field_key],
            )
        )
    return repaired, notes


NON_NUMERIC_IN_NUMERIC_ROW_RU = (
    'Строка ожидает число, а источник дал текст. Значение сохранено и ждёт '
    'решения эксперта: его нужно либо выразить числом, либо признать '
    'неприменимым к этой строке.'
)


WRONG_KIND_RULES = {
    'element_for_mineral': 'element_and_mineral_are_not_interchangeable',
    'mineral_for_element': 'element_and_mineral_are_not_interchangeable',
    'work_year_for_age': 'an_absolute_age_is_not_a_calendar_year',
    'metal_mass_for_ore': 'metal_mass_is_not_the_tonnage_of_ore',
}

WRONG_KIND_REASON_RU = {
    'element_for_mineral': (
        'Строка спрашивает минерал, а значение называет химический элемент. '
        'Подмена запрещена (решение предметного эксперта от 2026-08-30).'
    ),
    'mineral_for_element': (
        'Строка спрашивает элемент или полезное ископаемое, а значение '
        'называет минерал. Подмена запрещена (решение предметного эксперта '
        'от 2026-08-30).'
    ),
    'work_year_for_age': (
        'Строка спрашивает абсолютный возраст пород — это миллионы и '
        'миллиарды лет, и он определяется специальными исследованиями. '
        'Значение — календарный год работ, а не возраст '
        '(решение предметного эксперта от 2026-08-30).'
    ),
    'metal_mass_for_ore': (
        'Строка спрашивает тоннаж руды, а значение — масса металла. '
        'Подмена запрещена (решение предметного эксперта от 2026-08-30). '
        'Обе величины сохранены: там, где источник даёт тоннаж руды, '
        'содержание и металл, это одна оценка, отвечающая трём строкам.'
    ),
}


def _wrong_kind_for_the_row(
    field: Mapping[str, Any], patch: Mapping[str, Any]
) -> str | None:
    """Which substitution this cell is making, as a `WRONG_KIND_RULES` key, or None.

    The rule fires only on positive identification, so an unrecognised value
    returns None. An element in a mineral row, or a mineral in an element
    row, counts only when the value names nothing of the other kind.
    """
    field_key = str(field.get('field_key') or '')
    value = patch.get('value')

    element, mineral = names_an_element(value), names_a_mineral(value)
    if field_key in MINERAL_FIELD_KEYS and element and not mineral:
        return 'element_for_mineral'
    if field_key in ELEMENT_FIELD_KEYS and mineral and not element:
        return 'mineral_for_element'
    if field_key in ABSOLUTE_AGE_FIELD_KEYS and is_a_work_year(value):
        return 'work_year_for_age'
    attribute = str(field.get('attribute_name') or '').casefold().strip()
    if attribute in ORE_TONNAGE_ATTRIBUTES and states_metal_mass(
        value, patch.get('retrieval_note')
    ):
        return 'metal_mass_for_ore'
    return None


def refuse_the_wrong_kind_of_answer(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A row's declared kind is binding.

    A `filled` patch that `_wrong_kind_for_the_row` identifies moves to
    `requires_expert_review` with value, unit and value origin cleared; the
    refused value is kept in `source_locator.candidates` and `if_not_why_not`
    names the rule from `WRONG_KIND_RULES`. Returns the envelope and a run
    note per kind.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    notes: list[str] = []
    field_by_key = {
        str(field.get('field_key') or ''): field
        for field in next_batch.get('fields') or []
    }
    refused: dict[str, list[str]] = {}
    for patch in repaired['patches']:
        if patch.get('status') != 'filled':
            continue
        field = field_by_key.get(str(patch.get('field_key') or ''))
        if field is None:
            continue
        kind = _wrong_kind_for_the_row(field, patch)
        if kind is None:
            continue

        field_key = str(patch.get('field_key') or '')
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': WRONG_KIND_RULES[kind],
            'stated_reason': WRONG_KIND_REASON_RU[kind],
            'decided_by': 'policy',
        }
        locator['candidates'] = [
            *(locator.get('candidates') or []),
            {
                'value': patch.get('value'),
                'unit': patch.get('unit'),
                'value_origin': patch.get('value_origin'),
                'source_ref': next(
                    iter(str(ref) for ref in patch.get('source_refs') or []), ''
                ),
            },
        ]
        patch['source_locator'] = locator
        patch['status'] = EXPERT_REVIEW_STATUS
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        refused.setdefault(kind, []).append(field_key)

    for kind, keys in sorted(refused.items()):
        notes.append(
            cells_note(
                '{count} ячеек: '
                + WRONG_KIND_REASON_RU[kind].replace('{', '{{').replace('}', '}}')
                + ' Значение передано эксперту ({keys}).',
                keys,
            )
        )
    return repaired, notes


UNIT_CONTRADICTS_SOURCE_RULE = 'unit_contradicts_its_source'
UNIT_CONTRADICTS_SOURCE_RU = (
    'Единица значения не совпадает с единицей, названной источником, и пересчёт '
    'не заявлен. Источник: {source}; в ячейке: {stated}. Обе величины сохранены.'
)

READING_IS_NOT_A_COMPUTATION_NOTE_RU = (
    'Происхождение исправлено на «direct»: значение прочитано из сводки слоя, '
    'а не вычислено — на локаторе нет ни операции, ни CRS расчёта.'
)


def a_reading_is_not_a_computation(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """`calculated` must not be claimable by copying a number off a layer.

    A `filled` `calculated` patch whose mapping locator cites a GIS layer
    (`layer_id` or `source_layer_id`), has no `operation`, `calculation_crs`
    or `confirmed_by_calculation`, and states a unit for its figure
    (`unit_named_in_locator`) is relabelled `direct`, and
    `READING_IS_NOT_A_COMPUTATION_NOTE_RU` is appended to its note. The value
    is not changed. Returns the envelope and a run note.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    relabelled: list[str] = []
    for patch in repaired['patches']:
        if patch.get('status') != 'filled':
            continue
        if str(patch.get('value_origin') or '') != 'calculated':
            continue
        locator = patch.get('source_locator')
        if not isinstance(locator, Mapping):
            continue
        if locator.get('operation') or locator.get('calculation_crs'):
            continue
        if locator.get('confirmed_by_calculation'):
            continue
        if not (locator.get('layer_id') or locator.get('source_layer_id')):
            continue
        if not unit_named_in_locator(locator):
            continue
        patch['value_origin'] = 'direct'
        patch['retrieval_note'] = ' '.join(
            part
            for part in (
                str(patch.get('retrieval_note') or '').strip(),
                READING_IS_NOT_A_COMPUTATION_NOTE_RU,
            )
            if part
        )
        relabelled.append(str(patch.get('field_key') or ''))
    notes = (
        [
            cells_note(
                '{count} ячеек: '
                + READING_IS_NOT_A_COMPUTATION_NOTE_RU.replace('{', '{{').replace('}', '}}')
                + ' ({keys}).',
                relabelled,
            )
        ]
        if relabelled
        else []
    )
    return repaired, notes


def refuse_a_unit_the_source_contradicts(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A value may not wear a unit its own source disagrees with.

    A `filled` patch whose canonical unit and the unit its locator names are
    both known and differ, and which `states_a_conversion` does not excuse,
    moves to `requires_expert_review` with value, unit and value origin
    cleared. The refused value is kept in `source_locator.candidates` and
    `if_not_why_not` names `UNIT_CONTRADICTS_SOURCE_RULE`. A locator naming no
    unit, or an unknown unit spelling, never refuses. Returns the envelope
    and a run note.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    refused: list[str] = []
    for patch in repaired['patches']:
        if patch.get('status') != 'filled':
            continue
        stated = canonical_unit(patch.get('unit'))
        if not stated:
            continue
        source = unit_named_in_locator(patch.get('source_locator'))
        if not source or source == stated:
            continue
        if states_a_conversion(patch):
            continue

        field_key = str(patch.get('field_key') or '')
        reason = UNIT_CONTRADICTS_SOURCE_RU.format(
            source=source, stated=str(patch.get('unit') or '')
        )
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': UNIT_CONTRADICTS_SOURCE_RULE,
            'stated_reason': reason,
            'decided_by': 'policy',
        }
        locator['candidates'] = [
            *(locator.get('candidates') or []),
            {
                'value': patch.get('value'),
                'unit': patch.get('unit'),
                'value_origin': patch.get('value_origin'),
                'source_ref': next(
                    iter(str(ref) for ref in patch.get('source_refs') or []), ''
                ),
            },
        ]
        patch['source_locator'] = locator
        patch['status'] = EXPERT_REVIEW_STATUS
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        refused.append(field_key)

    notes = (
        [
            cells_note(
                '{count} ячеек: единица значения противоречит единице источника, '
                'пересчёт не заявлен; значение передано эксперту ({keys}).',
                refused,
            )
        ]
        if refused
        else []
    )
    return repaired, notes


def refuse_unanswerable_spatial_rows(
    envelope: Mapping[str, Any],
    unanswerable: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """A distance the project has no layer to measure is a gap, not a citation.

    `unanswerable` holds items with `field_key`, `code`, `role_labels` and
    `code_meaning_ru`. A matching `not_found` patch keeps its status and gets
    `absence_code` and the item's `code_meaning_ru` appended to its note; it
    is skipped when that meaning is empty. A matching `filled` patch moves to
    `requires_expert_review` with value, unit and value origin cleared, its
    value kept in `source_locator.candidates`, `if_not_why_not` naming
    `ABSENT_SPATIAL_LAYER_RULE`, `absence_code`, and a `selection_trace` from
    `ABSENCE_TRACE_RU`. A code with no entry there is described from its
    `code_meaning_ru` followed by `ABSENCE_TRACE_TAIL_RU`, or with the
    `layer_not_found` sentence when that meaning is empty. Returns the
    envelope and run notes per code.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list) or not unanswerable:
        return dict(envelope), []
    by_key = {
        str(item.get('field_key') or ''): item
        for item in unanswerable
        if isinstance(item, Mapping)
    }
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    refused: dict[str, list[str]] = {}
    stamped: dict[str, list[str]] = {}
    for patch in repaired['patches']:
        field_key = str(patch.get('field_key') or '')
        item = by_key.get(field_key)
        status = str(patch.get('status') or '')
        if item is None or status not in {'filled', 'not_found'}:
            continue
        labels = ', '.join(str(label) for label in item.get('role_labels') or []) or str(
            item.get('code') or ''
        )
        if status == 'not_found':
            meaning = str(item.get('code_meaning_ru') or '').strip()
            if not meaning:
                continue
            locator = locator_map(patch.get('source_locator'))
            locator['absence_code'] = str(item.get('code') or 'layer_not_found')
            patch['source_locator'] = locator
            note = str(patch.get('retrieval_note') or '').strip()
            patch['retrieval_note'] = f'{note} Роли: {labels}. {meaning}'.strip()
            stamped.setdefault(str(item.get('code') or 'layer_not_found'), []).append(field_key)
            continue
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': ABSENT_SPATIAL_LAYER_RULE,
            'stated_reason': bounded_text(
                str(patch.get('retrieval_note') or '').strip()
                or ABSENT_SPATIAL_LAYER_REASON_RU,
                max_chars=600,
            ),
            'decided_by': 'policy',
        }
        locator['candidates'] = [
            *(locator.get('candidates') or []),
            {
                'value': patch.get('value'),
                'unit': patch.get('unit'),
                'value_origin': patch.get('value_origin'),
                'source_ref': next(iter(str(ref) for ref in patch.get('source_refs') or []), ''),
                'locator': _locator_without_bookkeeping(patch.get('source_locator')),
            },
        ]
        code = str(item.get('code') or 'layer_not_found')
        template = ABSENCE_TRACE_RU.get(code)
        if template is None:
            meaning = str(item.get('code_meaning_ru') or '').strip()
            template = (
                f'Слой «{{labels}}»: {meaning}{ABSENCE_TRACE_TAIL_RU}'
                if meaning
                else ABSENCE_TRACE_RU['layer_not_found']
            )
        locator['selection_trace'] = template.format(labels=labels)
        locator['absence_code'] = code
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        refused.setdefault(code, []).append(field_key)
    stamped_notes = [
        cells_note(
            '{count} пустых ячеек: причина постоянная — {code}; проставлена на '
            'ячейке ({keys}).',
            keys,
            code=code,
        )
        for code, keys in sorted(stamped.items())
    ]
    if not refused:
        return repaired, stamped_notes
    return repaired, [
        *stamped_notes,
        *(
            cells_note(
                ABSENCE_NOTE_RU.get(code, UNNAMED_ABSENCE_NOTE_RU),
                keys,
                code=code,
                rule=ABSENT_SPATIAL_LAYER_RULE,
            )
            for code, keys in sorted(refused.items())
        ),
    ]


OUT_OF_RADIUS_RULE = 'an_object_outside_the_radius_does_not_answer_the_row'

OUT_OF_RADIUS_REASON_RU = (
    'Значение отклонено: объект находится в {stated_km:g} км, а строка '
    'спрашивает объекты в радиусе {limit_km:g} км.'
)

RADIUS_ROW_LIMITS_KM = {'r084': 50.0, 'r085': 100.0}

_DISTANCE_IN_VALUE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(?:[-–—]\s*(\d+(?:[.,]\d+)?)\s*)?(км|km)\b',
    re.IGNORECASE,
)


def _radius_row(field_key: str) -> str | None:
    parts = str(field_key).split('.')
    row = parts[2] if len(parts) > 2 else ''
    return row if row in RADIUS_ROW_LIMITS_KM else None


def _distances_km(text: Any) -> list[float]:
    """Every distance a piece of text states, each range read at its near end."""
    if not isinstance(text, str):
        return []
    return [
        min(
            float(match.group(1).replace(',', '.')),
            float((match.group(2) or match.group(1)).replace(',', '.')),
        )
        for match in _DISTANCE_IN_VALUE.finditer(text)
    ]


def stated_distance_km(value: Any) -> float | None:
    """The nearest distance a value states about itself, in kilometres."""
    stated = _distances_km(value)
    return min(stated) if stated else None


def _measured_distances_km(locator: Any) -> set[float]:
    """Every distance the cell's own recorded measurements state.

    Read from the values in `source_locator.spatial_divergence.measured`;
    empty when there are none.
    """
    if not isinstance(locator, Mapping):
        return set()
    divergence = locator.get('spatial_divergence')
    if not isinstance(divergence, Mapping):
        return set()
    return {
        distance
        for entry in divergence.get('measured') or []
        if isinstance(entry, Mapping)
        for distance in _distances_km(entry.get('value'))
    }


def note_distance_km(
    note: Any,
    *,
    limit_km: float,
    measured_km: set[float] | None = None,
) -> float | None:
    """The nearest distance the note states about the object, if it states one.

    Distances equal to `limit_km`, and distances in `measured_km`, are
    ignored. Callers read the note only when the value states no distance.
    """
    measured = measured_km or set()
    stated = [
        distance
        for distance in _distances_km(note)
        if distance != limit_km and distance not in measured
    ]
    return min(stated) if stated else None


def _measurement_within(locator: Any, limit_km: float) -> Mapping[str, Any] | None:
    """A measurement this cell already recorded that does satisfy the radius."""
    if not isinstance(locator, Mapping):
        return None
    divergence = locator.get('spatial_divergence')
    if not isinstance(divergence, Mapping):
        return None
    for entry in divergence.get('measured') or []:
        if not isinstance(entry, Mapping):
            continue
        distance = stated_distance_km(entry.get('value'))
        if distance is not None and distance <= limit_km:
            return entry
    return None


def refuse_out_of_radius_infrastructure(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A value that says it is 130 km away cannot fill the 50 km row.

    Applies to `filled` patches in the rows of `RADIUS_ROW_LIMITS_KM`. The
    distance is read from the value, or from the note when the value states
    none. When it exceeds the row's radius, the refused value is kept in
    `source_locator.candidates` with the stated distance and the radius. A
    measurement in `spatial_divergence.measured` within the radius then fills
    the cell as `calculated`; without one the cell moves to
    `requires_expert_review` with value, unit and value origin cleared.
    Returns the envelope and run notes.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    promoted: list[str] = []
    deferred: list[str] = []
    for patch in repaired['patches']:
        if str(patch.get('status') or '') != 'filled':
            continue
        row = _radius_row(str(patch.get('field_key') or ''))
        if row is None:
            continue
        limit_km = RADIUS_ROW_LIMITS_KM[row]
        stated = stated_distance_km(patch.get('value'))
        stated_in = 'value'
        if stated is None:
            stated = note_distance_km(
                patch.get('retrieval_note'),
                limit_km=limit_km,
                measured_km=_measured_distances_km(locator_map(patch.get('source_locator'))),
            )
            stated_in = 'retrieval_note'
        if stated is None or stated <= limit_km:
            continue
        field_key = str(patch.get('field_key') or '')
        says = (
            f'Значение «{patch.get("value")}» указывает расстояние {stated:g} км'
            if stated_in == 'value'
            else (
                f'Значение «{patch.get("value")}» расстояния не называет, '
                f'а заметка помещает объект на {stated:g} км'
            )
        )
        locator = locator_map(patch.get('source_locator'))
        refused = {
            'value': patch.get('value'),
            'unit': patch.get('unit'),
            'value_origin': patch.get('value_origin'),
            'source_ref': next(iter(str(ref) for ref in patch.get('source_refs') or []), ''),
            'locator': {
                'rule': OUT_OF_RADIUS_RULE,
                'stated_reason': OUT_OF_RADIUS_REASON_RU.format(
                    stated_km=stated, limit_km=limit_km,
                ),
                'stated_distance_km': stated,
                'stated_distance_read_from': stated_in,
                'row_radius_km': limit_km,
                'decided_by': 'policy',
            },
        }
        locator['candidates'] = [*(locator.get('candidates') or []), refused]
        measurement = _measurement_within(locator, limit_km)
        if measurement is not None:
            locator['policy'] = 'out_of_radius_value_replaced_by_measurement'
            locator['selection_trace'] = (
                f'{says}, а строка спрашивает объекты в радиусе {limit_km:g} км. '
                'Значение отклонено и сохранено в source_locator.candidates; ячейка '
                'заполнена измерением GIS, которое в радиус укладывается.'
            )
            patch['source_locator'] = locator
            patch['value'] = measurement.get('value')
            patch['unit'] = measurement.get('unit')
            patch['value_origin'] = 'calculated'
            patch['source_refs'] = [
                ref
                for ref in dict.fromkeys(
                    [
                        str(measurement.get('source_ref') or ''),
                        *(str(ref) for ref in patch.get('source_refs') or []),
                    ]
                )
                if ref
            ]
            patch['retrieval_note'] = (
                f'Измерение GIS: {measurement.get("value")}. Значение из документа '
                f'«{refused["value"]}» ({stated:g} км) отклонено: строка спрашивает '
                f'объекты в радиусе {limit_km:g} км.'
            )
            promoted.append(field_key)
            continue
        locator['policy'] = 'out_of_radius_value_refused'
        locator['selection_trace'] = (
            f'{says}, а строка спрашивает объекты в радиусе {limit_km:g} км. '
            'Измерения для этой ячейки нет, поэтому значение отклонено правилом '
            f'{OUT_OF_RADIUS_RULE!r} и передано эксперту.'
        )
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        deferred.append(field_key)
    notes: list[Any] = []
    if promoted:
        notes.append(
            cells_note(
                '{count} ячеек: объект вне радиуса строки заменён измерением '
                'GIS, которое в радиус укладывается ({keys}).',
                promoted,
            )
        )
    if deferred:
        notes.append(
            cells_note(
                '{count} ячеек: объект вне радиуса строки, измерения нет — '
                'значение отклонено правилом {rule!r} и передано эксперту '
                '({keys}).',
                deferred,
                rule=OUT_OF_RADIUS_RULE,
            )
        )
    return repaired, notes


def spatial_divergence_notes(
    envelope: Mapping[str, Any],
) -> list[Any]:
    """Say how many cells hold a measurement they did not fill with.

    Counts the patches whose `source_locator` carries `spatial_divergence`,
    and changes nothing.
    """
    cells = sorted(
        str(patch.get('field_key') or '')
        for patch in envelope.get('patches') or []
        if isinstance(patch, Mapping)
        and isinstance(patch.get('source_locator'), Mapping)
        and patch['source_locator'].get('spatial_divergence')
    )
    if not cells:
        return []
    return [
        cells_note(
            '{count} ячеек: расчёт GIS не выбран, значение взято из другого '
            'источника; расчёт сохранён в source_locator.spatial_divergence '
            '({keys}).',
            cells,
        )
    ]


def _locator_without_bookkeeping(locator: Any) -> Any:
    """The locator without its `if_not_why_not`, `candidates`, `selection_trace`
    and `negative_findings` keys; a non-mapping is returned unchanged."""
    if not isinstance(locator, Mapping):
        return locator
    return {
        key: value
        for key, value in locator.items()
        if key not in ('if_not_why_not', 'candidates', 'selection_trace', 'negative_findings')
    }


def normalize_patch_source_locators(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """One shape per field, decided before the state is saved.

    Every `source_locator` that is neither None nor a mapping is replaced by
    `locator_map` of it. Returns the envelope and a run note listing the
    converted cells.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope), []
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    converted: list[str] = []
    for patch in repaired['patches']:
        locator = patch.get('source_locator')
        if locator is None or isinstance(locator, Mapping):
            continue
        patch['source_locator'] = locator_map(locator)
        converted.append(str(patch.get('field_key') or ''))
    if not converted:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек: source_locator приведён из строки к объекту ({keys}).',
            converted,
        )
    ]


def inject_row_declared_work_stage(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Fill in the one qualifier the row already declares, rather than demand it.

    A `filled` patch in a row with a `GRR_WORK_STAGE_BY_ROW` entry, whose
    locator has no `work_stage`, gets that stage. A `work_stage` the owner
    wrote is never changed, even when it contradicts the row. Returns the
    envelope and a run note.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope), []
    row_by_key = {
        str(field.get('field_key') or ''): int(field.get('row_id') or 0)
        for field in next_batch.get('fields') or []
    }
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    injected: list[str] = []
    for patch in repaired['patches']:
        if str(patch.get('status') or '') != 'filled':
            continue
        field_key = str(patch.get('field_key') or '')
        stage = GRR_WORK_STAGE_BY_ROW.get(row_by_key.get(field_key, 0))
        if not stage:
            continue
        locator = locator_map(patch.get('source_locator'))
        if str(locator.get('work_stage') or '').strip():
            continue
        locator['work_stage'] = stage
        patch['source_locator'] = locator
        injected.append(field_key)
    if not injected:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек плана ГРР: work_stage подставлен из строки шаблона, '
            'владелец его не указал ({keys}).',
            injected,
        )
    ]


ABSENCE_WRITTEN_AS_A_VALUE = (
    'не извлечено',
    'не извлечён',
    'не извлечена',
    'недоступно',
    'недоступна',
    'недоступен',
    'недоступны',
    'не доступно',
    'не предоставлено',
    'не указано',
    'не указан',
    'не указана',
    'нет данных',
    'данные отсутствуют',
    'not verified',
    'not extracted',
    'not available',
    'no data',
    'n/a',
)

ABSENCE_AS_VALUE_REASON_RU = (
    'Ячейка сообщила об отсутствии значения текстом в поле значения. Это '
    'статус, а не значение: строка закрыта как «не найдено», и в полноту '
    'она не засчитывается.'
)

_ABSENCE_TRIM = ' \t\r\n.,;:!·—–-«»"\'()[]'


def reads_as_an_absence(value: Any) -> bool:
    """Whether the whole value is one of those phrases and nothing more."""
    if isinstance(value, (Mapping, list, tuple, set)):
        return False
    text = str(value if value is not None else '').strip(_ABSENCE_TRIM).casefold()
    return bool(text) and text in ABSENCE_WRITTEN_AS_A_VALUE


def refuse_absence_written_as_a_value(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """«Не извлечено» is a status. A cell holding it is `not_found`.

    A `filled` patch whose whole value `reads_as_an_absence` moves to
    `not_found` with value, unit and value origin cleared, and
    `if_not_why_not` keeps the phrase as `refused_text`, bounded to 200
    characters. Returns the envelope and a run note.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope), []
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    closed: list[str] = []
    for patch in repaired['patches']:
        if str(patch.get('status') or '') != 'filled':
            continue
        if not reads_as_an_absence(patch.get('value')):
            continue
        field_key = str(patch.get('field_key') or '')
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'absence_reported_as_a_value',
            'stated_reason': ABSENCE_AS_VALUE_REASON_RU,
            'refused_text': bounded_text(str(patch.get('value')), max_chars=200),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
        patch['status'] = 'not_found'
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        closed.append(field_key)
    if not closed:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек сообщили об отсутствии значения текстом в поле '
            'значения — статус изменён с filled на not_found, в полноту они '
            'не идут ({keys}).',
            closed,
        )
    ]


WORK_STAGE_FIELD_KEYS = {
    'stage': 'geotizer_object.v1.r014.a01',
    'start': 'geotizer_object.v1.r014.a02',
    'end': 'geotizer_object.v1.r014.a03',
}

LICENCE_START_FIELD_KEY = 'geotizer_object.v1.r009.a01'

LICENCE_CATEGORY_FIELD_KEY = 'geotizer_object.v1.r011.a01'

LICENCE_PURPOSE_PREFIXES = ('для ', 'на ')

LICENCE_STATE_WORDS = frozenset({
    'действует',
    'действующая',
    'действующий',
    'приостановлена',
    'приостановлено',
    'приостановлен',
    'прекращена',
    'прекращено',
    'прекращён',
    'прекращен',
    'аннулирована',
    'аннулировано',
    'досрочно прекращена',
    'не действует',
})

LICENCE_RECORD_IN_WORK_STAGE_RULE = 'a_licence_record_is_not_a_work_stage'

LICENCE_RECORD_IN_WORK_STAGE_RU = {
    'category': (
        'Значение совпадает с категорией лицензии (строка 11) — с тем, на что '
        'лицензия выдана, а не с тем, на какой стадии работы. Значение '
        'сохранено для эксперта.'
    ),
    'purpose': (
        'Значение сформулировано как целевое назначение лицензии («для …»), а '
        'не как стадия работ. Назначение лицензии — строка 11. Значение '
        'сохранено для эксперта.'
    ),
    'stage': (
        'Строка спрашивает, на какой стадии находятся РАБОТЫ по объекту, а '
        'значение взято из лицензионной записи — это состояние лицензии или '
        'её целевое назначение, а не стадия работ. Значение сохранено для '
        'эксперта.'
    ),
    'start': (
        'Значение совпадает с датой начала действия лицензии (строка 9). '
        'Стадия работ — не срок лицензии; дата повторена из другой строки. '
        'Значение сохранено для эксперта.'
    ),
    'end': (
        'Значение совпадает с датой окончания действия лицензии (строка 10). '
        'Стадия работ — не срок лицензии; дата повторена из другой строки. '
        'Значение сохранено для эксперта.'
    ),
}


def _date_parts(value: Any) -> tuple[int, int, int] | None:
    """A date as (year, month, day), or None if it is not one.

    The value must hold exactly three numbers. A four-digit first number
    reads year, month, day; a four-digit last number reads day, month, year.
    Any other layout returns None.
    """
    parts = re.findall(r'\d+', str(value or ''))
    if len(parts) != 3:
        return None
    numbers = [int(part) for part in parts]
    if len(parts[0]) == 4 and len(parts[-1]) != 4:
        year, month, day = numbers
    elif len(parts[-1]) == 4 and len(parts[0]) != 4:
        day, month, year = numbers
    else:
        return None
    return (year, month, day)


def _plain(value: Any) -> str:
    """A value reduced to what two spellings of one answer share.

    Casefolded, punctuation replaced by spaces, whitespace collapsed; `''`
    for a mapping or collection.
    """
    if isinstance(value, (Mapping, list, tuple, set)):
        return ''
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(value or '')).casefold().split())


def _same_date(left: Any, right: Any) -> bool:
    """Whether two written dates are the same date."""
    one, two = _date_parts(left), _date_parts(right)
    return one is not None and one == two


def refuse_a_licence_record_in_the_work_stage_row(
    envelope: Mapping[str, Any],
    *,
    accepted_fields: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], list[str]]:
    """Row 14 asks what stage the work is at, and got the licence back.

    A `filled` r014 stage value that is a licence-state word, equals the
    licence category (r011), or opens with a purpose preposition is refused,
    and so is a start or end date equal to the licence term (r009, r010).
    The licence values are read from `filled` patches in this envelope first,
    then from `accepted_fields`. A refused cell moves to
    `requires_expert_review` with value, unit and value origin cleared and
    the value kept in `source_locator.candidates`. Returns the envelope and a
    run note per refused part.
    """
    patches = envelope.get('patches')
    if not isinstance(patches, list):
        return dict(envelope), []
    repaired = {**dict(envelope), 'patches': [dict(patch) for patch in patches]}
    known = [*repaired['patches'], *accepted_fields]

    def stated(field_key: str) -> Any:
        return next(
            (
                record.get('value')
                for record in known
                if str(record.get('field_key') or '') == field_key
                and str(record.get('status') or '') == 'filled'
            ),
            None,
        )

    licence_term = {
        'start': stated(LICENCE_START_FIELD_KEY),
        'end': stated(LICENCE_END_FIELD_KEY),
    }
    licence_category = _plain(stated(LICENCE_CATEGORY_FIELD_KEY))
    refused: dict[str, list[str]] = {}
    for patch in repaired['patches']:
        if str(patch.get('status') or '') != 'filled':
            continue
        field_key = str(patch.get('field_key') or '')
        value = patch.get('value')
        if field_key == WORK_STAGE_FIELD_KEYS['stage']:
            text = str(value or '').strip().casefold()
            plain = _plain(value)
            if text in LICENCE_STATE_WORDS:
                part = 'stage'
            elif plain and plain == licence_category:
                part = 'category'
            elif text.startswith(LICENCE_PURPOSE_PREFIXES):
                part = 'purpose'
            else:
                continue
        elif field_key == WORK_STAGE_FIELD_KEYS['start']:
            if not _same_date(value, licence_term['start']):
                continue
            part = 'start'
        elif field_key == WORK_STAGE_FIELD_KEYS['end']:
            if not _same_date(value, licence_term['end']):
                continue
            part = 'end'
        else:
            continue

        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': LICENCE_RECORD_IN_WORK_STAGE_RULE,
            'stated_reason': LICENCE_RECORD_IN_WORK_STAGE_RU[part],
            'decided_by': 'policy',
        }
        locator['candidates'] = [
            *(locator.get('candidates') or []),
            {
                'value': value,
                'unit': patch.get('unit'),
                'value_origin': patch.get('value_origin'),
                'source_ref': next(
                    iter(str(ref) for ref in patch.get('source_refs') or []), ''
                ),
            },
        ]
        patch['source_locator'] = locator
        patch['status'] = EXPERT_REVIEW_STATUS
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        refused.setdefault(part, []).append(field_key)

    return repaired, [
        cells_note(
            '{count} ячеек: '
            + LICENCE_RECORD_IN_WORK_STAGE_RU[part]
            .replace('{', '{{')
            .replace('}', '}}')
            + ' ({keys}).',
            keys,
        )
        for part, keys in sorted(refused.items())
    ]


UNRECORDED_CONFLICT_TRACE = (
    'Владелец объявил конфликт, но не записал конкурирующие значения. '
    'Стороны конфликта известны только по источникам: {refs}. '
    'Значения нужно смотреть в самих источниках.'
)


def record_unrecorded_conflicts(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Say so when a declared conflict carries no sides.

    A `conflicted` patch whose locator has no `candidates` gets
    `UNRECORDED_CONFLICT_TRACE` naming its source refs and policy
    `owner_declared_conflict_without_candidates`; the status is not changed.
    Returns the envelope and a run note.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    unrecorded: list[str] = []
    for index, patch in enumerate(repaired['patches']):
        if str(patch.get('status') or '') != 'conflicted':
            continue
        locator = patch.get('source_locator')
        candidates = locator.get('candidates') if isinstance(locator, Mapping) else None
        if candidates:
            continue
        field_key = str(patch.get('field_key') or f'patches[{index}]')
        refs = [str(ref) for ref in patch.get('source_refs') or [] if str(ref).strip()]
        locator = locator_map(locator)
        locator['selection_trace'] = UNRECORDED_CONFLICT_TRACE.format(
            refs=', '.join(refs) if refs else 'не указаны'
        )
        locator['policy'] = 'owner_declared_conflict_without_candidates'
        patch['source_locator'] = locator
        unrecorded.append(field_key)
    if not unrecorded:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} конфликтных ячеек: владелец не записал конкурирующие '
            'значения, на карте конфликт виден без сторон ({keys}).',
            unrecorded,
        )
    ]


ONE_SIDED_CONFLICT_TRACE = (
    'Владелец объявил конфликт, но значение назвала только одна сторона из '
    '{total}: {stated}. Отсутствие данных у второй стороны — не конкурирующее '
    'значение, поэтому разрешать нечего; ячейка передана эксперту, а все '
    'кандидаты сохранены.'
)


def refuse_one_sided_conflicts(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A candidate that states no value is not a side of a disagreement.

    A `conflicted` patch with candidates, fewer than two of which have a
    truthy, non-blank value, moves to `requires_expert_review` with value, unit and
    value origin cleared and every candidate kept, and gets
    `ONE_SIDED_CONFLICT_TRACE` and policy `conflict_without_two_stated_values`.
    Returns the envelope and a run note.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    one_sided: list[str] = []
    for index, patch in enumerate(repaired['patches']):
        if str(patch.get('status') or '') != 'conflicted':
            continue
        locator = patch.get('source_locator')
        candidates = locator.get('candidates') if isinstance(locator, Mapping) else None
        if not candidates or not isinstance(candidates, list):
            continue
        stated = [
            candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get('value') or '').strip()
        ]
        if len(stated) >= 2:
            continue
        field_key = str(patch.get('field_key') or f'patches[{index}]')
        locator = locator_map(locator)
        locator['selection_trace'] = ONE_SIDED_CONFLICT_TRACE.format(
            total=len(candidates),
            stated=', '.join(
                f'«{str(candidate.get("value")).strip()}»' for candidate in stated
            )
            or 'ни одна',
        )
        locator['policy'] = 'conflict_without_two_stated_values'
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        patch['value'] = None
        patch['unit'] = None
        patch['value_origin'] = None
        one_sided.append(field_key)
    if not one_sided:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек: объявлен конфликт, но значение назвала только одна '
            'сторона — разрешать нечего, ячейка передана эксперту ({keys}).',
            one_sided,
        )
    ]


_FIELD_KEY_ROW = re.compile(r'^geotizer_object\.v\d+\.r(\d{3})\.a\d{2}$')


def _patch_row_id(patch: Mapping[str, Any]) -> int | None:
    match = _FIELD_KEY_ROW.match(str(patch.get('field_key') or ''))
    return int(match.group(1)) if match else None


def retire_stale_projected_reasons(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A reason composed for one status must not outlive it.

    A patch whose `PROJECTED_REASON_STATUS_KEY` names a status other than its
    current one has its `retrieval_note` cleared and the key removed. This is
    not a validation failure. Returns the envelope and a run note.
    """
    patches = envelope.get('patches') or []
    if not patches:
        return dict(envelope), []
    retired: list[str] = []
    kept: list[dict[str, Any]] = []
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            kept.append(raw_patch)
            continue
        patch = dict(raw_patch)
        locator = patch.get('source_locator')
        semantic = locator if isinstance(locator, Mapping) else {}
        projected_for = str(semantic.get(PROJECTED_REASON_STATUS_KEY) or '')
        if not projected_for or projected_for == str(patch.get('status') or ''):
            kept.append(patch)
            continue
        patch['retrieval_note'] = ''
        stamped = locator_map(locator)
        stamped.pop(PROJECTED_REASON_STATUS_KEY, None)
        patch['source_locator'] = stamped
        retired.append(str(patch.get('field_key') or ''))
        kept.append(patch)
    if not retired:
        return dict(envelope), []
    return (
        {**envelope, 'patches': kept},
        [
            cells_note(
                '{count} ячеек несли причину, написанную для прежнего '
                'статуса; причина снята ({keys}).',
                retired,
            )
        ],
    )


INVALID_SCOPE_TRACE = (
    'Область поиска названа некорректно: «{scope}» не является коллекцией базы '
    'знаний, поэтому искать внутри неё нельзя. Пустой результат здесь означает, '
    'что поиск не состоялся, а не что документа нет. Ячейка передана эксперту; '
    'после исправления области поиска строку следует запросить заново.'
)


GIS_LOCATOR_KEYS = (
    'layer_id', 'project_id', 'proposal_source_id', 'evidence_authority',
    'absence_code',
)
GIS_PROSE_MARKERS = ('gis project', 'layer ', 'layer_id:', 'слой ', 'слое ')


def names_a_gis_source(locator: Any) -> bool:
    """Whether this locator reports a spatial source rather than a corpus.

    True when any nested key in `GIS_LOCATOR_KEYS` has a non-empty value, or
    any nested string contains a `GIS_PROSE_MARKERS` marker, case-folded.
    """
    def walk(node: Any) -> bool:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in GIS_LOCATOR_KEYS and value not in (None, '', [], {}):
                    return True
                if walk(value):
                    return True
            return False
        if isinstance(node, (list, tuple)):
            return any(walk(item) for item in node)
        if isinstance(node, str):
            lowered = node.casefold()
            return any(marker in lowered for marker in GIS_PROSE_MARKERS)
        return False

    return walk(locator)


def flag_invalid_scope_conclusions(
    envelope: Mapping[str, Any],
    *,
    non_corpus_names: Sequence[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    """`not_found` from a search that had nowhere to look is not `not_found`.

    A `not_found` patch whose serialised locator names one of
    `non_corpus_names`, and which does not `names_a_gis_source`, moves to
    `requires_expert_review` with `INVALID_SCOPE_REASON_RU` as its note,
    `INVALID_SCOPE_TRACE` as its `selection_trace`, policy `invalid_scope`,
    and `PROJECTED_REASON_STATUS_KEY` set to `requires_expert_review`.
    Returns the envelope and a run note.
    """
    names = [str(name).strip() for name in non_corpus_names if str(name or '').strip()]
    if not names:
        return {**dict(envelope), 'patches': [dict(p) for p in envelope.get('patches') or []]}, []
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    flagged: list[str] = []
    for patch in repaired['patches']:
        if str(patch.get('status') or '') != 'not_found':
            continue
        locator = patch.get('source_locator')
        rendered = json.dumps(locator, ensure_ascii=False) if locator else ''
        named = next((name for name in names if name in rendered), None)
        if named is None:
            continue
        if names_a_gis_source(locator):
            continue
        locator = locator_map(locator)
        locator['selection_trace'] = INVALID_SCOPE_TRACE.format(scope=named)
        locator['policy'] = 'invalid_scope'
        locator[PROJECTED_REASON_STATUS_KEY] = 'requires_expert_review'
        patch['retrieval_note'] = INVALID_SCOPE_REASON_RU
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        flagged.append(str(patch.get('field_key') or ''))
    if not flagged:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек закрыты как not_found после поиска в области, '
            'которая не является коллекцией базы знаний — поиск не состоялся, '
            'и ячейки переданы эксперту ({keys}).',
            flagged,
        )
    ]


PLAN_DEADLINE_FIELD_KEYS = (
    *(f'geotizer_object.v1.r{row:03d}.a05' for row in range(68, 73)),
    *(f'geotizer_object.v1.r{row:03d}.a02' for row in range(73, 77)),
)
LICENCE_END_FIELD_KEY = 'geotizer_object.v1.r010.a01'

_YEAR = re.compile(r'(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)')

PLAN_BEYOND_LICENCE_TRACE = (
    'Аудит противоречий: срок работ ({plan}) выходит за пределы лицензии, '
    'которая заканчивается {licence} (строка 10, из слоя лицензии). '
    'Работы, запланированные после окончания лицензии, требуют либо продления, '
    'либо исправления срока. Значение сохранено: это противоречие, а не ошибка '
    'извлечения.'
)


def _latest_year(value: Any) -> int | None:
    years = [int(match) for match in _YEAR.findall(str(value or ''))]
    return max(years) if years else None


def flag_plan_beyond_licence_term(
    envelope: Mapping[str, Any],
    *,
    licence_end: Any = None,
    accepted_fields: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], list[str]]:
    """A planned deadline after the licence expires is a contradiction.

    The licence end is `licence_end`, else a `filled` r010 value in this
    envelope, else one in `accepted_fields`. A `filled` cell of
    `PLAN_DEADLINE_FIELD_KEYS` whose latest year is after the licence end's
    latest year gets `PLAN_BEYOND_LICENCE_TRACE` and policy
    `plan_deadline_beyond_licence_term`; its status and value are kept.
    Returns the envelope and a run note, and nothing when no licence year is
    known.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    patches = repaired['patches']
    stated_end = licence_end
    if stated_end is None:
        stated_end = next(
            (
                record.get('value')
                for record in (*patches, *accepted_fields)
                if str(record.get('field_key') or '') == LICENCE_END_FIELD_KEY
                and str(record.get('status') or '') == 'filled'
            ),
            None,
        )
    licence_year = _latest_year(stated_end)
    if licence_year is None:
        return repaired, []
    beyond: list[str] = []
    for patch in patches:
        field_key = str(patch.get('field_key') or '')
        if field_key not in PLAN_DEADLINE_FIELD_KEYS:
            continue
        if str(patch.get('status') or '') != 'filled':
            continue
        plan_year = _latest_year(patch.get('value'))
        if plan_year is None or plan_year <= licence_year:
            continue
        locator = locator_map(patch.get('source_locator'))
        locator['selection_trace'] = PLAN_BEYOND_LICENCE_TRACE.format(
            plan=str(patch.get('value')).strip(),
            licence=str(stated_end).strip(),
        )
        locator['policy'] = 'plan_deadline_beyond_licence_term'
        patch['source_locator'] = locator
        beyond.append(field_key)
    if not beyond:
        return repaired, []
    return repaired, [
        cells_note(
            '{count} ячеек плана ГРР: срок работ выходит за окончание лицензии '
            '({licence_end}) — требуется продление лицензии или исправление '
            'срока ({keys}).',
            beyond,
            licence_end=str(stated_end).strip(),
        )
    ]


_EXPANSION_MARKERS = ('web_search', 'web:', 'http://', 'https://')


def gis_retrieval_expansion(
    trace: Sequence[Mapping[str, Any]],
    patches: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Which GIS absences sent the run looking somewhere else, and where.

    Joins the GIS trace entries that were not accepted, by
    `rejection_reason`, with the patches carrying
    `source_locator.absence_code`. Returns one record per absence code: its
    semantic roles, the blocked field keys, the keys whose locator shows a
    search outside the project (`_EXPANSION_MARKERS`), and those of them that
    are `filled`.
    """
    roles_by_code: dict[str, set[str]] = {}
    for entry in trace:
        code = str(entry.get('rejection_reason') or '')
        role = str(entry.get('semantic_role') or '')
        if code and role and not entry.get('accepted'):
            roles_by_code.setdefault(code, set()).add(role)
    cells_by_code: dict[str, list[Mapping[str, Any]]] = {}
    for patch in patches:
        locator = patch.get('source_locator')
        if not isinstance(locator, Mapping):
            continue
        code = str(locator.get('absence_code') or '')
        if code:
            cells_by_code.setdefault(code, []).append(patch)
    expansions: list[dict[str, Any]] = []
    for code in sorted(set(roles_by_code) | set(cells_by_code)):
        cells = cells_by_code.get(code) or []
        searched: list[str] = []
        answered: list[str] = []
        for patch in cells:
            field_key = str(patch.get('field_key') or '')
            rendered = json.dumps(
                patch.get('source_locator'), ensure_ascii=False
            ).casefold()
            if not any(marker in rendered for marker in _EXPANSION_MARKERS):
                continue
            searched.append(field_key)
            if str(patch.get('status') or '') == 'filled':
                answered.append(field_key)
        expansions.append(
            {
                'absence_code': code,
                'semantic_roles': sorted(roles_by_code.get(code) or ()),
                'blocked_field_keys': sorted(
                    str(patch.get('field_key') or '') for patch in cells
                ),
                'searched_elsewhere_field_keys': sorted(searched),
                'answered_elsewhere_field_keys': sorted(answered),
            }
        )
    return expansions


MODEL_ENTAILED_PHENOMENA: tuple[dict[str, Any], ...] = (
    {
        'model_id': 'porphyry',
        'model_ru': 'медно-порфировая модель',
        'phenomenon_ru': 'гидротермальные изменения',
        'model_rows': (16, 18, 19, 27),
        'phenomenon_row': 26,
        'model_pattern': re.compile(r'(?:(?<=^)|(?<=[^0-9A-Za-zА-Яа-яЁё]))порфир', re.IGNORECASE),
    },
)

MODEL_CONTRADICTION_TRACE = (
    'Аудит противоречий: карта утверждает {model} в строках {model_rows}, '
    'а строка {phenomenon_row} «{phenomenon}» пуста во всех {cells} ячейках. '
    'Модель этого типа определяется этим процессом, поэтому пустая строка и '
    'заявленная модель не могут быть верны одновременно. Значение не '
    'подставлено: модель не называет ни тип, ни степень изменений.'
)


def _stated_model_rows(
    patches: Sequence[Mapping[str, Any]],
    entailment: Mapping[str, Any],
) -> list[int]:
    """Model rows that actually state the model, by row id."""
    pattern = entailment['model_pattern']
    rows = set()
    for patch in patches:
        row_id = _patch_row_id(patch)
        if row_id not in entailment['model_rows']:
            continue
        if str(patch.get('status') or '') != 'filled':
            continue
        if pattern.search(str(patch.get('value') or '')):
            rows.add(row_id)
    return sorted(rows)


def flag_model_contradictions(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A phenomenon row cannot be empty while the model that entails it stands.

    When a `filled` model row of a `MODEL_ENTAILED_PHENOMENA` entry states its
    model and every cell of the phenomenon row in this envelope has a status
    in `EMPTY_CELL_STATUSES`, each of those cells moves to
    `requires_expert_review` with value, unit and value origin cleared,
    `MODEL_CONTRADICTION_TRACE` and policy `model_entails_phenomenon`. No
    value is supplied. Returns the envelope and a plain-text run note per
    contradiction.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    patches = repaired['patches']
    notes: list[str] = []
    for entailment in MODEL_ENTAILED_PHENOMENA:
        model_rows = _stated_model_rows(patches, entailment)
        if not model_rows:
            continue
        phenomenon = [
            (index, patch)
            for index, patch in enumerate(patches)
            if _patch_row_id(patch) == entailment['phenomenon_row']
        ]
        if not phenomenon:
            continue
        if any(
            str(patch.get('status') or '') not in EMPTY_CELL_STATUSES
            for _, patch in phenomenon
        ):
            continue
        trace = MODEL_CONTRADICTION_TRACE.format(
            model=entailment['model_ru'],
            model_rows=', '.join(str(row) for row in model_rows),
            phenomenon_row=entailment['phenomenon_row'],
            phenomenon=entailment['phenomenon_ru'],
            cells=len(phenomenon),
        )
        for _, patch in phenomenon:
            locator = locator_map(patch.get('source_locator'))
            locator['selection_trace'] = trace
            locator['policy'] = 'model_entails_phenomenon'
            patch['source_locator'] = locator
            patch['status'] = 'requires_expert_review'
            patch['value'] = None
            patch['unit'] = None
            patch['value_origin'] = None
        notes.append(
            f'Строка {entailment["phenomenon_row"]} «{entailment["phenomenon_ru"]}» '
            f'пуста во всех {len(phenomenon)} ячейках, при том что строки '
            f'{", ".join(str(row) for row in model_rows)} утверждают '
            f'{entailment["model_ru"]}. Противоречие передано эксперту; '
            f'значение не подставлено.'
        )
    return repaired, notes


def coerce_contradictory_patch_fields(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Repair the two contradictions where the owner's intent is unambiguous.

    A `filled` patch whose value is a negative value marker becomes
    `not_found` with value, unit and value origin cleared. A patch with a
    status in `_VALUELESS_STATUSES` loses its value, unit and value origin
    when it carries a value, or its value origin alone when it carries only
    that. Returns the envelope and a run note per repaired cell.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    notes: list[str] = []

    for index, patch in enumerate(repaired['patches']):
        status = str(patch.get('status') or '')
        field_key = str(patch.get('field_key') or f'patches[{index}]')

        if status == 'filled' and _is_negative_value_marker(patch.get('value')):
            patch['status'] = 'not_found'
            patch['value'] = None
            patch['unit'] = None
            patch['value_origin'] = None
            notes.append(
                cells_note(
                    '{count} ячеек: статус исправлен с filled на not_found — '
                    'значение является маркером отсутствия, а не величиной '
                    '({keys}).',
                    [field_key],
                )
            )
            continue

        if status in _VALUELESS_STATUSES and patch.get('value') is not None:
            patch['value'] = None
            patch['unit'] = None
            patch['value_origin'] = None
            notes.append(
                cells_note(
                    '{count} ячеек: значение снято — статус {status} не может '
                    'нести величину ({keys}).',
                    [field_key],
                    status=status,
                )
            )
        elif status in _VALUELESS_STATUSES and patch.get('value_origin') is not None:
            patch['value_origin'] = None
            notes.append(
                cells_note(
                    '{count} ячеек: value_origin снят — статус {status} не '
                    'может нести происхождение ({keys}).',
                    [field_key],
                    status=status,
                )
            )

    return repaired, notes


def normalize_source_inventory(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Coerce owner sources to the submission schema, then deduplicate.

    Each source becomes `source_id`, `source_type`, `title`, `locator` and
    `url`. A missing `source_type` comes from `source_domain` through
    `_DOMAIN_TO_SOURCE_TYPE`, else `derived`. A missing title falls back to
    `<producer> evidence`, the first 120 characters of `retrieval_note`, then
    the `source_id`. An empty `locator` falls back to `source_locator`, and a
    mapping or list locator is serialised as JSON. Entries without a
    `source_id` are dropped. Sources equal in type, title, locator and URL
    merge into the first, and patch `source_refs` are remapped to it;
    non-mapping patches are dropped. Returns the envelope and plain-text run
    notes.
    """
    raw_sources = envelope.get('source_inventory')
    if not isinstance(raw_sources, list) or not raw_sources:
        return dict(envelope), []

    notes: list[str] = []
    repaired: list[dict[str, Any]] = []
    canonical: dict[str, str] = {}
    by_identity: dict[tuple, str] = {}
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
