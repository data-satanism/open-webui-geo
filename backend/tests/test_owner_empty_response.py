"""An empty or unparseable owner response is reported as such, not as a field-contract violation."""

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
    """Consecutive empty owner responses stop the loop after `MAX_CONSECUTIVE_EMPTY_OWNER_RESPONSES` calls."""
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
    """A single empty response is followed by another attempt."""
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
    """A non-empty attempt between two empty ones resets the consecutive-empty count to one."""
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
    """An empty-response failure is reported as a specialist-call failure, not a field-contract failure."""

    async def agent_call(task, prompt, object_name, datacube):
        return ''

    note = _run(agent_call)['patches'][0]['retrieval_note']

    assert 'no output at all' in note
    assert 'specialist-call failure' in note
    assert 'did not satisfy the deterministic field contract' not in note


def test_the_card_names_the_unparseable_mode_separately():
    """An unparseable response is reported as having no usable envelope and cites its text prefix."""

    async def agent_call(task, prompt, object_name, datacube):
        return 'The licence area is described in the 2019 report, section 4.'

    note = _run(agent_call)['patches'][0]['retrieval_note']

    assert 'usable envelope' in note
    assert 'text_prefix' in note
    assert 'did not satisfy the deterministic field contract' not in note


def test_every_attempt_reaches_the_feedback_record():
    """Every attempt, including one that produced no envelope, appears in `owner_attempt_feedback`."""
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
    """Whitespace classifies as empty, and a text prefix is kept only for an unparseable response."""
    diagnostic = owner_attempt_diagnostic(text, attempt=1)

    assert diagnostic['response_mode'] == mode
    assert ('text_prefix' in diagnostic) is keeps_prefix


def test_the_kept_prefix_is_bounded():
    """The kept text prefix is bounded to 500 characters while the full character count is recorded."""
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
    """An empty attempt's diagnostic records the request's size, per-role breakdown and largest sections."""
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
    """An answered attempt's diagnostic records only the request's character count and token estimate."""
    diagnostic = owner_attempt_diagnostic(
        json.dumps({'patches': [], 'source_inventory': []}),
        attempt=1,
        request=_owner_request(evidence_chars=10),
    )

    assert set(diagnostic['request']) == {'characters', 'tokens_estimate'}


def test_an_unclassified_prompt_section_is_counted_as_unclassified():
    """A prompt section with no assigned role is counted under `other`."""
    request = json.dumps({'rules': ['a'], 'a_section_added_later': 'x' * 100}, ensure_ascii=False)
    diagnostic = owner_attempt_diagnostic('', attempt=1, request=request)

    assert diagnostic['request']['characters_by_role']['other'] >= 100
