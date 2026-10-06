"""One model call's reply: the fixed reply schema, its parsing and the per-item guards."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .seed import PROPOSED_KINDS, SeedIndex

ITEM_OUTCOMES = ('accepted', 'excerpt_not_in_chunk', 'term_not_in_excerpt', 'unknown_seed_term')
CALL_OUTCOMES = ('unparseable', 'schema_violation', 'empty_completion', 'timeout')
OUTCOMES = ITEM_OUTCOMES + CALL_OUTCOMES

REQUIRED_ITEM_KEYS = ('surface_form', 'excerpt', 'proposed_kind')
OPTIONAL_ITEM_KEYS = ('proposed_class', 'suggested_seed_term_id')

REPLY_SCHEMA: Mapping[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['items'],
    'properties': {
        'items': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': list(REQUIRED_ITEM_KEYS),
                'properties': {
                    'surface_form': {'type': 'string', 'minLength': 1},
                    'excerpt': {'type': 'string', 'minLength': 1},
                    'proposed_kind': {'type': 'string', 'enum': list(PROPOSED_KINDS)},
                    'proposed_class': {'type': 'string', 'minLength': 1},
                    'suggested_seed_term_id': {'type': 'string', 'minLength': 1},
                },
            },
        }
    },
}


@dataclass(frozen=True)
class Reply:
    """A parsed reply: `outcome` names a call-level failure, or is None and `items` holds the reply's items."""

    outcome: str | None
    items: list[dict[str, str]] = field(default_factory=list)


def empty_outcomes() -> dict[str, int]:
    """A zero count for every outcome, in the proposal schema's order."""
    return {outcome: 0 for outcome in OUTCOMES}


def response_format() -> dict[str, Any]:
    """The `response_format` sent with every call."""
    return {'type': 'json_schema', 'json_schema': {'name': 'ontology_induction_items', 'schema': REPLY_SCHEMA}}


def completion_failure(response: Any) -> str | None:
    """A short code for a completion that is an API error rather than a reply, or None for a reply.

    The code never carries upstream message text: `api_error` for a mapping with `error`,
    `api_error_status_<n>` for a response object with an integer `status_code`, otherwise
    `unexpected_response_<type name>`.
    """
    if not isinstance(response, Mapping):
        status = getattr(response, 'status_code', None)
        if isinstance(status, int) and not isinstance(status, bool):
            return f'api_error_status_{status}'
        return f'unexpected_response_{type(response).__name__}'
    if response.get('error'):
        return 'api_error'
    return None


def _valid_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    keys = set(item)
    if not set(REQUIRED_ITEM_KEYS) <= keys or not keys <= set(REQUIRED_ITEM_KEYS + OPTIONAL_ITEM_KEYS):
        return False
    if not all(isinstance(value, str) and value for value in item.values()):
        return False
    return item['proposed_kind'] in PROPOSED_KINDS


def read_reply(response: Mapping[str, Any]) -> Reply:
    """Parse a completion against `REPLY_SCHEMA` without repairing it.

    No choice, or a message whose content is empty or absent, is `empty_completion`, including a
    reply that carries only reasoning. Content that is not JSON is `unparseable`. JSON that does
    not match the schema is `schema_violation`.
    """
    choices = response.get('choices')
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get('message') if isinstance(first, Mapping) else None
    content = message.get('content') if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        return Reply('empty_completion')
    try:
        parsed = json.loads(content)
    except ValueError:
        return Reply('unparseable')
    if not isinstance(parsed, dict) or set(parsed) != {'items'} or not isinstance(parsed['items'], list):
        return Reply('schema_violation')
    if not all(_valid_item(item) for item in parsed['items']):
        return Reply('schema_violation')
    return Reply(None, [dict(item) for item in parsed['items']])


def collapse_whitespace(text: str) -> str:
    """Runs of whitespace replaced by one space, ends stripped."""
    return ' '.join(text.split())


def item_outcome(item: Mapping[str, str], chunk_text: str, normalize: Callable[[str], str], index: SeedIndex) -> str:
    """The first guard an item fails, in the order (a), (b), (c), or `accepted`.

    (a) `excerpt_not_in_chunk`: the excerpt does not occur in the chunk after whitespace collapsing.
    (b) `term_not_in_excerpt`: the normalised surface form is not a contiguous run of whole tokens
    of the normalised excerpt.
    (c) `unknown_seed_term`: `suggested_seed_term_id` is not a seed term, or `proposed_class` is not
    a seed class term.
    """
    if collapse_whitespace(item['excerpt']) not in collapse_whitespace(chunk_text):
        return 'excerpt_not_in_chunk'
    form = normalize(item['surface_form'])
    if not form or f' {form} ' not in f' {normalize(item["excerpt"])} ':
        return 'term_not_in_excerpt'
    suggested = item.get('suggested_seed_term_id')
    if suggested is not None and suggested not in index.term_ids:
        return 'unknown_seed_term'
    proposed_class = item.get('proposed_class')
    if proposed_class is not None and proposed_class not in index.class_term_ids:
        return 'unknown_seed_term'
    return 'accepted'
