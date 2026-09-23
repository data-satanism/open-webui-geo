"""Tests for the bounded repair prompt: the failed draft is cut to the patches
the violations name, and the violations are grouped to one entry per
distinct rule."""

from __future__ import annotations

import asyncio
import json

from open_webui.services.artifacts.geotizer.owner_envelope import (
    PREVIOUS_OUTPUT_CAP,
    bounded_previous_output,
    build_batch_tasks,
    grouped_repair_feedback,
)
from open_webui.services.artifacts.geotizer.prompts import _owner_prompt
from open_webui.services.artifacts.geotizer.workflow import _produce_valid_owner_envelope

RULES = (
    'resource field requires entity_id: set source_locator.entity_id to the '
    'identifier of the analogue_deposit this value belongs to',
    "resource entity_scope must be analogue_deposit; got '(unset)'",
    "resource estimate_state is incompatible with row 54; allowed: ['analogue'], got '(unset)'",
    "analogue relation is incompatible with row 54; required: 'same_structure', got '(unset)'",
)


def _draft(count=18):
    return json.dumps(
        {
            'patches': [
                {
                    'field_key': f'geotizer_object.v1.r054.a{index:02d}',
                    'status': 'filled',
                    'value': '1200000',
                    'unit': 'т',
                    'source_locator': {'page': 12},
                    'retrieval_note': 'Ресурсы по аналогии с соседним месторождением.',
                }
                for index in range(count)
            ],
            'source_inventory': [
                {'source_id': f's{n}', 'source_type': 'knowledge_base', 'title': f'Документ {n}'}
                for n in range(1, 9)
            ],
        },
        ensure_ascii=False,
    )


def _violations(indices):
    return [
        f'patches[{index}] geotizer_object.v1.r054.a{index:02d} {rule}'
        for index in indices
        for rule in RULES
    ]


def test_only_the_patches_the_violations_name_are_sent_back():
    result = bounded_previous_output(_draft(), _violations([6, 7]))

    assert [item['index'] for item in result['patches_named_by_feedback']] == [6, 7]
    assert 'a06' in json.dumps(result, ensure_ascii=False)
    assert 'a12' not in json.dumps(result, ensure_ascii=False)


def test_the_note_forbids_returning_only_the_patches_shown():
    """The note tells the owner to return the complete patch array, not only
    the patches shown."""
    result = bounded_previous_output(_draft(), _violations([6]))

    assert 'complete array' in result['note']
    assert 'not only these' in result['note']
    assert 'whether or not it is shown here' in result['note']


def test_the_note_says_how_much_was_dropped():
    """The note states how many patches were shown, out of how many, and the
    draft's length."""
    draft = _draft()
    result = bounded_previous_output(draft, _violations([6]))

    assert '1 of the 1 patches' in result['note']
    assert 'out of 18' in result['note']
    assert str(len(draft)) in result['note']


def test_a_violation_about_the_array_as_a_whole_falls_back_to_a_cap():
    """A violation naming no patch falls back to a character cap."""
    result = bounded_previous_output(_draft(), ['patch count: expected 18, got 17'])

    assert isinstance(result, str)
    assert 'characters omitted' in result


def test_the_cap_keeps_both_ends():
    """The character cap keeps both the head and the tail of the draft."""
    draft = _draft(60)
    result = bounded_previous_output(draft, ['patch count: expected 60, got 59'])

    assert len(result) < len(draft)
    assert result.startswith(draft[:100])
    assert result.endswith(draft[-100:])


def test_a_draft_within_the_cap_is_untouched():
    assert bounded_previous_output('{"patches": []}', ['patch count: x']) == '{"patches": []}'


def test_an_unparseable_draft_falls_back_to_the_cap():
    """An unparseable draft falls back to the character cap."""
    result = bounded_previous_output('prose, no envelope, ' * 400, _violations([6]))

    assert isinstance(result, str)
    assert len(result) <= PREVIOUS_OUTPUT_CAP + 80


def test_forty_eight_violations_collapse_to_the_rules_behind_them():
    violations = _violations(range(6, 18))
    grouped = grouped_repair_feedback(violations)

    assert len(violations) == 48
    assert len(grouped) == len(RULES)
    assert len(json.dumps(grouped, ensure_ascii=False)) < len(
        json.dumps(violations, ensure_ascii=False)
    ) // 4


