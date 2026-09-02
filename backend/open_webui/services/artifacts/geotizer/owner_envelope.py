"""The GeoTeaser owner envelope: batching, extraction, merge and repair.

CORE-BOUNDARY-01 action 2. GeoTeaser-specific logic lives here and nowhere
else.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
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


#: How many cell keys a run note names before it stops listing them.
RUN_NOTE_KEY_SAMPLE = 6


def cells_note(template: str, field_keys: Sequence[str], **fields: Any) -> dict[str, Any]:
    """One rule's verdict on some cells, before it is a sentence.

    Every rule here used to render its own note the moment it fired, and every
    rule fires once per chunk. So run `af707b17` shipped nine separate «N
    пустых ячеек без причины» notes and three «resource_estimate_needs_more_
    than_a_press_number» ones, and run `973999df` shipped twenty-two lines of
    «значение снято — статус conflicted не может нести величину», one per
    cell. Deduplication could not merge them: each already carried its own
    count and its own key list, so the strings differed. The reader was being
    shown the chunk boundaries -- «1 ячеек» is a chunk of one, not a rule that
    touched one cell.

    The note is therefore kept as its rule and its cells until the run ends.
    `render_run_notes` groups by the template and whatever fields vary within
    it, and writes one sentence per rule for the whole run.

    The template is the grouping key, which is why there is no registry of
    rule names to keep in step with one: two notes are the same rule exactly
    when the same template produced them.
    """
    return {
        'template': template,
        'field_keys': [str(field_key) for field_key in field_keys],
        'fields': dict(fields),
    }


def render_run_notes(notes: Sequence[Any]) -> list[str]:
    """One sentence per rule per run, in the order the rules first fired.

    Plain strings pass through deduplicated -- a note about the run rather
    than about a set of cells (a deadline, a chunk size) has nothing to
    aggregate.
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

    The one place an agent name still means something to this repository, and it
    is a mode rather than a route: the skilled agent's owner call is the bounded
    decision that must not be able to change state while it is being made. The
    tool agrees independently -- `AGENT_CATEGORIES['skilled']` is empty -- so
    this is the near side of one rule, not a routing table with one row.
    """
    if task.role == 'owner' and task.agent == 'skilled':
        return 'tool_free_owner'
    if task.role == 'owner':
        return 'specialist_owner_completion'
    return 'specialist_contributor'


def build_batch_tasks(next_batch: Mapping[str, Any]) -> tuple[AgentTask, ...]:
    """Plan contributor calls before the single exact owner call.

    The producer travels verbatim into `AgentTask.agent`. Nothing here validates
    it against a list of agents, because the list this repository could check
    against would be a copy of the tool's, and a copy is exactly what put a
    second failure point between the batch plan and the model. The refusal lives
    in `run_agent_task`, which owns the model valves and the tool surfaces and
    can therefore say what it does serve.

    A name this tool does not serve still ends the run -- `unknown_agent` is
    `retryable: false` -- so strictness is not lost. It moved to where the
    configuration is.
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


#: Keys inside a `source_locator` whose values are source ids, and so have to
#: follow the rename that `merge_owner_envelopes` applies to the inventory.
#: `source_ref` values live wherever a locator puts them, and a rename that
#: walks a list of known places is out of date the moment a later round adds
#: one. Four rounds taught this function a new key:
#:
#:     patch['source_refs']                 taught
#:     source_locator.candidates            taught, later
#:     source_locator.negative_findings     taught with it
#:     source_locator.spatial_divergence    taught two rounds after that
#:
#: The state-level invariant in `gis_service`'s render-readiness audit found a
#: fifth on its first run -- `candidates[0].locator.candidates[0].source_ref`
#: and `owner_locator.candidates[…]` on r096, a locator nested inside a
#: candidate's own locator. So this walks the whole locator instead of naming
#: places in it. A rename with no idea what the structure is cannot fall behind
#: the structure.
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


#: A resource row whose attributes report two estimates. Recorded on the
#: locator of every cell of that row, so the reason survives into the state --
#: the run note below is a fact about the run and does not reach a cell.
INCOHERENT_ESTIMATE_ROW_TRACE = 'resource_row_reports_more_than_one_estimate'


def refuse_incoherent_resource_rows(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Mark a row that reports two estimates; do not end the run over it.

    A row of six attributes that names two estimates is one wrong row. Until
    now it was a `GeotizerOrchestrationError` out of `merge_owner_envelopes`,
    which ended the fill: run `6a791799` stopped on «resource row 48 mixes
    resource_estimate_id: ['RE-2001-PKH', 'RE-2025-PROJ']» with every other
    batch already answered and nothing written.

    The scope of the defect is the row, so the scope of the refusal is the row.
    Its cells become `requires_expert_review` naming both identities and
    keeping the value each cell actually carried -- a reader has to be able to
    see what was found, and dropping the values would make the row
    indistinguishable from one nobody searched.

    This is the only rule in the envelope contract that can first fail at merge
    time. Everything else `validate_owner_envelope` checks is either per patch,
    and so already checked when the chunk was accepted, or structural -- the
    partition and the batch header, which a marked row cannot repair. So this
    is one degradation, not the first of a family.
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
        # `requires_expert_review` is not `filled`, and a non-filled patch that
        # keeps a `value_origin` is refused by the envelope contract.
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


#: What a `not_found` cell says when the owner wrote no reason for it.
#: Composed from the locator the patch already carries, never invented.
NEGATIVE_SEARCH_WHERE_RU = 'Где искали: {where}.'
NEGATIVE_FINDING_NOTE_RU = ' Результат поиска: {findings}.'


#: The statuses that leave a cell empty and therefore owe a reason. A reader of
#: an empty cell asks the same question whichever of the two it carries, and
#: the answer is in the same place.
#:
#: `not_applicable` joined on run `f480a072`, which returned twelve of them --
#: rows 51 and 52, участок 2 and участок 3 -- every one with an empty note. It
#: is a status the state machine has always allowed, that nothing in either
#: service sets, and that no run had produced before.
EMPTY_CELL_STATUSES = ('not_found', 'not_applicable')

#: What each of them says before the projected «где искали». `not_applicable`
#: is an answer and `not_found` is a gap, and a cell that reads the same for
#: both would lose the distinction the owner drew by choosing between them.
EMPTY_CELL_REASON_PREFIX_RU = {
    'not_found': 'Значение не найдено.',
    'not_applicable': 'Строка неприменима к этому объекту.',
}

#: Where `state_the_negative_search` records which status it composed a note
#: for. A projected reason is only true of the status it was written for, and
#: nine passes in this module move a patch's status after the projection has
#: run. Run `803ce041` is what that costs: `flag_invalid_scope_conclusions`
#: moved 40 cells to `requires_expert_review` and 28 of them kept «Значение не
#: найдено» -- a sentence claiming the search happened and came back empty, on
#: the cells whose whole point is that the search was never valid.
#:
#: Stamped into the locator rather than onto the patch, because the locator is
#: already where a pass records what it did to a cell (`policy`,
#: `selection_trace`) and the patch is the contract's shape.
PROJECTED_REASON_STATUS_KEY = 'projected_reason_for'

#: What an `invalid_scope` cell says instead. Not the `not_found` sentence with
#: a different status on it: the two disagree, and the reader trusts the
#: sentence. The distinction is the same one `rule_excluded` draws against
#: `not_found` -- there a value existed and a rule refused it, here the search
#: never opened a corpus, so its emptiness is not evidence about the corpus.
INVALID_SCOPE_REASON_RU = (
    'Поиск выполнен в области, не являющейся коллекцией базы знаний. '
    'База знаний не открывалась; значение не искали.'
)


def state_the_negative_search(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Give an empty cell the reason the state already holds for it.

    GT-POLICY-01: a cell that reads «не найдено» has to say why. Run
    `d0a464be` shipped 100 `not_found` cells of which **59 carry an empty
    `retrieval_note`** -- 40 from `KB-STUDY`, 16 from `KB-RESOURCE-TECH`, 3
    from `KB-LIC-LEGAL`. The card renders the note, so the reader sees an empty
    cell and no reason at all.

    The reason was never missing. All 59 carry a locator saying where the
    search went -- «searched: lekyn_new_data, Lekyn-Talbeyskaya, Полярный
    Урал», «layer_id: Скважины_ГСК, layer_inventory», «Document: 8b407795…,
    Page: 1, 4» -- and three also carry a `negative_findings` entry saying what
    came back. It is the same shape as the run log before it had a carrier: the
    fact is in the state and not in the field anything reads.

    So this is a projection and not a judgement. Nothing is composed that the
    patch does not already say, a patch that already has a note keeps it
    untouched, and a patch with nothing to project is left alone rather than
    given a sentence that says only that it has none.
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
        # The sentence is only true of `status`. Stamped so a later pass that
        # moves the status cannot leave this one standing underneath it.
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
                '{count} пустых ячеек без причины: причина взята из '
                'source_locator ({keys}).',
                written,
            )
        ],
    )


