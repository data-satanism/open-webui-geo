"""How a Workspace Model's system prompt combines with a caller-injected one.

Every GeoMAS specialist prompt depends on this and nothing covered it.

`fill_geoteaser` and Multitask Orchestration both build their own `messages`
list with a system message at index 0 carrying the per-call invocation note --
"you have no tools in this call", the direct tool-server prompts -- and then
call `generate_chat_completion` **without** `bypass_system_prompt`. The router
therefore also applies the Workspace Model's configured system prompt, and the
two are merged.

The merge must PREPEND the model prompt, leaving the caller's note last:

    <Workspace Model system prompt>      invariant, first
    <caller's per-call invocation note>  variant, last

That ordering is load-bearing twice over. The per-call note lands last, which
is the stronger position for a specific instruction. And the invariant content
lands first, which is what prefix caching needs -- the trap recorded as
"prompt key order defeats caching: invariant content first".

Four lines across three files decide it: the `append` default here, the branch
in `add_or_update_system_message`, the call in `apply_system_prompt_to_body`,
and the `bypass_system_prompt` guard in each router. Flip any one and every
specialist prompt changes meaning at once, silently.
"""

from __future__ import annotations

import inspect

import pytest

from open_webui.utils.misc import add_or_update_system_message, update_message_content
from open_webui.utils.payload import apply_system_prompt_to_body

MODEL_PROMPT = 'You are the Skilled Agent: a geology analyst who reasons and decides.'
CALLER_NOTE = 'You are making a bounded decision with no tools in this call.'


def caller_messages():
    """What Multitask and fill_geoteaser hand to generate_chat_completion."""
    return [
        {'role': 'system', 'content': CALLER_NOTE},
        {'role': 'user', 'content': 'Заполнить GeoTeaser для Лекын-Тальбейской площади'},
    ]


def test_model_prompt_is_prepended_not_substituted():
    messages = add_or_update_system_message(MODEL_PROMPT, caller_messages())

    assert messages[0]['content'] == f'{MODEL_PROMPT}\n{CALLER_NOTE}'


def test_caller_note_lands_last_and_model_prompt_first():
    messages = add_or_update_system_message(MODEL_PROMPT, caller_messages())
    system = messages[0]['content']

    assert system.index(MODEL_PROMPT) < system.index(CALLER_NOTE)


def test_no_second_system_message_is_created():
    messages = add_or_update_system_message(MODEL_PROMPT, caller_messages())

    assert [m['role'] for m in messages] == ['system', 'user']


def test_append_default_is_false():
    """The default decides the order. A change here inverts every prompt."""
    assert inspect.signature(add_or_update_system_message).parameters['append'].default is False
    assert update_message_content({'role': 'system', 'content': CALLER_NOTE}, MODEL_PROMPT, False)[
        'content'
    ].startswith(MODEL_PROMPT)


def test_system_message_is_inserted_when_the_caller_sent_none():
    messages = add_or_update_system_message(MODEL_PROMPT, [{'role': 'user', 'content': 'hello'}])

    assert messages[0] == {'role': 'system', 'content': MODEL_PROMPT}
    assert messages[1]['role'] == 'user'


@pytest.mark.parametrize('system', ['', None])
def test_absent_model_prompt_leaves_the_caller_note_intact(system):
    """A model with no configured prompt must not disturb the invocation note."""
    import asyncio

    form_data = {'messages': caller_messages()}
    result = asyncio.run(apply_system_prompt_to_body(system, form_data))

    assert result['messages'][0]['content'] == CALLER_NOTE


def test_apply_system_prompt_to_body_preserves_the_layering():
    """The full path the routers take, not just the merge helper."""
    import asyncio

    form_data = {'messages': caller_messages()}
    result = asyncio.run(apply_system_prompt_to_body(MODEL_PROMPT, form_data))

    assert result['messages'][0]['content'] == f'{MODEL_PROMPT}\n{CALLER_NOTE}'
    assert [m['role'] for m in result['messages']] == ['system', 'user']


def test_replace_mode_is_not_the_default():
    """`replace=True` drops the caller's note entirely; it must stay opt-in."""
    import asyncio

    form_data = {'messages': caller_messages()}
    result = asyncio.run(apply_system_prompt_to_body(MODEL_PROMPT, form_data, replace=True))

    assert CALLER_NOTE not in result['messages'][0]['content']
