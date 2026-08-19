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
from ...geotizer.semantics import semantic_hint
from ...project_evidence.retrieval import (
    build_retrieval_plans,
)
from .validation import (
    _contract_violations,
    _partition_violations,
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
)
from ...project_evidence.proposals import (
    _review_hypothesis,
    normalize_contributor_evidence,
)


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


def merge_owner_envelopes(
    next_batch: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Merge validated chunk envelopes into one atomic GIS batch submission."""
    if len(chunks) != len(envelopes) or not chunks:
        raise GeotizerOrchestrationError('Owner chunks and envelopes must form one non-empty partition')

    sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    patches: list[dict[str, Any]] = []
    for chunk_index, (chunk, envelope) in enumerate(
        # The guard above already refuses a ragged partition; `strict` keeps the
        # two statements from drifting apart.
        zip(chunks, envelopes, strict=True),
        start=1,
    ):
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
    violations = validate_owner_envelope(next_batch, merged)
    if violations:
        raise GeotizerOrchestrationError('; '.join(violations))
    return merged


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
                },
                'retrieval_note': (
                    f'{_owner_failure_sentence(attempts, attempt_diagnostics)} '
                    f'Validation feedback: {feedback_text}'
                ),
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
        locator = patch.get('source_locator')
        locator = dict(locator) if isinstance(locator, Mapping) else {}
        locator['if_not_why_not'] = {
            'reason_kind': 'excluded_by_rule',
            'rule': rule,
            'stated_reason': bounded_text(note, max_chars=600),
            'decided_by': 'policy',
        }
        patch['source_locator'] = locator
        patch['status'] = 'requires_expert_review'
        notes.append(
            f'{field_key}: значение отклонено правилом {rule!r}, а не отсутствует — '
            f'статус изменён с not_found на requires_expert_review.'
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
                f'{field_key}: статус исправлен с filled на not_found — значение '
                'является маркером отсутствия, а не величиной.'
            )
            continue

        if status in _VALUELESS_STATUSES and patch.get('value') is not None:
            patch['value'] = None
            patch['unit'] = None
            patch['value_origin'] = None
            notes.append(
                f'{field_key}: значение снято — статус {status} не может нести величину.'
            )
        elif status in _VALUELESS_STATUSES and patch.get('value_origin') is not None:
            patch['value_origin'] = None
            notes.append(
                f'{field_key}: value_origin снят — статус {status} не может нести происхождение.'
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
