"""A request that did not fit, told apart from a server that did not answer.

    This model's maximum context length is 150000 tokens. However, you
    requested 32768 output tokens and your prompt contains at least 117233
    input tokens, for a total of at least 150001 tokens.

That arrived as an HTTP 400 and was classified `upstream_error` — accurate and
unactionable. A caller reading it cannot tell whether to wait, to narrow the
task, or to stop, and those are three different next steps.

It is not an outage. It is arithmetic: the same prompt over the same tool
history produces the same token count, so it reproduces identically and
`retryable: true` is a false statement about it. That is the same argument that
separated `upstream_unavailable` from `completion_failed` — a distinct cause
needs a distinct code, or every caller re-derives the distinction from prose.

Its own module, and importing nothing, because `open_webui.events` is expensive
to import and this is a pure function over a string. A rule that can only be
exercised by standing up the app is a rule nobody exercises.
"""

from __future__ import annotations

import re
from typing import Any

#: How a provider says the request did not fit.
#:
#: Matched on the message, because no provider gives this its own HTTP status:
#: OpenAI-compatible servers send 400 with `context_length_exceeded`, some send
#: 413, vLLM and llama.cpp write their own prose, and the contour this runs on
#: returned a plain 400 with the sentence above and no code field at all.
CONTEXT_OVERFLOW_MARKERS = (
    'context_length_exceeded',
    'context window',
    'maximum context length',
    'context length',
    'too many tokens',
    'reduce the length of the messages',
    'prompt is too long',
    'exceeds the maximum',
)

#: The numbers the provider's own sentence carries.
#:
#: Extracted, never re-derived. A count computed here would be this
#: repository's tokeniser guessing at the server's, and two numbers that
#: disagree about one request are worse than one number — the reader cannot
#: tell which to act on, and the wrong one sends them to narrow the wrong side.
_NUMBERS = re.compile(
    r'maximum context length is (?P<window>[\d,\s]+?) tokens'
    r'|you requested (?P<requested>[\d,\s]+?) output tokens'
    r'|prompt contains (?:at least )?(?P<prompt>[\d,\s]+?) input tokens'
)

#: What to do about it, in the words of the thing that can be done.
#:
#: Deliberately no layer count and no tool-specific default: those live in
#: `gis_service`, this repository cannot see them, and a number restated here
#: would be right until the day it silently was not.
NARROW_THE_INPUT_RU = (
    'Повтор с тем же входом даст тот же отказ — это арифметика, а не сбой '
    'сервера. Сократите вход: сузьте запрос к инструменту (по группе, слою '
    'или фильтру) либо сожмите историю результатов инструментов.'
)


def context_window_overflow(message: str) -> dict[str, Any] | None:
    """What the provider said about size, or None when it said nothing about it.

    Returns only the numbers that were actually in the message. An absent key
    means the provider did not say; a zero would be this function claiming it
    did, and a budget of zero tokens is a claim someone would act on.
    """
    marker = str(message or '').lower()
    if not any(value in marker for value in CONTEXT_OVERFLOW_MARKERS):
        return None
    found: dict[str, int] = {}
    for match in _NUMBERS.finditer(marker):
        for name, raw in match.groupdict().items():
            if raw is None:
                continue
            digits = raw.replace(',', '').replace(' ', '').replace(' ', '')
            if digits.isdigit():
                found[f'{name}_tokens'] = int(digits)
    return {'overflow': found, 'narrow': NARROW_THE_INPUT_RU}


#: The provider failures that already had names, and the one this adds.
#:
#: Values are unchanged from where this decision used to live inline in
#: `events.py`: they are read outside this repository, and a classification
#: that quietly renames its answers is a worse bug than the one it fixes.
PROVIDER_FAILURE_TYPES = (
    'model_not_found',
    'authentication_failed',
    'rate_limited',
    'context_window_exceeded',
    'server_failed',
    'upstream_error',
)

_MODEL_NOT_FOUND_MARKERS = (
    'model_not_found', 'model not found', 'does not exist', 'no such model',
)


def classify_provider_failure(
    *, status: int, marker: str
) -> tuple[str, dict[str, Any] | None]:
    """What kind of provider failure this is, and its size numbers if it has any.

    Pure, and here rather than inline in `events.py`, because `events.py`
    imports `open_webui.env`, which imports `cryptography` — a classification
    that can only be exercised by standing up the application is one nobody
    exercises, and the branch this adds is the branch most worth exercising.

    **The overflow check does not wait for `status >= 500` to be ruled out.** A
    provider that returns «maximum context length» as a 500 is still describing
    arithmetic, and `server_failed` would send the caller to wait for a server
    that is fine.
    """
    overflow = context_window_overflow(marker)
    if status == 404 and any(value in marker for value in _MODEL_NOT_FOUND_MARKERS):
        return 'model_not_found', overflow
    if status in (401, 403):
        return 'authentication_failed', overflow
    if status == 429:
        return 'rate_limited', overflow
    if overflow is not None:
        return 'context_window_exceeded', overflow
    if status >= 500:
        return 'server_failed', overflow
    return 'upstream_error', overflow