def test_a_group_names_every_patch_it_covers():
    """Each group names every patch it covers."""
    grouped = grouped_repair_feedback(_violations(range(6, 18)))

    assert all(item['patches'] == list(range(6, 18)) for item in grouped)


def test_rules_that_differ_stay_separate():
    """Rules that differ only in a row number stay separate groups."""
    grouped = grouped_repair_feedback(
        [
            "patches[6] k1 estimate_state is incompatible with row 54; allowed: ['analogue']",
            "patches[7] k2 estimate_state is incompatible with row 55; allowed: ['analogue']",
        ]
    )

    assert len(grouped) == 2


def test_a_feedback_list_that_does_not_collapse_keeps_its_shape():
    """A feedback list with nothing to collapse is returned unchanged."""
    violations = ['patches[3] k3 not_found must use value=null']

    assert grouped_repair_feedback(violations) == violations


def test_a_violation_naming_no_patch_survives_grouping():
    grouped = grouped_repair_feedback(
        ['patch count: expected 18, got 17', 'patches[3] k3 not_found must use value=null']
    )

    assert 'patch count: expected 18, got 17' in grouped


def _second_attempt_prompt():
    """Return the repair prompt and the first prompt the retry loop built,
    parsed from JSON."""
    value = {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {'field_key': f'geotizer_object.v1.r054.a{index:02d}', 'row_id': 54}
            for index in range(18)
        ],
    }
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')
    seen = []

    async def agent_call(task, prompt, object_name, datacube):
        seen.append(prompt)
        return _draft()

    asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын',
            run_id='run-repair-bounds',
            agent_call=agent_call,
            datacube=None,
        )
    )
    assert len(seen) > 1, 'the loop did not retry, so no repair prompt was built'
    return json.loads(seen[1]), json.loads(seen[0])


def test_the_loop_sends_a_bounded_draft_and_not_the_whole_one():
    repair, first = _second_attempt_prompt()

    assert isinstance(repair['previous_output'], dict)
    assert 'patches_named_by_feedback' in repair['previous_output']
    assert len(json.dumps(repair['previous_output'], ensure_ascii=False)) < len(_draft())
    assert 'previous_output' not in first


def test_a_chunk_where_every_patch_is_wrong_is_still_bounded():
    """A draft whose every patch is named is still bounded, by dropping whole
    patches."""
    draft = _draft()
    result = bounded_previous_output(draft, _violations(range(18)))

    assert len(json.dumps(result, ensure_ascii=False)) < len(draft)
    assert len(result['patches_named_by_feedback']) < 18
    assert 'whether or not it is shown here' in result['note']
    assert all(set(item) == {'index', 'patch'} for item in result['patches_named_by_feedback'])


def test_the_loop_sends_grouped_feedback():
    repair, _ = _second_attempt_prompt()
    feedback = repair['repair_feedback']

    assert any(isinstance(item, dict) and 'patches' in item for item in feedback), feedback


def test_the_repair_payload_is_smaller_than_the_draft_that_produced_it():
    """The repair payload, draft and feedback together, is smaller than the
    draft."""
    repair, _ = _second_attempt_prompt()

    payload = len(json.dumps(repair['previous_output'], ensure_ascii=False)) + len(
        json.dumps(repair['repair_feedback'], ensure_ascii=False)
    )

    assert payload < len(_draft()), payload


def test_the_repair_keys_come_last_so_the_prefix_is_shared():
    """`repair_feedback` and `previous_output` are the last two keys of a
    repair prompt."""
    context = {'batch': {'batch_id': 'B', 'producer': 'kb', 'policy_version': 'p',
                         'template_version': 't', 'fields': [{'field_key': 'f1', 'row_id': 1}]}}
    keys = list(json.loads(
        _owner_prompt(context=context, attempt=2, feedback=['patches[0] f1 bad'], previous_output='x')
    ))

    assert keys[-2:] == ['repair_feedback', 'previous_output']


def test_the_first_attempt_carries_neither_key():
    context = {'batch': {'batch_id': 'B', 'producer': 'kb', 'policy_version': 'p',
                         'template_version': 't', 'fields': [{'field_key': 'f1', 'row_id': 1}]}}
    prompt = json.loads(_owner_prompt(context=context, attempt=1, feedback=None, previous_output=''))

    assert 'repair_feedback' not in prompt
    assert 'previous_output' not in prompt
