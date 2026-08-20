"""The repair prompt, bounded — the largest lost-cell mode on run `6056e157`.

Attempt 3 of `KB-RESOURCE-TECH 4/6` carried all 10,851 characters of attempt 2
plus 48 violations, and returned nothing. Empty responses were 24 of that run's
35 lost cells, and the chunks that went empty are the ones whose earlier
attempts were largest. A model handed its own failed draft and 48 things to fix
in it is being asked to do something harder than the task it just failed.

Two halves, and they only work together:

  - the draft is cut to the patches the violations name, which is possible
    because every violation carries `patches[N]` and the semantic ones carry
    the `field_key`
  - the violations are grouped to one entry per distinct rule

The second half is not an optimisation. Quoting each rule's contract into its
text -- the change that made a resource rejection actionable -- grew that
chunk's feedback from 2,852 to roughly 7,644 characters. Landing that without
this would have made the empty-response mode more likely, not less.
"""

from __future__ import annotations

import asyncio
import json

import pytest
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
    """A repair that returns 2 of 18 patches trades one violation for
    `patch count: expected 18, got 2`."""
    result = bounded_previous_output(_draft(), _violations([6]))

    assert 'complete array' in result['note']
    assert 'not only these' in result['note']
    assert 'whether or not it is shown here' in result['note']


def test_the_note_says_how_much_was_dropped():
    """A silent truncation reads as the whole draft, and a model that needs
    the omitted part should be able to say so rather than invent it."""
    draft = _draft()
    result = bounded_previous_output(draft, _violations([6]))

    assert '1 of the 1 patches' in result['note']
    assert 'out of 18' in result['note']
    assert str(len(draft)) in result['note']


def test_a_violation_about_the_array_as_a_whole_falls_back_to_a_cap():
    """`patch count` and `missing field_key values` name no patch, so there is
    no offending patch to show and the draft is all there is."""
    result = bounded_previous_output(_draft(), ['patch count: expected 18, got 17'])

    assert isinstance(result, str)
    assert 'characters omitted' in result


def test_the_cap_keeps_both_ends():
    """The head carries the envelope's shape and the tail carries whatever the
    model was writing when it ran long. A single truncation keeps only one."""
    draft = _draft(60)
    result = bounded_previous_output(draft, ['patch count: expected 60, got 59'])

    assert len(result) < len(draft)
    assert result.startswith(draft[:100])
    assert result.endswith(draft[-100:])


def test_a_draft_within_the_cap_is_untouched():
    assert bounded_previous_output('{"patches": []}', ['patch count: x']) == '{"patches": []}'


def test_an_unparseable_draft_falls_back_to_the_cap():
    """`KB-GEO` wrote 8,929 characters with no candidate in them. There is no
    patch array to select from."""
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
    """Collapsing must not lose which patches to fix."""
    grouped = grouped_repair_feedback(_violations(range(6, 18)))

    assert all(item['patches'] == list(range(6, 18)) for item in grouped)


def test_rules_that_differ_stay_separate():
    """`row 54` and `row 55` are different instructions, and the difference is
    the part the owner has to act on."""
    grouped = grouped_repair_feedback(
        [
            "patches[6] k1 estimate_state is incompatible with row 54; allowed: ['analogue']",
            "patches[7] k2 estimate_state is incompatible with row 55; allowed: ['analogue']",
        ]
    )

    assert len(grouped) == 2


def test_a_feedback_list_that_does_not_collapse_keeps_its_shape():
    """One-element groups are harder to read than the plain strings, and an
    unchanged shape is one less thing to parse differently between attempts."""
    violations = ['patches[3] k3 not_found must use value=null']

    assert grouped_repair_feedback(violations) == violations


def test_a_violation_naming_no_patch_survives_grouping():
    grouped = grouped_repair_feedback(
        ['patch count: expected 18, got 17', 'patches[3] k3 not_found must use value=null']
    )

    assert 'patch count: expected 18, got 17' in grouped


def _second_attempt_prompt():
    """The prompt the retry loop actually builds, captured on attempt 2.

    Asserting on the helpers proves only that the helpers work. Both were
    verified in isolation and neither was wired in by the first version of
    this file: replacing `bounded_previous_output(...)` with the raw draft, and
    `grouped_repair_feedback(...)` with the ungrouped list, each left every
    test above green. That is the third time this pattern has appeared, so the
    wiring gets its own assertions -- against the loop, since the bounding
    happens there and not in the prompt builder.
    """
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
    """The case selection alone cannot help, and the one that lost 12 cells.

    `KB-RESOURCE-TECH 4/6` returned 48 violations over twelve of eighteen
    patches. When the offending subset is most of the draft, sending "only the
    offending patches" sends the draft. Whole patches are dropped instead of
    characters, so what survives is still JSON the owner can read.
    """
    draft = _draft()
    result = bounded_previous_output(draft, _violations(range(18)))

    assert len(json.dumps(result, ensure_ascii=False)) < len(draft)
    assert len(result['patches_named_by_feedback']) < 18
    assert 'whether or not it is shown here' in result['note']
    # every kept entry is a whole patch, not a truncated one
    assert all(set(item) == {'index', 'patch'} for item in result['patches_named_by_feedback'])


def test_the_loop_sends_grouped_feedback():
    repair, _ = _second_attempt_prompt()
    feedback = repair['repair_feedback']

    assert any(isinstance(item, dict) and 'patches' in item for item in feedback), feedback


def test_the_repair_payload_is_smaller_than_the_draft_that_produced_it():
    """The whole point, measured on the prompt the loop built.

    `KB-RESOURCE-TECH 4/6` sent 10,851 characters of draft plus 48 violations
    and got nothing back. The repair payload is now a fraction of the draft it
    repairs, and the comparison includes the contract text that grew the
    feedback in the first place.
    """
    repair, _ = _second_attempt_prompt()

    payload = len(json.dumps(repair['previous_output'], ensure_ascii=False)) + len(
        json.dumps(repair['repair_feedback'], ensure_ascii=False)
    )

    assert payload < len(_draft()), payload


def test_the_repair_keys_come_last_so_the_prefix_is_shared():
    """A repair attempt must share its whole prefix with the attempt it
    repairs; a cache that misses on attempt two pays for the whole prompt
    again."""
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