#: A source id the owner cited inside a locator and never registered. Recorded
#: as a source of its own rather than dropped, because the id is the only trace
#: of what the owner meant by it.
UNREGISTERED_LOCATOR_REF_TYPE = 'derived'


def register_locator_only_sources(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    run_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """Give every ref recorded inside a locator a source it can resolve against.

    `source_refs` on the patch has been checked against the inventory since the
    contract existed. The refs *inside* the locator never were, and they are
    the ones a reader follows to see the losing side of a conflict or what a
    negative search actually consulted.

    Run `6e68eeec` is the measurement: eight refs across six cells resolved
    against nothing — «vsluh-2007-07-03__geotizer_object.v1.r068.a05» on three
    `negative_findings`, two `candidates` on r081.a01, two on r087.a01, one
    `negative_findings` on r007.a01. None was in the chunk's inventory, so
    `merge_owner_envelopes` had no rename for it and it reached the finalized
    state naming a source that does not exist.

    Registered rather than refused, and registered rather than dropped. Refused
    would turn a provenance defect into `agent_contract_failed` — the value and
    its own source are sound, and only a secondary reference fails to resolve,
    so a failed cell would be the worse cell. Dropped would lose the id, which
    is the one thing that says what the owner was pointing at. What the new
    source says is exactly what is known: this id was cited here and never
    registered.
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

    Returns the submission and the run notes the merge produced. The notes are
    a second return rather than a key on the envelope because the envelope goes
    to `gis_service` and a note about the run is not a patch.
    """
    if len(chunks) != len(envelopes) or not chunks:
        raise GeotizerOrchestrationError('Owner chunks and envelopes must form one non-empty partition')

    sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    patches: list[dict[str, Any]] = []
    coherence_notes: list[str] = []
    for chunk_index, (chunk, envelope) in enumerate(
        # The guard above already refuses a ragged partition; `strict` keeps the
        # two statements from drifting apart.
        zip(chunks, envelopes, strict=True),
        start=1,
    ):
        # Here as well as after the merge, and for the same reason in both
        # places: a row inside one chunk is caught here, a row split across two
        # is caught there, and neither is worth the whole card.
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
            # `source_refs` was renamed and the locator was not, so every
            # `candidates[].source_ref` in the merged state named a source id
            # that no longer exists in it. On run `6af7479f` that was all 50
            # sides of 25 conflicts: the DOCX conflict cell prints `[{ref}]`,
            # `conflict_summary` returns it to a caller, and neither could be
            # resolved against `state.sources`. A conflict whose sides cannot
            # be traced to a source is the thing conflicts exist to avoid.
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
    # Before the merged check, because the merged check is the only place this
    # can be seen: a row that straddles two chunks is coherent inside each of
    # them. A retry batch is where that happens -- its fields are whatever is
    # still empty, so its chunks do not divide into whole rows the way a first
    # pass does.
    merged, merged_notes = refuse_incoherent_resource_rows(next_batch, merged)
    for note in merged_notes:
        if note not in coherence_notes:
            coherence_notes.append(note)
    violations = validate_owner_envelope(next_batch, merged)
    if violations:
        raise GeotizerOrchestrationError('; '.join(violations))
    return merged, coherence_notes


#: How an owner attempt ended, as classified by `owner_attempt_diagnostic`.
#: These live here rather than in `observability` because that module imports
#: this one for `_owner_payload_candidates`, and because what they name is an
#: outcome of envelope extraction.
EMPTY_RESPONSE = 'empty'
UNPARSEABLE_RESPONSE = 'unparseable'
PARSED_RESPONSE = 'parsed'


def _owner_failure_sentence(
    attempts: int,
    attempt_diagnostics: Sequence[Mapping[str, Any]],
    specialist_failures: Sequence[Mapping[str, Any]] = (),
    stopped_by_deadline: bool = False,
) -> str:
    """Say which way the owner failed, because the three need different readers.

    Every failure used to read "did not satisfy the deterministic field
    contract", which on run `6056e157` was true of exactly one of the five
    failing chunks. For the other four it pointed a reader at a contract that
    was never reached: `KB-GRR-FACTORS` returned zero characters three times,
    and `KB-GEO` wrote 18,080 characters across three attempts without ever
    emitting an envelope. A person deciding whether to rerun, re-scope or
    escalate needs those told apart -- rerunning is plausible for an empty
    response and pointless for a contract violation that will repeat.
    """
    # Before all of them, because it is the only one where nothing was asked.
    # The other three describe an answer that came back wrong, empty or not at
    # all; this one means the fill deadline was reached and no call was made,
    # so a reader looking for an attempt to diagnose would find none and
    # conclude the diagnostics were lost.
    if stopped_by_deadline:
        return (
            'The fill deadline was reached before these fields were '
            'requested, so no specialist and no owner call was made for them. '
            'This is a run that ran out of wall-clock time, not a run whose '
            'evidence was refused -- rerunning the object is what recovers '
            'them.'
        )
    # First of the three that are about the owner, because it is the only one
    # of them that is not about the owner at all. `KB-GRR-FACTORS` chunk 2/3
    # spent three attempts here and was reported as a contract failure on all
    # 18 of its cells.
    if specialist_failures:
        return specialist_failure_sentence(specialist_failures)
    modes = [str(item.get('response_mode') or '') for item in attempt_diagnostics]
    plural = 'attempt' if attempts == 1 else 'attempts'
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


#: The status a fallback patch carries when the run never got an answer, and
#: the one it falls back to on a deployment that has not heard of it.
#:
#: `requires_expert_review` was carrying both meanings. On run `6976094d` all
#: 35 review cells were failed agent calls -- none was a geological question --
#: and the card asked a geologist to inspect every one. The GIS service now
#: has a separate status, but it and this repository deploy separately: the
#: service from git, the Workspace tools by hand. Emitting a status the
#: deployed service rejects loses the whole envelope, so the batch is asked
#: what it accepts rather than told.
AGENT_FAILURE_STATUS = 'agent_contract_failed'
EXPERT_REVIEW_STATUS = 'requires_expert_review'


def failure_status_for(next_batch: Mapping[str, Any]) -> str:
    """Which status this run's fallback patches may carry.

    `ASSEMBLE` keeps `requires_expert_review` on purpose. Its fallback puts a
    review hypothesis in the cell, and accepting or rejecting that hypothesis
    is a geological judgement even though a contract failure is what produced
    it. Every other batch's fallback has no value at all to judge.
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
) -> dict[str, Any]:
    """Fail closed while preserving individually valid owner decisions.

    `feedback` is the last attempt's violations and `feedback_by_attempt` is all
    of them. The distinction cost a diagnosis: in run `5880a164` the
    `KB-GRR-FACTORS` chunk returned 9,372 characters, then 11,687 characters
    carrying a real `patches`/`source_inventory` envelope, then nothing -- and
    the card reported only `Agent returned an empty response`, because that was
    the third attempt's feedback and the first two had been overwritten. The
    violation that actually rejected a well-formed envelope was not recorded
    anywhere, so the histogram of what the contract refuses could not be built.
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
    )
    # A deadline stop has no validation feedback because nothing was validated.
    # Printing «Validation feedback: []» after it would invite a reader to go
    # looking for the empty list's contents.
    feedback_clause = '' if stopped_by_deadline else f' Validation feedback: {feedback_text}'
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
                    # Every attempt's violations, not only the last. Without it
                    # a chunk that was rejected for a real contract reason and
                    # then returned nothing reports only the empty response.
                    'owner_attempt_feedback': [dict(item) for item in feedback_by_attempt],
                    # Named separately from the attempt feedback, because a
                    # batch that died in the specialist and a batch the owner
                    # contract refused send a reader to different code.
                    'specialist_failures': [dict(item) for item in specialist_failures],
                    # Machine-readable, because «no call was made» and «three
                    # calls failed» are the same cell to a reader who only has
                    # the status, and only one of them is recovered by
                    # rerunning the object.
                    'stopped_by': 'fill_deadline' if stopped_by_deadline else None,
                },
                'retrieval_note': failure_sentence + feedback_clause,
            }
            for field in next_batch.get('fields') or []
        ],
    }
    if batch_id == 'ASSEMBLE':
        for field, patch in zip(
            next_batch.get('fields') or [],
            # Built from the same field list a few lines above, one patch each.
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
        # The resolved scope identity, not the name the caller typed. Salvage
        # validates one field at a time and the subarea rule compares against
        # the object, so a request spelled differently from the scope would
        # turn the probe back into the bypass it just stopped being.
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

    `object_name` has to reach the one-field probe or salvage becomes a way
    around any rule that needs it. The subarea check found this the day it
    landed: the attempt loop refused a chunk whose `site_name` was the object,
    all three attempts, and salvage then accepted the same patch from a
    candidate envelope because its probe validated without a name. A rule the
    retry loop enforces and salvage does not is not a rule.
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
            patch_by_key[field_key].update(patch)
            result['source_inventory'].extend(sources)
            accepted.add(field_key)
    return result


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
            return next(iter(unique.values()))
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
        ranked.append((recognized, -index, recovered))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]




