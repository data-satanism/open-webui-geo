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

Its own module, under the fork-owned `utils/geotizer` prefix. `events.py` is
upstream's file and `publish_model_provider_request_failed` is upstream's
function: the fork briefly classified there, which put a diff on a tracked
upstream file for a benefit the geotizer pipeline does not take. The pipeline
reads its own failure envelope, not that admin event.

It imports nothing of its own — but that does not make it free to import.
`open_webui/__init__.py` pulls `typer` and `uvicorn` on any submodule import,
so «importing nothing» would be a claim about this file mistaken for a claim
about reaching it. What is actually avoided is `events.py`'s chain through
`open_webui.env` into `cryptography`, which crashes rather than merely
requiring a dependency, and that is the difference between a rule that can be
exercised and one that cannot.
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
#: Two plausible markers are deliberately absent. «too many tokens» is Azure's
#: RATE-LIMIT wording («Too many tokens, please retry after N seconds»), and
#: «exceeds the maximum» matches a file-size refusal as readily as a context
#: one. Both would mark a retryable failure permanent, which is the more
#: expensive of the two mistakes: waiting fixes a rate limit, and nothing the
#: caller can do fixes a run this stopped by mistake.
CONTEXT_OVERFLOW_MARKERS = (
    'context_length_exceeded',
    'context window',
    'maximum context length',
    'context length',
    'reduce the length of the messages',
    'prompt is too long',
    'exceeds the model',
    # llama.cpp says «size» where OpenAI says «length», and the docstring above
    # claims to cover it. A claim about coverage that the tuple does not back
    # is the kind this project keeps finding in its own comments.
    'context size',
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


#: The code a context overflow gets, in place of the exception's class name.
CONTEXT_WINDOW_EXCEEDED = 'context_window_exceeded'


def geotizer_failure_code(exc: BaseException) -> tuple[str, dict[str, Any]]:
    """The failure's code and what to put beside it, for a run that could not finish.

    `fill_geotizer` reported `type(exc).__name__` and the provider's sentence:
    `APIError` над «This model's maximum context length is 150000 tokens» tells
    a reader which Python class was raised and nothing about what to do. The
    overflow gets its own code and its numbers; everything else keeps exactly
    the name it had, because the class name is genuinely the best available
    answer when nothing more specific is known.
    """
    overflow = context_window_overflow(f'{exc}')
    if overflow is None:
        return type(exc).__name__, {}
    return CONTEXT_WINDOW_EXCEEDED, overflow
