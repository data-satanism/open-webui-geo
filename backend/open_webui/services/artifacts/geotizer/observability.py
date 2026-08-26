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

#: How much of an unparseable response is kept. See `owner_attempt_diagnostic`
#: for why only the unparseable case keeps any of it.
UNPARSEABLE_PREFIX_CHARS = 500


#: Characters per token, for an estimate the diagnostics label as one.
#:
#: There is no tokenizer below the purity boundary and the specialist's model
#: is a valve, so an exact count is not available where the diagnostic is
#: written. Three is the ratio measured on these prompts, which are JSON with
#: Russian evidence in them -- Cyrillic costs more per character than English
#: prose and the JSON scaffolding costs less. It is here to answer one
#: question: whether a request that produced nothing was near a context or
#: output ceiling, or nowhere near it.
CHARACTERS_PER_TOKEN_ESTIMATE = 3


#: Which half of the request each section is, for the one question a
#: zero-character response raises: was the model given too much to read, and
#: was it evidence or instruction that filled the window.
#:
#: A section named nowhere here counts as `other` rather than being folded
#: into a neighbour, so a key added to the prompt shows up as unclassified
#: instead of silently inflating one of the two halves.
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

    Run `6af7479f` stopped `KB-GRR-FACTORS` chunk 1/3 after two attempts that
    each returned zero characters, for the fourth run running. The record said
    what came back -- nothing, twice, with the SHA-256 of the empty string --
    and nothing at all about what went out, so every account of the cause was
    a guess: too large a prompt, a reasoning budget spent before any content,
    or a deterministic failure on one chunk. The three are distinguishable
    only from the request side.

    Sections are measured by re-serialising each value, so they sum to
    slightly less than `characters` -- the keys and the enclosing braces are
    not attributed to anyone. The totals are what the numbers are for.
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

    `response_mode` separates the two ways an attempt reaches the contract with
    nothing. They are not the same failure and they do not have the same fix:

      - `empty` — the specialist returned no characters. Nothing was written,
        so there is nothing to repair and no feedback that can change the next
        attempt. On run `6056e157` this took 24 of the 35 lost cells, and on
        `KB-GRR-FACTORS` all three attempts returned zero characters.
      - `unparseable` — the specialist wrote at length and none of it was an
        owner envelope. `KB-GEO` wrote 8,929 then 4,706 then 4,445 characters
        across three attempts with no candidate in any of them.

    Both used to be recorded as the same thing, and the card called both "did
    not satisfy the deterministic field contract", which is true of neither.

    **`text_prefix` is kept only for `unparseable`, and that is a deliberate
    narrowing of the previous no-raw-text rule.** A parsed response's content
    is already in the card, cell by cell, so recording it again buys nothing.
    An unparseable one is the only case where the text exists nowhere else and
    the run cannot be diagnosed without it -- with `candidate_count=0` and no
    prefix, `KB-GEO`'s three attempts are indistinguishable from each other and
    from any other prose. The prefix is bounded to
    `UNPARSEABLE_PREFIX_CHARS` characters and lands in `state.json`, which is
    downloadable, so it is owner output and should be read as such.
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
        # An attempt that produced something can be diagnosed from what it
        # produced, so it carries the two totals and no breakdown. An empty
        # one cannot be diagnosed from its response at all -- there isn't one
        # -- so the whole of the request side goes in the record.
        diagnostic['request'] = (
            outbound
            if response_mode == EMPTY_RESPONSE
            else {key: outbound[key] for key in ('characters', 'tokens_estimate')}
        )
    return diagnostic