#: How much raw previous output survives when no violation names a patch.
PREVIOUS_OUTPUT_CAP = 2000

#: `patches[6] geotizer_object.v1.r054.a01 resource ...` -- the index, and the
#: field_key when the violation carries one.
_VIOLATION_TARGET = re.compile(r'patches\[(\d+)\]')

#: The addressing prefix, so grouping compares rules and not addresses.
_VIOLATION_PREFIX = re.compile(r'^patches\[\d+\]\s*(?:\S+\.\S+)?\s*')


#: How many planned searches a run records. A run plans one set per KB
#: contributor per chunk, so the count grows with chunking; the cap is what
#: keeps a comparison file readable rather than a second copy of the run.
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

    Two clean runs against a pinned corpus, both `run_mode: clean`, both
    `kb_scope_status: configured`: `KB-RESOURCE-TECH` moved 56 -> 25 filled and
    `KB-STUDY` moved 30 -> 58, for a net of -3. Pinning the corpus did not
    remove the spread, so the variance is not in which collections were
    searched.

    The next hypothesis is what was searched *for*, and neither `state.json`
    can test it: `exact_query` appears **zero** times in both. The plans exist
    -- `build_retrieval_plans` produces them and they reach the contributor's
    evidence -- and then nothing persists them, so the queries are gone the
    moment the run ends.

    Recorded per plan rather than aggregated, because the comparison that
    matters is set against set: which searches one run issued that the other
    did not. `must_terms` and `should_terms` travel with `exact_query` because
    two plans can share a rendered query and differ in what they required.

    Bounded, and the bound is reported in the entry that trips it rather than
    silently truncating -- a query set that says it is complete and is not
    would make the comparison worse than having none.
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

    Bounding `previous_output` alone would not have shrunk the prompt that
    matters. `KB-RESOURCE-TECH 4/6` returned 48 violations, and they are five
    rules repeated across twelve patches. Worse, quoting each rule's contract
    into its text -- the change that made a resource rejection actionable --
    grew that chunk's feedback from 2,852 characters to roughly 7,644. Taken
    alone, that change made the empty-response mode it sits beside more likely,
    not less. The two have to land together.

    Grouping loses nothing: entries are deduplicated by their text with the
    `patches[N] <field_key>` prefix stripped, so twelve identical rejections
    become one rule and the list of patches it names. A rule whose text differs
    -- `row 54` against `row 55`, a different `allowed:` set -- stays a separate
    entry, because that difference is the part the owner has to act on.

    Only the prompt is grouped. `feedback_by_attempt` keeps the exact list,
    because that record exists to build a histogram of what the contract
    refuses and a grouped copy would undercount it.
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
        # Nothing collapsed. A plain list is easier to read than a list of
        # one-element groups, and an unchanged shape is one less thing for a
        # model to parse differently between attempts.
        return list(feedback)
    return [
        {'patches': grouped[rule], 'violation': rule} if grouped[rule] else rule
        for rule in order
    ]


def bounded_previous_output(previous_output: str, feedback: Any) -> Any:
    """The failed draft, cut down to the patches the violations name.

    Attempt 3 of `KB-RESOURCE-TECH 4/6` on run `6056e157` carried all 10,851
    characters of attempt 2 plus 48 violations, and returned nothing. Empty
    responses were 24 of that run's 35 lost cells, and the chunks that went
    empty are the ones whose earlier attempts were largest. Handing a model its
    own failed 10.8 KB draft and asking it to fix 48 things in it is a harder
    task than the one it just failed.

    The repair needs the violations and enough of the draft to locate them --
    not the draft. Every violation carries `patches[N]`, and the semantic ones
    now carry the `field_key` too, so the offending patches can be selected
    exactly rather than approximated by a character count.

    Two things it must not do. It must not imply the owner may return only the
    patches shown -- the contract is one patch per field in `batch.fields`, and
    a repair that returns three of twenty-two fails `patch count` instead. And
    it must not silently drop the rest: the note says how much was omitted, so
    a model that needs the omitted part can say so rather than invent it.

    Falls back to a character cap with the omitted middle marked when nothing
    can be parsed out of the draft, or when no violation names a patch -- a
    `patch count` or `missing field_key` violation is about the array as a
    whole, and there is no offending patch to show.
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

    # A ceiling on top of the selection, because selection alone bounds
    # nothing in the case that matters most. When every patch in the chunk
    # violates the same rule -- which is exactly what `KB-RESOURCE-TECH 4/6`
    # did, 48 violations over twelve of eighteen patches -- the "offending"
    # subset is the whole draft, and sending it back is what this exists to
    # stop. Whole patches are dropped rather than characters, so what survives
    # is still valid JSON the owner can read.
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

    The head carries the envelope's shape and the tail carries whatever the
    model was writing when it ran long, and those are the two ends a reader --
    or a model -- uses to orient. A single truncation keeps only the first.
    """
    if len(previous_output) <= PREVIOUS_OUTPUT_CAP:
        return previous_output
    half = PREVIOUS_OUTPUT_CAP // 2
    omitted = len(previous_output) - 2 * half
    return f'{previous_output[:half]}\n\n[... {omitted} characters omitted ...]\n\n{previous_output[-half:]}'


#: The marker a specialist agent writes when its own call failed. Read, never
#: written here -- it belongs to the Workspace side and this repository only
#: recognises it.
SPECIALIST_FAILED_MARKER = 'specialist_failed'

#: Two in a row ends the batch, the same rule an empty response follows. The
#: envelope itself asks for this: it carries `"retryable": true` next to
#: `"instruction": "One retry is acceptable; do not loop."`
MAX_CONSECUTIVE_SPECIALIST_FAILURES = 2


