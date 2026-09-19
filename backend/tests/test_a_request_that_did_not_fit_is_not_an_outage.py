"""«upstream_error» was accurate about a context overflow and unactionable.

    This model's maximum context length is 150000 tokens. However, you
    requested 32768 output tokens and your prompt contains at least 117233
    input tokens, for a total of at least 150001 tokens.

A GIS round on `GIS_Data_RF` — 1 139 layers — sent that back as an HTTP 400,
and the classifier had no branch for it, so it fell to `upstream_error` with
the provider's English attached. A caller reading that cannot tell whether to
wait, to narrow the task, or to stop.

It is not weather. It is arithmetic: the same prompt over the same tool history
counts the same tokens, so it reproduces identically and `retryable: true` is a
false statement about it. The same argument separated `upstream_unavailable`
from `completion_failed`, and it applies here unchanged.

Two things follow, and both are tested below: the failure gets a code of its
own with the numbers the provider gave, and a specialist that reports
`retryable: false` stops being retried — the field was parsed and read by
nobody, so a deterministic failure bought a second round to fail identically.

The classification is NOT in `events.py`. That is upstream's file and
`publish_model_provider_request_failed` is upstream's function; a fork diff
there buys nothing the geotizer pipeline reads, and it publishes an event type
upstream does not have. The pipeline reads its own failure envelope, and that
is where this classifies.
"""

from __future__ import annotations

import pytest

from open_webui.utils.geotizer_context_window import (
    CONTEXT_WINDOW_EXCEEDED,
    NARROW_THE_INPUT_RU,
    context_window_overflow,
    geotizer_failure_code,
)

#: The message this task was reported with, verbatim.
REPORTED = (
    "This model's maximum context length is 150000 tokens. However, you "
    'requested 32768 output tokens and your prompt contains at least 117233 '
    'input tokens, for a total of at least 150001 tokens.'
)


def test_the_reported_message_yields_the_three_numbers_in_it():
    """The numbers, not the sentence. «Слишком длинный запрос» sends a reader
    nowhere; 117 233 of 150 000 says which side is full and roughly how far
    over."""
    answer = context_window_overflow(REPORTED)

    assert answer['overflow'] == {
        'window_tokens': 150000,
        'requested_tokens': 32768,
        'prompt_tokens': 117233,
    }
    assert answer['narrow'] == NARROW_THE_INPUT_RU


@pytest.mark.parametrize('message', [
    'context_length_exceeded',
    'This request would exceed the maximum context length for this model.',
    'prompt is too long: 205000 tokens > 200000 maximum',
    'Please reduce the length of the messages.',
    'THE CONTEXT WINDOW IS FULL',
    # llama.cpp says «size» where OpenAI says «length». The module docstring
    # claimed to cover this backend before the tuple did.
    'the request exceeds the available context size, try increasing rope_freq_base',
    'context size exceeded',
])
def test_the_spellings_providers_actually_use_are_recognised(message):
    """No provider gives this its own status code, so the message is the only
    signal there is. One vendor's wording is not the rule."""
    assert context_window_overflow(message) is not None


@pytest.mark.parametrize('message', [
    'Rate limit reached for gpt-4 in organization org-x',
    'The model `gpt-5` does not exist',
    'Internal server error',
    '',
])
def test_an_ordinary_failure_is_not_claimed_as_an_overflow(message):
    """A false positive here marks a retryable outage non-retryable and stops a
    run that waiting would have fixed. The two mistakes are not symmetric."""
    assert context_window_overflow(message) is None


def test_a_number_the_provider_did_not_give_is_absent_and_not_zero():
    """A zero-token window is a claim someone would act on. An absent key is
    «the provider did not say», which is what happened."""
    answer = context_window_overflow('context_length_exceeded')

    assert answer['overflow'] == {}
    assert 'window_tokens' not in answer['overflow']


def test_a_thousands_separator_does_not_halve_the_number():
    """`117,233` read as `117` is a number that looks fine and is wrong by
    three orders of magnitude — and it would read as a request comfortably
    inside the window it just overflowed."""
    answer = context_window_overflow(
        "maximum context length is 150,000 tokens ... prompt contains at least "
        '117,233 input tokens'
    )

    assert answer['overflow']['window_tokens'] == 150000
    assert answer['overflow']['prompt_tokens'] == 117233


def test_the_advice_states_that_a_retry_changes_nothing():
    """The one thing a caller must not do, said in the field they read."""
    assert 'тот же отказ' in NARROW_THE_INPUT_RU


def test_the_advice_names_no_number_from_the_other_repository():
    """`list_layers` defaults live in `gis_service`, which this repository
    cannot see. A count restated here is right until the day it silently is
    not, and nothing would compare them."""
    assert not any(character.isdigit() for character in NARROW_THE_INPUT_RU)


# -- and the wiring that calls it --------------------------------------------


@pytest.mark.parametrize('message,expected', [
    (REPORTED, CONTEXT_WINDOW_EXCEEDED),
    ('context_length_exceeded', CONTEXT_WINDOW_EXCEEDED),
    ('Connection reset by peer', 'RuntimeError'),
    ('', 'RuntimeError'),
])
def test_the_failure_code_is_the_cause_when_there_is_one_and_the_class_otherwise(
    message, expected
):
    """`APIError` над «maximum context length is 150000 tokens» names the Python
    class that was raised and nothing a reader can act on. Everything else keeps
    the class name, because when nothing more specific is known that is
    genuinely the best answer available."""
    code, _overflow = geotizer_failure_code(RuntimeError(message))

    assert code == expected


def test_the_numbers_travel_with_the_code():
    _code, overflow = geotizer_failure_code(RuntimeError(REPORTED))

    assert overflow['overflow']['prompt_tokens'] == 117233
    assert overflow['narrow'] == NARROW_THE_INPUT_RU


def test_an_ordinary_failure_carries_no_overflow_block():
    """The detector runs on every failure, so the block has to be withheld
    rather than merely unused: `details` is rendered, and «сократите вход»
    printed under a connection reset sends a reader to shrink a request that
    was never too big.
    """
    _code, overflow = geotizer_failure_code(RuntimeError('Connection reset by peer'))

    assert overflow == {}


@pytest.mark.parametrize('message', [
    'Too many tokens, please retry after 6 seconds',
    'Rate limit reached: too many tokens per minute',
    'The uploaded file exceeds the maximum size of 50MB',
])
def test_a_retryable_failure_is_not_marked_permanent_by_a_shared_word(message):
    """«too many tokens» is Azure's RATE-LIMIT wording and «exceeds the maximum»
    matches a file-size refusal. Both were in the marker list and both would
    have marked a retryable failure deterministic.

    The two mistakes are not symmetric. Missing an overflow costs one wasted
    round; claiming one costs a run that waiting would have fixed, and the
    caller is told to narrow a request that was the right size.
    """
    assert context_window_overflow(message) is None
