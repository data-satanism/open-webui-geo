"""Observability for the owner attempt."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from .owner_envelope import (
    EMPTY_RESPONSE,
    PARSED_RESPONSE,
    UNPARSEABLE_RESPONSE,
    _owner_payload_candidates,
)

UNPARSEABLE_PREFIX_CHARS = 500


CHARACTERS_PER_TOKEN_ESTIMATE = 3


OWNER_REQUEST_SECTION_ROLES = {
    'attempt': 'instruction',
    'backend_owned_envelope': 'instruction',
    'field_semantics': 'instruction',
    'operation': 'instruction',
    'output_contract': 'instruction',
    'rules': 'instruction',
    'semantic_policy_version': 'instruction',
    'context.batch': 'instruction',
    'context.object_name': 'instruction',
    'context.run_id': 'instruction',
    'context.accepted_field_summary': 'evidence',
    'context.contributor_evidence': 'evidence',
    'context.datacube': 'evidence',
    'context.knowledge_search_plan': 'evidence',
    'context.retrieval_plans': 'evidence',
    'previous_output': 'repair',
    'repair_feedback': 'repair',
}


def owner_request_diagnostic(prompt: Any) -> dict[str, Any]:
    """How large the outbound request was, and what filled it.

    Returns `characters` and `tokens_estimate` for the rendered prompt. When
    the prompt parses as a JSON object it also returns `characters_by_role`
    (`evidence`, `instruction`, `repair` and `other`, per
    `OWNER_REQUEST_SECTION_ROLES`) and the eight `largest_sections`. Each
    top-level key is a section and `context` is split into `context.<key>`
    sections; sections are measured by re-serialising each value, so they sum
    to slightly less than `characters`.
    """
    rendered = prompt if isinstance(prompt, str) else str(prompt or '')
    diagnostic: dict[str, Any] = {
        'characters': len(rendered),
        'tokens_estimate': len(rendered) // CHARACTERS_PER_TOKEN_ESTIMATE,
    }
    try:
        payload = json.loads(rendered)
    except (TypeError, ValueError):
        return diagnostic
    if not isinstance(payload, dict):
        return diagnostic

    sections: dict[str, int] = {}
    for key, value in payload.items():
        if key == 'context' and isinstance(value, dict):
            for inner_key, inner_value in value.items():
                sections[f'context.{inner_key}'] = len(json.dumps(inner_value, ensure_ascii=False))
            continue
        sections[str(key)] = len(json.dumps(value, ensure_ascii=False))

    by_role: dict[str, int] = {'evidence': 0, 'instruction': 0, 'repair': 0, 'other': 0}
    for name, size in sections.items():
        by_role[OWNER_REQUEST_SECTION_ROLES.get(name, 'other')] += size
    diagnostic['characters_by_role'] = by_role
    diagnostic['largest_sections'] = [
        {'section': name, 'characters': size}
        for name, size in sorted(sections.items(), key=lambda item: -item[1])[:8]
    ]
    return diagnostic


def owner_attempt_diagnostic(
    text: str,
    *,
    attempt: int,
    request: Any = None,
) -> dict[str, Any]:
    """Classify one owner attempt and return bounded diagnostics.

    `response_mode` is `empty` when the response is blank or whitespace,
    `unparseable` when it holds no owner-envelope candidate, and `parsed`
    otherwise. `text_prefix`, the first `UNPARSEABLE_PREFIX_CHARS` characters
    of the response, is kept only for `unparseable`. When `request` is given,
    `request` holds the whole `owner_request_diagnostic` for an `empty`
    response and only its `characters` and `tokens_estimate` otherwise.
    """
    rendered = text if isinstance(text, str) else str(text)
    candidates = _owner_payload_candidates(rendered)
    if not rendered.strip():
        response_mode = EMPTY_RESPONSE
    elif not candidates:
        response_mode = UNPARSEABLE_RESPONSE
    else:
        response_mode = PARSED_RESPONSE
    diagnostic = {
        'attempt': attempt,
        'sha256': hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
        'character_count': len(rendered),
        'candidate_count': len(candidates),
        'candidate_keys': [sorted(str(key) for key in candidate.keys())[:12] for candidate in candidates[:4]],
        'response_mode': response_mode,
    }
    if response_mode == UNPARSEABLE_RESPONSE:
        diagnostic['text_prefix'] = rendered[:UNPARSEABLE_PREFIX_CHARS]
    if request is not None:
        outbound = owner_request_diagnostic(request)
        diagnostic['request'] = (
            outbound
            if response_mode == EMPTY_RESPONSE
            else {key: outbound[key] for key in ('characters', 'tokens_estimate')}
        )
    return diagnostic