def specialist_failure_signal(text: Any) -> dict[str, Any] | None:
    """The specialist saying its own call failed, or None.

    On run `6976094d` the whole of `KB-GRR-FACTORS` chunk 2/3 was this and
    nothing else. All three attempts returned

        {"status": "specialist_failed", "agent": "kb",
         "code": "completion_failed", "retryable": true,
         "instruction": "One retry is acceptable; do not loop."}

    and the run put it through the owner-envelope validator, which found no
    `batch_id`, `producer`, `policy_version` or `template_version` in it and
    said so -- six violations per attempt, eighteen in total, every one of them
    telling the model to fix a field in a message the model never wrote. Then
    it sent the same prompt again. Twice. The envelope had already said not to.

    Recognising it is worth more than the saved call. `batch_id: expected
    'KB-GRR-FACTORS', got None` sends a reader to the owner prompt and the
    field contract; `the kb specialist reported completion_failed` sends them
    to the specialist's timeout, which is where the 27 lost cells actually
    came from.

    Deliberately narrow: the marker must be the payload's own `status`. A
    patch whose value happens to contain the word, or an owner envelope
    reporting a contributor's failure inside its own `patches`, is an owner
    response and is validated as one.
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
            'retryable': bool(root.get('retryable')),
        }
    return None


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


def compact_batch_context(
    next_batch: Mapping[str, Any],
    *,
    owner_agent: str,
    object_name: str,
    run_id: str,
    datacube: Mapping[str, Any] | None,
    contributor_evidence: Sequence[Mapping[str, Any]],
    knowledge_search_plan: Mapping[str, Any] | None = None,
    rag_v2_enabled: bool = False,
    rag_v2_collections: Sequence[str] = (),
    rag_v2_index_version: str | None = None,
    accepted_field_summary: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded context an owner needs; omit unrelated run state.

    `owner_agent` is the owner `AgentTask`'s agent, from the same chunk. RAG-v2
    retrieval plans belong to the knowledge owner, and the test for one was once
    the producer name compared against a hardcoded literal -- a second copy of
    the routing decision, so a contour that renamed its KB producer kept its
    batches and silently lost its retrieval plans.

    Comparing against `'kb'` is not that literal returning. Under
    `geotizer_assignments.v2` the agent name IS `kb`, so this reads the one
    field that decides which specialist runs rather than a name that had to be
    translated into it first. If a batch plan ever calls its knowledge owner
    something else, this gate goes quiet again -- which is why the agent set
    lives in the tool, where renaming one means editing the same artefact that
    holds its model valve.
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
    return {
        'object_name': object_name,
        'run_id': run_id,
        'batch': dict(next_batch),
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


# -- making the inventory submittable ----------------------------------------

# What an owner's `source_domain` means in the submission schema's vocabulary.
# `derived` is the fallback rather than `unknown`, because a source the owner
# produced from other sources is what an unattributed entry almost always is,
# and `unknown` would be a claim about the source rather than about our
# knowledge of it.
_DOMAIN_TO_SOURCE_TYPE = {
    'gis': 'gis',
    'web': 'web',
    'kb': 'knowledge_base',
    'knowledge_base': 'knowledge_base',
    'vision': 'vision',
}


# The statuses that may not carry a value. Taken from `validation.py`'s own rule
# rather than restated: it covers three, and a coercion that handles two leaves
# `conflicted` patches failing -- which is 25 cells on run 6056e157 alone.
_VALUELESS_STATUSES = frozenset({'not_found', 'not_applicable', 'conflicted'})


#: `... excluded by rule 'historical_actual_is_not_plan'.` -- the shape the
#: specialists use when a policy refuses a candidate they did find.
_RULE_EXCLUSION = re.compile(r"""rule\s+['"`]([a-z_]{4,})['"`]""", re.I)


def classify_rule_excluded_patches(
    next_batch: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A value a rule refused is not a value nobody found.

    On run `92661b9b` the whole `KB-GRR-FACTORS` block came back 0/42, and 18
    of those cells read:

        Searched GIS, KB, Web, Datacube. No 2024-2026 GRR Plan found.
        Historical data excluded by rule 'historical_actual_is_not_plan'.

    The rule is right, and it is the fix the domain review asked for: those rows
    used to fill with an investment declaration's 4 bn ₽ and three years, an
    investment figure standing in as a ГРР budget and duplicated onto the
    `all_grr` summary row. Wrong values were replaced by nothing.

    But `not_found` means *we looked and there is nothing there*, and the truth
    is *we found 2007 data and policy refused it*. The card said less than the
    run knew, which is the same failure as reporting coverage as accuracy --
    and it put a cell the programme deliberately emptied in the same bucket as
    a cell nobody ever found anything for.

    So a rule-excluded cell moves to `requires_expert_review`, which the card
    already reports separately, and carries a machine-readable `if_not_why_not`
    naming the rule and quoting what the specialist said it found.

    **The rule must be one the row declares.** `semantic_hint` publishes each
    row's `negative_cases` as `rules`, and only those count -- otherwise a model
    that writes the words "excluded by rule 'x'" into any note could move its
    own cell out of `not_found` by asserting a policy that does not exist.

    Nothing here invents a remedy. What would satisfy the requirement is the
    specialist's own sentence, kept verbatim and bounded; this code is not in a
    position to know what a current approved ГРР plan looks like, and a
    generated remedy would read exactly like a real one.
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
        # `locator_map`, not an isinstance guard: the guard here was dropping
        # `layer_id` and `project_id` off the four GIS layer reads and writing
        # `if_not_why_not` onto an otherwise empty locator, so the rule's own
        # evidence disappeared from exactly the cells a rule most often
        # excludes.
        locator = locator_map(patch.get('source_locator'))
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': rule,
            'stated_reason': bounded_text(note, max_chars=600),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
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


#: Source types that cannot carry a resource estimate on their own.
#:
#: One entry, and the narrowness is the point: `web` here means a press
#: release, a news article or a company page.
LONE_SOURCE_REFUSED_FOR_RESOURCES = frozenset({'web'})


#: The rule's name, as it appears in `selection_trace` and `if_not_why_not`.
LONE_WEB_RESOURCE_RULE = 'resource_estimate_needs_more_than_a_press_number'


def refuse_lone_web_resource_values(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A resource estimate whose only source is a press article is not one.

    `GT-POLICY-01` puts WEB last, and it executes only when two sources
    compete for one cell. Where WEB is the *only* source nothing fires and it
    wins by being alone: on run `05169ef1` that is 48 of the 74 filled cells
    in rows 44-57, against 14 from the knowledge base and 12 from GIS. No
    amount of conflict-resolution work reaches those cells, because there is
    no conflict in them.

    **Why resources and nowhere else.** A licensee's registered address from a
    state registry is a sound sole web source, and this rule must never grow
    to cover it. A resource figure is different for a specific reason: it is
    only a resource figure if it carries an estimate identity -- the category,
    the effective date, the author and the method it was computed by. A press
    article's tonnage has none of those, so it cannot satisfy the resource
    contract even when the number itself is right. Run `05169ef1` shows the
    consequence directly: one 2007 publication supplied the approved, the
    current and the minimum-target rows at once, because nothing in a bare
    number says which of the three it is.

    Refused, not deleted. The cell moves to `requires_expert_review` for the
    same reason `classify_rule_excluded_patches` does: `not_found` means
    nobody found anything, and here somebody did and policy declined it. The
    figure, its unit and its source stay on the locator so a reader can see
    what was rejected and decide.
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
                str(patch.get('retrieval_note') or ''),
                max_chars=600,
            ),
            'decided_by': 'policy',
        }
        # The rejected figure, kept where a resolved conflict keeps its losing
        # side. A refusal a reader cannot see is the same defect as a silent
        # resolution.
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


#: The rule name that lands on a refused spatial row, so a reader meeting it in
#: `state.json` can find the reasoning without reading the pipeline.
ABSENT_SPATIAL_LAYER_RULE = 'spatial_question_needs_a_spatial_answer'

