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
"""

from __future__ import annotations

import pytest

from open_webui.utils.context_window import (
    NARROW_THE_INPUT_RU,
    PROVIDER_FAILURE_TYPES,
    classify_provider_failure,
    context_window_overflow,
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


# -- the classification, not only the detector -------------------------------
#
# The detector was the easy half. The branch that decides which of six names a
# failure gets is the half that was wrong, and it used to live inline in
# `events.py` — which imports `open_webui.env`, which imports `cryptography`.
# Nothing could reach it without standing up the application, so nothing did.


def test_the_reported_400_is_classified_by_its_cause_and_not_by_its_status():
    """The failure this task is about, through the function that names it."""
    error_type, overflow = classify_provider_failure(
        status=400, marker=REPORTED.lower()
    )

    assert error_type == 'context_window_exceeded'
    assert overflow['overflow']['prompt_tokens'] == 117233


def test_an_overflow_returned_as_a_500_is_still_an_overflow():
    """`server_failed` would send the caller to wait for a server that is fine.
    No provider gives this its own status, so the status cannot be the test."""
    error_type, _ = classify_provider_failure(
        status=500, marker='maximum context length is 150000 tokens'
    )

    assert error_type == 'context_window_exceeded'


@pytest.mark.parametrize('status,marker,expected', [
    (404, 'the model `gpt-5` does not exist', 'model_not_found'),
    (401, 'invalid api key', 'authentication_failed'),
    (403, 'forbidden', 'authentication_failed'),
    (429, 'rate limit reached', 'rate_limited'),
    (500, 'internal server error', 'server_failed'),
    (502, 'bad gateway', 'server_failed'),
    (400, 'malformed request body', 'upstream_error'),
])
def test_every_name_that_existed_before_still_means_what_it_meant(
    status, marker, expected
):
    """The five other answers are read outside this repository. A new branch
    that quietly reclassifies one of them is a worse defect than the gap it
    closes — and inserting a branch into a six-way conditional is exactly how
    that happens."""
    error_type, _ = classify_provider_failure(status=status, marker=marker)

    assert error_type == expected


def test_authentication_beats_an_overflow_in_the_same_message():
    """A 401 whose body happens to mention context length is a 401. The caller
    cannot narrow their way past a rejected key, and telling them to try would
    cost them the rounds this task exists to save."""
    error_type, _ = classify_provider_failure(
        status=401, marker='invalid key; maximum context length is 150000 tokens'
    )

    assert error_type == 'authentication_failed'


def test_a_rate_limit_that_mentions_tokens_is_still_a_rate_limit():
    """«too many tokens» appears in both vocabularies, and only one of them is
    worth waiting out. Getting this backwards marks a retryable failure
    permanent and stops a run that a pause would have fixed."""
    error_type, _ = classify_provider_failure(
        status=429, marker='rate limit: too many tokens per minute'
    )

    assert error_type == 'rate_limited'


def test_every_name_the_classifier_can_return_is_published():
    """A value returned and not listed is a value no reader can enumerate, and
    the list is what a consumer switches on."""
    seen = {
        classify_provider_failure(status=status, marker=marker)[0]
        for status, marker in (
            (404, 'does not exist'), (401, 'x'), (429, 'x'),
            (400, 'context_length_exceeded'), (500, 'x'), (400, 'x'),
        )
    }

    assert seen == set(PROVIDER_FAILURE_TYPES)
