"""An empty owner response is not a rejected answer, and the run should say so.

Run `6056e157` lost 35 cells at the owner contract. The three failure modes
divide 24 / 10 / 1:

  - 24 cells to an owner that returned **zero characters**. `KB-GRR-FACTORS`
    returned nothing three times in a row and spent three specialist calls
    doing it; `KB-RESOURCE-TECH` chunk 4/6 went 0 -> 10,851 -> 0.
  - 10 cells to output that was written at length and contained no envelope.
    `KB-GEO` wrote 8,929 then 4,706 then 4,445 characters with no candidate in
    any of them, and nothing was recorded about what it did contain.
  - 1 cell to an actual schema violation.

All three were reported identically: "the owner response did not satisfy the
deterministic field contract", which was true of the third only. These tests
pin the three things that had to change.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from open_webui.services.artifacts.geotizer.observability import owner_attempt_diagnostic
from open_webui.services.artifacts.geotizer.workflow import (
    MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES,
    MAX_OWNER_ATTEMPTS,
    _produce_valid_owner_envelope,
)
from open_webui.services.artifacts.geotizer.owner_envelope import build_batch_tasks

from test_geotizer_orchestration import batch, envelope


def _run(agent_call, *, value=None):
    value = value if value is not None else batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    return asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-empty-response',
            agent_call=agent_call,
            datacube=None,
        )
    )


def _locator(result):
    return result['patches'][0]['source_locator']


def test_a_run_of_empty_responses_stops_instead_of_spending_a_third_call():
    """`KB-GRR-FACTORS` proved an empty prompt-and-answer pair repeats.

    There is no output to quote back, so attempt N+1 is sent the prompt that
    already produced nothing. The third call cost a full specialist round and
    returned zero characters, exactly like the two before it.
    """
    calls = 0

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal calls
        calls += 1
        return ''

    result = _run(agent_call)

    assert calls == MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES
    assert calls < MAX_OWNER_ATTEMPTS
    assert _locator(result)['attempts'] == calls


def test_one_empty_response_does_not_stop_the_loop():
    """The reason the threshold is two and not one.

    `KB-RESOURCE-TECH` chunk 4/6 went 0 -> 10,851 -> 0. Stopping after the
    first empty response would have discarded the only attempt that produced
    an envelope, and with it the 21 cells salvage took out of it.
    """
    outputs = ['', json.dumps(envelope(), ensure_ascii=False)]
    calls = 0

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal calls
        calls += 1
        return outputs[calls - 1]

    result = _run(agent_call)

    assert calls == 2
    assert result['patches'] == envelope()['patches']


def test_a_non_empty_attempt_resets_the_run():
    """Empty, output, empty is two isolated failures and not a run of two.

    At `MAX_OWNER_ATTEMPTS = 3` the reset saves no call -- the second empty
    lands on the last attempt either way -- so what it changes here is the
    count the card reports, and that count is the whole point of the record:
    "2 in a row" says the specialist has stopped answering, "1 in a row" says
    it answered in between. The saved call appears the moment the ceiling
    rises, and this test is what keeps the reset from being deleted as dead
    code before then.
    """
    outputs = ['', 'prose with no envelope in it', '']
    calls = 0

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal calls
        calls += 1
        return outputs[calls - 1]

    result = _run(agent_call)

    assert calls == MAX_OWNER_ATTEMPTS
    assert _locator(result)['attempts'] == MAX_OWNER_ATTEMPTS
    recorded = _locator(result)['owner_attempt_feedback']
    assert '(1 in a row)' in recorded[0]['violations'][0]
    assert '(1 in a row)' in recorded[2]['violations'][0]


def test_the_card_names_the_empty_mode_rather_than_blaming_the_contract():
    """The contract was never reached, so reporting it as the cause sends the
    reader to the wrong place. Rerunning is plausible after an empty response
    and pointless after a violation that will repeat."""

    async def agent_call(task, prompt, object_name, datacube):
        return ''

    note = _run(agent_call)['patches'][0]['retrieval_note']

    assert 'no output at all' in note
    assert 'specialist-call failure' in note
    assert 'did not satisfy the deterministic field contract' not in note


def test_the_card_names_the_unparseable_mode_separately():
    """Written at length, no envelope. Distinct from empty and from a
    violation, and the only one of the three whose remedy is to read the text."""

    async def agent_call(task, prompt, object_name, datacube):
        return 'The licence area is described in the 2019 report, section 4.'

    note = _run(agent_call)['patches'][0]['retrieval_note']

    assert 'usable envelope' in note
    assert 'text_prefix' in note
    assert 'did not satisfy the deterministic field contract' not in note


def test_every_attempt_reaches_the_feedback_record():
    """The record `owner_failure_envelope` exists to keep, and did not.

    `feedback_by_attempt` was appended only at the foot of the loop, so an
    attempt that never produced an envelope contributed nothing. On
    `6056e157` that left `owner_attempt_feedback` empty for `KB-GEO` and
    `KB-GRR-FACTORS` -- 20 of the 35 lost cells, and the two chunks whose
    failure was hardest to read.
    """
    outputs = ['', 'prose with no envelope', 'more prose with no envelope']
    calls = 0

    async def agent_call(task, prompt, object_name, datacube):
        nonlocal calls
        calls += 1
        return outputs[calls - 1]

    recorded = _locator(_run(agent_call))['owner_attempt_feedback']

    assert [item['attempt'] for item in recorded] == [1, 2, 3]
    assert all(item['violations'] for item in recorded)


@pytest.mark.parametrize(
    ('text', 'mode', 'keeps_prefix'),
    [
        ('', 'empty', False),
        ('   \n\t ', 'empty', False),
        ('prose with no envelope', 'unparseable', True),
        (json.dumps({'patches': [], 'source_inventory': []}), 'parsed', False),
    ],
)
def test_the_diagnostic_classifies_and_keeps_a_prefix_only_when_unparseable(text, mode, keeps_prefix):
    """Whitespace is empty, not unparseable: there is nothing in it to read.

    The prefix is kept for the unparseable case alone. A parsed response's
    content is already in the card cell by cell; an unparseable one exists
    nowhere else, and `KB-GEO`'s three attempts were otherwise
    indistinguishable from each other and from any other prose.
    """
    diagnostic = owner_attempt_diagnostic(text, attempt=1)

    assert diagnostic['response_mode'] == mode
    assert ('text_prefix' in diagnostic) is keeps_prefix


def test_the_kept_prefix_is_bounded():
    """It lands in `state.json`, which is downloadable."""
    diagnostic = owner_attempt_diagnostic('и' * 5000, attempt=1)

    assert len(diagnostic['text_prefix']) == 500
    assert diagnostic['character_count'] == 5000


def _owner_request(*, evidence_chars: int) -> str:
    return json.dumps(
        {
            'operation': 'geotizer_owner_decision',
            'attempt': 1,
            'context': {
                'object_name': 'Лекын-Талбейская площадь',
                'batch': {'batch_id': 'KB-GRR-FACTORS'},
                'contributor_evidence': [{'output': 'и' * evidence_chars}],
            },
            'rules': ['Return one JSON object only.'],
            'output_contract': {'patches': []},
        },
        ensure_ascii=False,
        indent=2,
    )


def test_an_empty_attempt_records_what_was_sent_to_produce_it():
    """Four runs stopped `KB-GRR-FACTORS` 1/3 on two empty responses, and the
    record said nothing about the request. A cause cannot be chosen between
    "too large" and "not large at all" without the number."""
    request = _owner_request(evidence_chars=40_000)
    diagnostic = owner_attempt_diagnostic('', attempt=1, request=request)

    assert diagnostic['response_mode'] == 'empty'
    assert diagnostic['request']['characters'] == len(request)
    assert diagnostic['request']['tokens_estimate'] == len(request) // 3
    roles = diagnostic['request']['characters_by_role']
    assert roles['evidence'] > roles['instruction']
    assert roles['other'] == 0, 'a prompt section nobody classified must be visible as unclassified'
    assert diagnostic['request']['largest_sections'][0]['section'] == 'context.contributor_evidence'


def test_an_answered_attempt_records_the_size_and_not_the_breakdown():
    """The breakdown is for diagnosing a response that does not exist. An
    attempt that answered is diagnosable from its answer, and `state.json` is
    written once per attempt per batch."""
    diagnostic = owner_attempt_diagnostic(
        json.dumps({'patches': [], 'source_inventory': []}),
        attempt=1,
        request=_owner_request(evidence_chars=10),
    )

    assert set(diagnostic['request']) == {'characters', 'tokens_estimate'}


def test_an_unclassified_prompt_section_is_counted_as_unclassified():
    """Folding a new key into evidence or instruction would move the number
    this diagnostic exists to report without anyone deciding to."""
    request = json.dumps({'rules': ['a'], 'a_section_added_later': 'x' * 100}, ensure_ascii=False)
    diagnostic = owner_attempt_diagnostic('', attempt=1, request=request)

    assert diagnostic['request']['characters_by_role']['other'] >= 100