#: The absences `gis_service` reports, and the sentence each one gets.
#:
#: They are not the same fact and the card must not print them as one. Run
#: `08330f72` produced 18 `layer_not_found` and 4
#: `no_labelled_feature_in_layer`, and only the first ever reached this side --
#: the second was recorded on the trace entry and nowhere the caller could read
#: it. `Расширение использования GIS` §4.2 says a missing layer is a technical
#: absence and not a geological one; a layer that is present and whose features
#: carry no name is neither. It is a defect in the project data, the reviewer
#: can fix it, and reporting it as a missing layer tells them not to look.
#:
#: `no_labelled_feature_in_layer` is no longer among them and its entries are
#: gone. It stopped being an absence when the measurement gate and the naming
#: gate were separated: a layer whose features carry no name is measured, the
#: distance reaches the cell, and the gap is stated in the cell's own text as
#: «(без названия в слое)». `unanswerable_field_keys` no longer reports it, so
#: an entry here could only ever be printed by mistake.
#:
#: `layer_lacks_required_attribute` takes its place, and had been missing:
#: `.get(code, ...['layer_not_found'])` below meant rows 38 and 39 -- blocked
#: because `Скважины_ГСК` carries no depth, no diameter and no year -- would
#: have been told «в GIS-проекте нет слоя», about a layer the project has with
#: 105 features in it.
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
    # The third code, and the only one of the three that is an answer rather
    # than an obstacle. Run `6e68eeec`: `licence` and `subsoil_user` both
    # measure against `СЛХ_025834_ТП`, a layer of exactly one feature -- the
    # run's own licence -- and both were reported as «the features have no
    # name» when the truth is «there are no other licences».
    'only_the_source_feature_in_layer': (
        'Слой «{labels}» в GIS-проекте есть, и единственный объект в нём — сам '
        'объект отчёта. Других объектов этой роли в проекте нет: это истинное '
        'отсутствие, а не дефект данных и не отсутствие слоя. Значение из '
        'документа или WEB сохранено в source_locator.candidates и не принято '
        'как измерение.'
    ),
}

#: What every refused spatial cell says after its absence has been named. The
#: clause each `ABSENCE_TRACE_RU` entry ends with, lifted out so an absence
#: code with no entry of its own can still be described correctly.
#: The note for an absence code `ABSENCE_NOTE_RU` has no wording for. It names
#: the code rather than borrowing another absence's sentence, so a reader of
#: the run notes meets an unfamiliar word instead of a false statement.
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

    Run `af707b17` put «Энергетическая база отсутствует» in the
    distance-to-energy-node cell and every check passed it. Nothing could
    object: the template declares no types, so a string in a cell that takes
    strings is all a validator could see. The row asks how far the energy base
    is; the answer says there is not one -- which may well be true, and is not
    a distance.

    `requires_expert_review` and not `not_found`, for the reason
    `refuse_rule_excluded_cells` gives and for the same shape of error:
    something *was* found and policy declined it. The negative-marker repair
    coerces to `not_found` and drops the value with it, which would put a cell
    whose answer the run holds in the same bucket as one nobody found anything
    for -- and would throw away the sentence a reviewer needs to tell an
    unanswerable row from a misread one.

    So the text stays on the patch and is quoted into `if_not_why_not`, the
    record the card already reads. `requires_expert_review` is not in
    `_VALUELESS_STATUSES`, so keeping the value is legal as well as useful.

    Run-wide by construction. The predicate is a property of the row, not a
    list of cells to repair, so any numeric row anywhere on the card that comes
    back with prose is caught by the same pass.
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
            'stated_reason': bounded_text(str(value), max_chars=600),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
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


#: The three rules the Domain Reviewer's answers of 2026-08-30 made
#: enforceable, recorded in
#: `operations/domain-review/2026-08-30__five-answers-from-the-domain-reviewer.md`.
#: Named separately because a reader of a refused cell has to be able to tell
#: which answer refused it.
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
    """Which of the three substitutions this cell is making, or None.

    Positive identification in every direction. The element vocabulary is
    closed and can be enumerated with confidence; the mineral vocabulary is
    not, and a rule that refused anything absent from a hand-written mineral
    list would refuse correct answers. So an unrecognised value passes, and the
    rule fires only when it is sure -- which is worth more here than one that
    fires often.
    """
    field_key = str(field.get('field_key') or '')
    value = patch.get('value')

    # Both directions require the *other* kind to be absent, and that is not
    # a softening of an unqualified answer -- it is the answer applied to what
    # it was about. The reviewer refused *substitution*: a mineral name standing
    # where an element is asked for. Native metals are both things at once, and
    # run `1c46b6ca` has the case: F60 «сопутствующие рудные минералы» reads
    # «сфалерит, галенит, блеклые руды, касситерит, шеелит, минералы группы
    # платиноидов, золото, серебро» — native gold and native silver, correctly
    # listed among ore minerals. Firing on the element name alone would refuse
    # that, which is the rule refusing a correct answer.
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
    """A row's declared kind is binding, and three answers made it enforceable.

    The Domain Reviewer's answers of 2026-08-30, unqualified in all three
    cases: a mineral name may not stand in an element field or the reverse; an
    absolute age is the age of the rocks, measured in millions and billions of
    years; and the mass of metal never substitutes for the tonnage of ore.

    The row contract already declared `allowed_value_kinds` on the resource
    rows and the previous round deferred enforcing it «until a run shows it
    arriving». Three cells then arrived stating the substitution in their own
    prose — «Объем руды не указан отдельно; тоннаж меди приведён как ресурсный
    показатель» — and the answer removes the condition anyway.

    `requires_expert_review` with the value kept, never `not_found`. Something
    was found and policy declined it, which is the distinction two earlier
    rounds established and which none of these answers changes. For the ore
    row both figures stay: where a source gives ore tonnage, grade and
    contained metal, that is one estimate answering three rows rather than one
    number serving all three, and a reviewer needs the number that was offered
    in order to route it.
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

    `value_origin: calculated` is the discriminator three rounds of
    verification have rested on, and run `35509321` made it ambiguous. `F38`
    held two candidates, both reading `calculated`: the GIS computation
    (`mean_geometry_length_m`, 34 features, EPSG:32642) and an owner value
    transcribed out of a layer summary whose locator is
    `avg(Shape_Length)=0.00262°` and which names no operation at all. One was
    computed; the other was read off the output of a computation and then
    given a different unit.

    **Not the agreement branch.** That branch fires only when `_claims_are_one`
    holds, and 88 м against 0.00262 км is the disagreement path -- the cell
    finalized `conflicted` under `direct_disagreement_is_conflicted`. The
    label was already on the owner's patch when it arrived.

    So the fix is here, on the way in, and it is narrow on purpose. Only a
    patch citing a **GIS layer** with no operation and no
    `confirmed_by_calculation` is relabelled. An owner deriving a figure by
    arithmetic from documents is genuinely `calculated` and is untouched --
    run `93bc59a9` measured 69 such cells against two GIS computations, so a
    broad rule here would mislabel the overwhelming majority to catch one.

    The value is not touched. Only the account of where it came from.
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
        # The locator has to state the figure itself, with its unit, the way
        # `summarize_layer` prints it: `avg(Shape_Length)=0.00262°`. That is
        # what makes the value a transcription -- the answer was already on
        # the page and the owner copied it.
        #
        # A contributor proposing `sum(length)` over a GIS layer is naming an
        # operation and not quoting a result, and it is `calculated`. Without
        # this line the rule demotes those too, which
        # `test_workflow_applies_structured_calculated_gis_proposal_before_submit`
        # caught before the rule reached a run.
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

    Three consecutive runs produced a wrong number in `F38` that rendered
    cleanly, and each round it was wrong differently:

        0.0024 «градусы»   obviously not an answer -- the owner ignored it
        0.0021 bare        no unit -- the owner supplied the row's
        0.00262 «км»       the source says degrees, the value says kilometres

    Labelling the source stopped the owner guessing the unit. It did not stop
    the owner overriding it, and `0.00262 км` is 2.62 metres against a measured
    88 -- wrong by a factor of 34 and perfectly plausible on the page.

    The rule is a string comparison between two fields of one patch: the unit
    the locator states for its figure against the unit the value carries. A
    conversion makes them legitimately differ, so a stated one -- an
    `operation` and a `calculation_crs`, or prose saying the figure was
    converted -- passes. `0.00262°` may become `88 м` by reprojection or stay
    `0.00262°`; it may not become `0.00262 км` in silence.

    Deliberately no geometry and no arithmetic. The cheapest rule available is
    also the one least able to misfire: a locator naming no unit is silent, an
    unknown spelling is silent, and only two *known and different* units
    refuse.

    `requires_expert_review` with both figures kept, the shape every other
    refusal here uses. The number was found and policy declined it, which is
    not the same as finding nothing.
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

    `calculate_infrastructure_field_proposals` has recorded
    `{"role": ..., "code": "layer_not_found"}` since it was written, and it
    reaches the card as prose inside an evidence blob that nothing
    deterministic reads. So the row stays open, and a question about *this
    object's geometry* is answered from prose: on `05169ef1` and `6af7479f`
    r078 takes `130` from a licence appendix while a settlements layer would
    have measured it, and r080-r083 read `undetermined` off the web.

    Both runs computed exactly one thing, `minimum_geometry_to_geometry`
    against `road` -- not because the other nine roles are unimplemented, but
    because `lekyn_new_data` holds no layer matching any of them.

    Refused to `requires_expert_review`, not `not_found`, and the documentary
    value is kept in `candidates` -- the same shape as
    `refuse_lone_web_resource_values`, for the same reason. `not_found` says
    nobody found anything; here the project has no instrument for the
    question, and a person may still know the answer.
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
            # An empty cell on a row the project has no instrument for. Run
            # `6e68eeec` shipped r079, r080, r082 and r083 reading «Значение не
            # найдено. Где искали: Web search: no data.» -- true, and an
            # invitation to search again. What the run knows and the cell did
            # not say is that no layer in a 34-layer project can answer these
            # rows, which is permanent.
            #
            # Stamped, not restatused. `requires_expert_review` is for a cell
            # where a documentary value was refused and a person may still
            # know; here nothing was found by anyone, so `not_found` is the
            # honest status and the reason is what was missing.
            #
            # The sentence is the contract's own `code_meaning_ru`, carried on
            # the item from `unanswerable_field_keys`. A second wording here
            # would be the catalogue transcribed into a Python string, which is
            # the drift this catalogue exists to end.
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
                str(patch.get('retrieval_note') or ''),
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
        # Falling back to `layer_not_found`'s sentence is how rows 38 and 39
        # would have been told «в GIS-проекте нет слоя» about a layer holding
        # 105 features: `layer_lacks_required_attribute` had no entry, and the
        # default said something false rather than nothing. A code this table
        # does not know is now described from the catalogue's own
        # `code_meaning_ru`, which travels on the item and is always right for
        # the code it came with.
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


#: r084 asks for infrastructure «в радиусе 50 км» and r085 «в радиусе 100 км».
#: On run `84afa9e2` three of r084's five cells held «г. Лабытнанги (130 км)»,
#: «ж/д ветка Сейда – Лабытнанги (130 км)» and «ж/д ветка Обская – Бованенково
#: (70 км)», and each had displaced a road this project measured at 0.0, 9.5 and
#: 35.5 km. A reader of the card is told three objects are within 50 km by cells
#: that say in their own text that they are not.
#:
#: This is not the source hierarchy. `Расширение использования GIS` §12 excludes
#: «GIS всегда главнее» and nothing here prefers GIS: a documentary value
#: stating «(30 км)» keeps r084 against any measurement, and a value stating no
#: distance at all is left exactly as it is. What is refused is a value that
#: contradicts the question its own row asks -- the same shape as
#: `resource_estimate_needs_more_than_a_press_number`, which refuses a figure
#: that cannot satisfy the resource contract however good its source.
OUT_OF_RADIUS_RULE = 'an_object_outside_the_radius_does_not_answer_the_row'

RADIUS_ROW_LIMITS_KM = {'r084': 50.0, 'r085': 100.0}

#: «(130 км)», «70–130 км», «в 60 км», «расстояние 60-300 км». Where a range is
#: written, the nearest end is taken, because that is the reading most
#: favourable to keeping the value.
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

    Not to compare against -- to subtract. When a computed candidate is
    displaced by a documentary value the run writes the measurement into the
    cell's note («Расчёт GIS для этой ячейки не выбран: автомобильная дорога
    row:17; 0.0 км»), so the note ends up holding two distances: the object's,
    from the specialist, and the measurement's, from this pipeline. Reading the
    nearest of the two would answer «is the object inside the radius» with a
    number about a different object -- 0.0 km for a road, on a cell naming a
    railway 70 km away.

    Taken from `spatial_divergence.measured` rather than by cutting the note at
    a sentence this code composed: the structured record is where the number
    came from, and a list of composed sentences is a list that goes stale.
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

    Read only when the value states none. The first shape of this rule read the
    value and nothing else, on the ground that a note is prose and a parser
    deciding what stays on a CPR card is a worse failure than the defect it
    fixes. The corpus says where that leaves the rule: of 176 filled r084/r085
    cells across eighteen runs, 143 state the distance in the value and **28
    state it only in the note -- twelve of them outside their row's radius**.
    All five filled r084 cells of run `d0a464be` are among the twelve:
    «ж/д ветка Обская – Бованенково» with a note reading «в 70 км», on the row
    that asks for objects within 50.

    A distance equal to the row's own radius is dropped, and that is the whole
    of what makes this safe. The commonest phrase on these rows is the row's
    radius restated -- «Населенный пункт в радиусе 100 км», five cells of run
    `92661b9b` -- which says nothing about where the object is, and reading it
    as the object's distance is a misread in both directions. Dropping it costs
    nothing even when it is the object's real distance: a distance equal to the
    limit is inside it.

    What survives is the nearest of the rest, which is again the reading most
    favourable to keeping the value: «в радиусе 50 км (фактически 70 км)» reads
    70 and is refused, «в радиусе 100 км: … (расстояние 60-300 км)» on the 100
    km row reads 60 and is kept.
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

    Two outcomes, and which one applies is decided by the evidence rather than
    by a preference. Where the cell already recorded a measurement that does
    satisfy the radius -- `spatial_divergence.measured`, written when the
    documentary value displaced it -- that measurement fills the cell, because
    it is the only remaining candidate and it is one this project computed.
    Where there is none, the cell goes to a person: the row has no answer this
    run can stand behind, and inventing one is what `not_found` would do.

    The refused value is kept in `candidates` either way, with the distance it
    stated and the radius it failed, so the reviewer sees what was declined and
    why rather than a cell that quietly changed.
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
        # Which field the distance came from, because «the value says 70 km»
        # and «the value names an object the note places at 70 km» are
        # different statements and the reviewer is reading the one the cell
        # makes.
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
            # The measurement's source first, because it is the one the cell
            # now cites; the refused document keeps its ref so the candidate
            # entry beside it still resolves.
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

    Reporting only -- nothing is changed. The record itself is written by
    `project_evidence.proposals`, one cell at a time, and a per-cell key in
    `state.json` is not something a reader of the card will ever go looking
    for. Run `08330f72` lost eight measurements silently and the loss was only
    visible by counting `gis-infrastructure-*` sources against the fields that
    referenced them, which is not a thing anyone will do twice.

    Counted after every applier, for the same reason the two refusal rules
    are: it reads the locator a cell ended up with, not the one any single
    pass proposed.
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
    """The locator as the source wrote it, without this module's own keys."""
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

    The coercion in every reader unblocks a run; this is the half that stops
    the next reader needing one. A patch should not be able to emit two shapes
    for one field, and until it could not, every new consumer of
    `source_locator` was one `.get()` away from the batch-2 crash.

    Parsed, not replaced: `project_id=…; layer_id=…` is the whole provenance of
    a GIS layer read, and coercing it to an empty mapping would erase the
    evidence of the four cells that carry the licence identity.

    Counted and disclosed, because an owner that starts emitting strings is a
    fact about the run -- the four in every run of this object are the
    service's own scope binding, and a fifth would be something new.
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

    `GRR_WORK_STAGE_BY_ROW[row_id]` is a constant lookup: row 68 is always
    `routes`, row 70 always `drilling`. The contract nonetheless refused any
    filled GRR patch that did not echo it back, and the model did not always
    echo it -- on run `05169ef1` chunk 1/3 of `KB-GRR-FACTORS` returned the
    same nine violations three times, all of them `work_stage is incompatible
    with row N; required: 'routes', got '(unset)'`, on exactly `вид`, `срок`
    and `документ` of each of rows 68-70. Never on the three quantitative
    attributes. Three attempts, eighteen cells, one derivable constant.

    That is the shape `backend_owned_envelope` already names: batch identity is
    "injected and validated by the backend. Do not spend output tokens echoing
    them." A value the backend can compute from `row_id` belongs on the same
    side of that line.

    **A contradicting value is not repaired.** If the owner writes a
    `work_stage` that disagrees with the row, that carries information -- it
    says the owner misread which row it was answering -- and the violation
    still fires. Only the unset case is filled in, and only for the rows the
    policy declares a stage for.
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


#: A conflict a reader cannot see the sides of.
#:
#: `_conflict_candidate` exists because run `6056e157` emptied all 25 of its
#: conflicted cells and left two locators behind, and every downstream reader
#: assumes otherwise: `geoteaser-fill` tells the model `state.json` holds each
#: conflict "with its competing values", the orchestration prompt's INV-6 and
#: OUT-3 require reporting "value A with source, value B with source", and the
#: DOCX conflict cell prints `candidates` and nothing else.
#:
#: That machinery covers the conflicts *this code* forms. It does not cover the
#: ones the owner declares for itself, and run `08330f72` has fourteen of them
#: -- `r045`, `r046`, `r048`, `r049`, `r050` -- each `conflicted` with
#: `value: null`, two or three `source_refs` and no record of what any of those
#: sources said. Fourteen of the run's twenty-seven conflicts print as an empty
#: «КОНФЛИКТ — ТРЕБУЕТ РАЗРЕШЕНИЯ» on the card.
UNRECORDED_CONFLICT_TRACE = (
    'Владелец объявил конфликт, но не записал конкурирующие значения. '
    'Стороны конфликта известны только по источникам: {refs}. '
    'Значения нужно смотреть в самих источниках.'
)


def record_unrecorded_conflicts(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Say so when a declared conflict carries no sides.

    Repaired rather than rejected, and the status is left alone. The values are
    gone -- they were never written down -- so there is nothing to recover and
    a stricter validator would only cost the rest of the chunk, which is the
    lesson `coerce_contradictory_patch_fields` records above. What is added is
    the one thing a reader needs and does not have: that the record is
    incomplete, and which sources to open instead.

    The prompt asks for the values as well, so the next run should produce
    fewer of these. The count in the run note is how that is measured.
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


#: A conflict needs two sides that state something. Recorded when one of them
#: states nothing at all.
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

    §4.1's rule, in the shape the marker check cannot see. That one refuses a
    negative *marker* — «неизвестно», «не указано» — used as a value; this is
    the case where the candidate's `value` is `null` outright, so there is no
    text to match and nothing to compare.

    Run `f480a072` is the first occurrence, and it is three cells of one row:
    r045.a01, a02 and a03 each hold `{value: 2332, unit: "тыс. т Cu"}` against
    `{value: null, unit: null, value_origin: null}`. Three of 193 conflicts
    across the whole corpus, all in that run.

    It matters out of proportion to the count because a conflict blocks
    publication. `unresolved_conflicts` is the audit check that fails, and
    these three hold the gate shut over a disagreement that does not exist —
    while telling a Competent Person «КОНФЛИКТ — ТРЕБУЕТ РАЗРЕШЕНИЯ» about a
    cell with one value and one silence.

    Marked, not decided. Promoting the surviving value would be the wrong
    repair here and the run says so in its own words: r045's note explains that
    the document gives P1+P2 while the row asks P3+P2+P1, so 2332 is a real
    number that does not answer the row. Which is a good reason to withhold and
    not a conflict, and the owner reached for the wrong vehicle. Every
    candidate is kept.
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


#: `geotizer_object.v1.r026.a01` -> 26. Read off the key rather than looked up
#: in the batch's field list, so a rule that needs a row id does not also need
#: to be handed the batch. Anchored on the whole key: a loose `r\d+` would take
#: the `v1` of a future `geotizer_object.v2` contract as a row.
_FIELD_KEY_ROW = re.compile(r'^geotizer_object\.v\d+\.r(\d{3})\.a\d{2}$')


def _patch_row_id(patch: Mapping[str, Any]) -> int | None:
    match = _FIELD_KEY_ROW.match(str(patch.get('field_key') or ''))
    return int(match.group(1)) if match else None


def retire_stale_projected_reasons(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """A reason composed for one status must not outlive it.

    `state_the_negative_search` projects «Значение не найдено. Где искали: …»
    onto an empty cell, and nine passes in this module can move that cell's
    status afterwards. The projection is true of the status it was written
    for and of no other, so any of those nine can strand it.

    Run `803ce041` shipped the case that names this: 40 cells moved to
    `requires_expert_review` by `flag_invalid_scope_conclusions`, 28 of them
    still reading «Значение не найдено» -- a sentence asserting the search
    ran and returned nothing, on cells whose finding is that the search never
    opened a corpus at all. `flag_invalid_scope_conclusions` now writes its
    own reason, which settles those 40. This settles the shape.

    The stale note is cleared rather than rewritten. Nothing here knows what
    the new status means for this cell -- only the pass that moved it does,
    and if that pass had a sentence it would have written one. An empty
    reason is a gap a reader can see; a confident wrong one is not.

    Deliberately not a validation failure. The envelope is the owner's, the
    stranding is ours, and refusing the batch would make a reporting defect
    look like a contract breach the owner could repair.
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


#: A cell that says it searched a corpus which is not one. A-88's conclusion
#: path: the specialist searched `lekyn_new_data`, found nothing, and wrote
#: `not_found` -- which claims the knowledge base was consulted and had no
#: answer, when the knowledge base was never opened.
INVALID_SCOPE_TRACE = (
    'Область поиска названа некорректно: «{scope}» не является коллекцией базы '
    'знаний, поэтому искать внутри неё нельзя. Пустой результат здесь означает, '
    'что поиск не состоялся, а не что документа нет. Ячейка передана эксперту; '
    'после исправления области поиска строку следует запросить заново.'
)


def flag_invalid_scope_conclusions(
    envelope: Mapping[str, Any],
    *,
    non_corpus_names: Sequence[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    """`not_found` from a search that had nowhere to look is not `not_found`.

    The same distinction as `rule_excluded` against `not_found`, one layer up.
    There, a value existed and a rule refused it; here, a search never
    happened and its emptiness is being reported as evidence of absence.

    §4.2's principle at the corpus level: a technical failure to look is not a
    finding about what is there. A cell reading «нет документа» after searching
    a GIS project id tells a Competent Person the knowledge base was checked.
    It was not.

    Marked, not answered. The repair is to fix the scope and ask again, which
    is a re-run and not something this pass can do -- so the cells go to
    `requires_expert_review` carrying the reason, rather than staying
    `not_found` where the completeness figure counts them as settled.
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
        locator = locator_map(locator)
        locator['selection_trace'] = INVALID_SCOPE_TRACE.format(scope=named)
        locator['policy'] = 'invalid_scope'
        # The status moves, so the reason moves with it. Whatever stood here
        # was composed for `not_found` -- either the owner's own sentence or
        # `state_the_negative_search`'s projection -- and both say the search
        # happened and found nothing, which is the opposite of what this rule
        # has just established.
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


#: The cells that state when planned work finishes, and the cell that states
#: when the right to do it expires. r068-r072 carry «срок» at `a05`, r073-r076
#: at `a02`, and r010 «Дата окончания» is the licence's own end date, read by
#: the run from `СЛХ_025834_ТП`'s `LDatefi`.
#:
#: Keyed on field keys and not on the attribute name «срок». «срок выполнения
#: работ» contains «выполнен», and matching Russian labels by substring is how
#: four earlier defects happened.
PLAN_DEADLINE_FIELD_KEYS = (
    *(f'geotizer_object.v1.r{row:03d}.a05' for row in range(68, 73)),
    *(f'geotizer_object.v1.r{row:03d}.a02' for row in range(73, 77)),
)
LICENCE_END_FIELD_KEY = 'geotizer_object.v1.r010.a01'

#: A four-digit year in 19xx-21xx. Bounded rather than `\d{4}`, so a cost of
#: «1200 тыс. руб.» in the cell beside it cannot be read as a year.
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

    Stage 6's GIS half, and it is smaller than the brief expected because the
    ГРР rows do not ask for geometry. Rows 68-76 want work types, volumes,
    scales, costs, deadlines and a document; a licence polygon answers none of
    them. The one thing `СЛХ_025834_ТП` does constrain is the outer bound: the
    licence runs 17.07.2024 to 17.07.2031 on this object, and work planned
    past that date needs an extension rather than a schedule.

    Compared on the year alone. A plan says «2026-2028» or «IV квартал 2027» и
    a licence says «17.07.2031»; parsing both into dates to compare them
    precisely would be a false precision, and the year is the granularity the
    contradiction actually lives at.

    The value is kept. Unlike a missing reason or a self-naming cell, nothing
    here says the extraction was wrong -- the plan may really run past the
    licence, which is a fact a Competent Person needs to see rather than a
    defect to repair.

    It fired zero times on run `f480a072`, because every «срок» cell in the
    block is empty. That is the block's real problem and this does not touch
    it: see the ГРР note in `operations/geotizer-runs`.
    """
    repaired = {
        **dict(envelope),
        'patches': [dict(patch) for patch in envelope.get('patches') or []],
    }
    patches = repaired['patches']
    # The licence end is r010, owned by `KB-LIC-LEGAL`; the plan deadlines are
    # rows 68-76, owned by `KB-GRR-FACTORS`. The two never share an envelope,
    # so the date has to come from what the run already accepted. Looked for in
    # this envelope first anyway, so the rule is testable on one envelope and
    # does not silently depend on batch order.
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


#: Locator words that mark a cell as answered by going outside the project.
#: `web_search`, `Web:` and a bare URL are the three shapes run `f480a072`
#: used, and they are what a GIS absence sends the owner to look for.
_EXPANSION_MARKERS = ('web_search', 'web:', 'http://', 'https://')


def gis_retrieval_expansion(
    trace: Sequence[Mapping[str, Any]],
    patches: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Which GIS absences sent the run looking somewhere else, and where.

    §5.9's observability ask. The expansion already happens and nothing
    records it: the trace says `road` resolved and `port` did not, and five
    cells of run `f480a072` carry «web_search, запрос '…порт'» in their
    locator. Two facts about the same event, in two places, joined by nobody
    -- so «did the run compensate for a missing layer, and did the
    compensation work?» could only be answered by reading a card by eye.

    Joined on the absence code, which both sides already carry: the trace as
    `rejection_reason`, the cell as `source_locator.absence_code`. Nothing new
    is threaded through the run and no catalogue lookup is needed, so this
    cannot go stale against a role table it does not read.

    Built at the end rather than recorded as it happens. The carrier
    principle: what describes a *run* rides `run_log.json`, and a retrieval
    driven by a layer's absence is a property of the run and not of any one
    cell. Deriving it from what was actually written also means it cannot
    disagree with what was actually written.

    Reports the outcome as well as the attempt. An absence that drove a search
    which found nothing is a different fact from one nobody searched for, and
    both differ from one the search answered -- the first says the data is not
    out there, the second says nobody looked.
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


#: A genetic model and the phenomenon it entails, by row. The model rows say
#: what kind of deposit this is; the phenomenon row says whether the process
#: that kind of deposit is defined by was observed. A card can hold both only
#: if they agree.
#:
#: Run `f480a072` holds the contradiction the third-party review found: r016
#: «ведущий геолого-генетический тип» = «медно-порфировая», r018 «тип» =
#: «медно-порфировое», r027 «Медно-порфировая модель рудообразования, связанная
#: с интрузиями Кызыгейского комплекса», and r026 «Гидротермальные изменения»
#: empty in all nine of its cells. A porphyry copper system is defined by its
#: alteration halo. The card states the model three times and reports the
#: alteration as not found.
MODEL_ENTAILED_PHENOMENA: tuple[dict[str, Any], ...] = (
    {
        'model_id': 'porphyry',
        'model_ru': 'медно-порфировая модель',
        'phenomenon_ru': 'гидротермальные изменения',
        'model_rows': (16, 18, 19, 27),
        'phenomenon_row': 26,
        # Anchored at a word start so «порфиров» matches «медно-порфировое»
        # across the hyphen and does not match inside an unrelated word. Four
        # substring defects preceded this rule -- `197` inside a UUID,
        # «выполнен» inside «срок выполнения работ», `reviewed_gap` inside
        # `reviewed_gaps`, «скважин» taking a whole layer -- and the stem is
        # matched as a stem, not as a substring of anything.
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

    §5.6's audit requirement, and the one part of Stage 5 that survives the
    column read. `BaseA_R_42`, `TectL_R_42` and `MranA_R_42` carry `INDEX`,
    `L_CODE` and `NAME`, so the layers exist -- but the manifest gives column
    *names* and not values, so which code system `INDEX` speaks is unknown and
    a spatial calculation for age or rock type cannot be written yet. This
    audit needs no geometry at all: it reads what the card already says.

    Deliberately not a repair. §5.6 forbids taking age or rock type from a
    spatial relationship, and taking alteration *type and degree* from a
    genetic model is the same move one step further: the model entails that
    alteration exists, and says nothing about which kind or how intense. The
    cells stay empty and gain a reason and `requires_expert_review`, which is
    the honest state -- a contradiction a Competent Person must settle, not a
    gap to fill.

    §4.2's converse also matters here and is why this reads the model rows
    rather than the GIS layers: the absence of an alteration layer would not
    prove the absence of alteration, so a missing layer is no evidence at all.
    What is evidence is the card contradicting itself.
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
        # Every cell of the row, not one. A row with one type named and eight
        # empty cells is an incomplete answer, not a contradiction, and
        # flagging it would bury the real case.
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

    A patch carrying `status=filled` beside a negative value marker states two
    incompatible things, and so does one carrying a valueless status beside a
    value. Either way the intent is readable, and rejecting the whole chunk over
    it costs every other cell in that chunk -- on run 6056e157 a single
    `patches[17] negative marker cannot use status=filled` took a chunk with it.

    The marker wins over the status, because a marker is a positive statement
    about absence and `filled` is the default a model reaches for.

    **`value_origin` has to go too, and that is the part worth stating**, since
    it is what makes the difference between a repair and a swap.
    `_value_origin_violations` refuses any non-`filled` status carrying a
    `value_origin` at all, so coercing to `not_found` while leaving
    `value_origin='direct'` trades one violation for another and the cell is
    lost just the same. Measured against the real validator, not reasoned.

    `unit` is dropped for tidiness and not for the validator, which has no unit
    rule -- the server's own sanitiser drops it, so the two agree.

    Returns `(envelope, notes)` in the shape `normalize_source_inventory` uses,
    and the notes are surfaced as run degradations. A silent repair is how a
    card comes to rest on a value nobody chose.
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

    Ported from the deployed Workspace Tool `geoteaser 2.2.0`
    (`GMM/operations/workspace-exports/geoteaser.py:3284`). Register A-04: the
    repaired version was in the production Tool and the broken one here, so a
    merge that took this repository's side would have reintroduced the defect.

    GIS requires `source_id`, `source_type` and `title`. This repository's
    `merge_owner_envelopes` copies each entry through and only re-namespaces the
    id, and the local validator only ever harvested `source_id` -- so an owner
    that serialized its contributor evidence as sources, carrying `producer`,
    `source_domain` and `source_locator` instead, passed every local check and
    was rejected with HTTP 422 at submission, after the whole batch had been
    built.

    Repairing rather than dropping keeps provenance that would otherwise be
    lost: the owner had the evidence, it just wrote it under the wrong schema.
    Returns `(envelope, notes)`; the notes are surfaced as run degradations,
    because a card built on rebuilt source metadata is not the same as one built
    on metadata the owner got right.
    """
    raw_sources = envelope.get('source_inventory')
    if not isinstance(raw_sources, list) or not raw_sources:
        return dict(envelope), []

    notes: list[str] = []
    repaired: list[dict[str, Any]] = []
    canonical: dict[str, str] = {}  # original source_id -> kept source_id
    by_identity: dict[tuple, str] = {}  # content -> kept source_id
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

        # Fall back through the fields that actually identify the source. The
        # source_id is last: it carries the chunk and attempt suffixes that make
        # otherwise identical entries look distinct and defeat deduplication.
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
