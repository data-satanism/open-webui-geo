"""Nothing bounded a whole fill, and the thing that looked like it does not.

Five ceilings bound a fill today. A completion, a tool call and a specialist
each bound one unit of work; Open WebUI's request timeout bounds the caller's
patience, which is a different thing entirely. When the request timeout fires,
a tool call already running in the event loop is not cancelled, `gis_service`
is a separate process that never hears about it, and the user gets an error
with no state, no card and no artefacts. A fill makes around seventy-five
specialist calls inside one request.

So the case left open is the one where nothing individually times out and the
fill never ends: an unbounded setup path, a pathological batch plan, a loop
introduced later. This is the layer for that, and it exists to produce a
partial card rather than an exception.

The shape it had to take. «Finalize with what has been collected» is not
reachable by skipping batches: GIS refuses a finalize with any batch
outstanding -- `missing_owner_batches`, regardless of `allow_draft` -- so a run
that stopped submitting would produce exactly the nothing this layer exists to
prevent. What expiry stops is therefore the *calling*, not the submitting. Every
remaining batch is still closed, from the fallback envelope, with no specialist
and no owner call, and the run finalizes into a real card whose cells say they
were never requested.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from open_webui.services.core.deadline import FillDeadline
from open_webui.services.artifacts.geotizer.terminal import run_notes_section
from open_webui.services.artifacts.geotizer.workflow import (
    DEFAULT_FILL_DEADLINE_SECONDS,
    resolve_fill_deadline,
    run_geotizer_workflow,
)

from test_geotizer_orchestration import batch, envelope


# -- the clock ---------------------------------------------------------------


class _Clock:
    """A hand-cranked monotonic clock. Nothing here sleeps."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_an_unconfigured_deadline_never_expires():
    """Zero means no deadline, not a deadline of zero. A run that configured
    nothing must not stop before its first batch."""
    clock = _Clock()
    deadline = FillDeadline(0, now=clock)
    clock.advance(10_000_000)

    assert deadline.configured is False
    assert deadline.expired() is False


def test_a_deadline_expires_when_the_clock_passes_it():
    clock = _Clock()
    deadline = FillDeadline(100, now=clock)

    assert deadline.expired() is False
    clock.advance(99)
    assert deadline.expired() is False
    clock.advance(2)
    assert deadline.expired() is True


def test_the_clock_is_read_every_time_and_not_latched():
    """A deadline that sampled its answer at construction would report the one
    moment it is guaranteed not to have expired."""
    clock = _Clock()
    deadline = FillDeadline(10, now=clock)
    for _ in range(3):
        assert deadline.expired() is False
    clock.advance(11)

    assert deadline.expired() is True


# -- the value ---------------------------------------------------------------


def test_the_default_is_six_hours():
    assert DEFAULT_FILL_DEADLINE_SECONDS == 21600
    assert resolve_fill_deadline(None) == (21600.0, None)


def test_a_small_deadline_is_allowed_and_announced():
    """Deliberately unlike `resolve_owner_fields_per_call`, which refuses. A
    chunk size of 8 silently disables a validation rule; a short deadline has
    no such cliff and an operator capping a smoke test is using it correctly.
    It is announced because a card truncated by a lowered backstop and one
    truncated by a genuine hang are otherwise identical."""
    seconds, note = resolve_fill_deadline('600')

    assert seconds == 600.0
    assert note and '600' in note


def test_garbage_falls_back_and_says_so():
    seconds, note = resolve_fill_deadline('soon')

    assert seconds == float(DEFAULT_FILL_DEADLINE_SECONDS)
    assert note and 'not a number' in note


def test_a_negative_deadline_is_refused():
    """Not treated as zero. «No deadline» and «expire immediately» are opposite
    instructions and must not share a spelling."""
    seconds, note = resolve_fill_deadline('-1')

    assert seconds == float(DEFAULT_FILL_DEADLINE_SECONDS)
    assert note and 'negative' in note


def test_an_explicit_zero_disables_it_without_a_complaint():
    assert resolve_fill_deadline('0') == (0.0, None)


# -- the run -----------------------------------------------------------------


def _drive(*, deadline_seconds, batch_count=3, expire_after_calls=None):
    """The real workflow against a GIS stub that serves `batch_count` batches.

    `expire_after_calls` moves the clock past the deadline once that many agent
    calls have been made, which is how a deadline is made to fire mid-run
    without waiting for one.
    """
    served = {'n': 0}
    calls: list[str] = []
    submitted: list[dict] = []
    clock = _Clock()

    def _batch(index):
        value = batch()
        value['batch_id'] = f'BATCH-{index}'
        return value

    async def gis_call(payload):
        if payload['action'] == 'start':
            served['n'] = 1
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-deadline',
                'object_name': 'Лекын',
                'datacube': {},
                'batches_total': batch_count,
                'next_batch': _batch(1),
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            served['n'] += 1
            nxt = _batch(served['n']) if served['n'] <= batch_count else None
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-deadline',
                'next_batch': nxt,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-deadline',
            'xlsx': {'download_path': '/geotizer/files/run-deadline/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        calls.append(task.role)
        if expire_after_calls is not None and len(calls) >= expire_after_calls:
            clock.advance(deadline_seconds + 1)
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(envelope(), ensure_ascii=False)

    import open_webui.services.artifacts.geotizer.workflow as module

    original = module.FillDeadline
    module.FillDeadline = lambda seconds: original(seconds, now=clock)
    try:
        final = asyncio.run(
            run_geotizer_workflow(
                object_name='Лекын',
                project_id=None,
                model_run_id=None,
                run_id=None,
                allow_draft=True,
                gis_call=gis_call,
                agent_call=agent_call,
                fill_deadline_seconds=deadline_seconds,
            )
        )
    finally:
        module.FillDeadline = original
    return final, calls, submitted


def test_a_fill_inside_its_deadline_is_untouched():
    """The property that matters most: this must never cut work that is
    running. A run that never reaches the deadline must be the run it would
    have been without one."""
    final, calls, submitted = _drive(deadline_seconds=21600, batch_count=3)

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 3
    assert calls, 'the run made no agent calls at all'
    assert not any('предельный срок' in note for note in final.get('run_notes') or [])


def test_an_expired_deadline_stops_the_calling_and_not_the_submitting():
    """GIS refuses `missing_owner_batches` whatever `allow_draft` says, so a
    run that stopped submitting would finalize into nothing. Every batch is
    still closed; what stops is the work."""
    final, calls, submitted = _drive(
        deadline_seconds=100, batch_count=4, expire_after_calls=1
    )

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 4, 'a batch was left outstanding and GIS would refuse'


def test_the_run_stops_making_agent_calls_once_the_deadline_passes():
    """The whole point. Without this the deadline is a log line."""
    unbounded, unbounded_calls, _ = _drive(deadline_seconds=21600, batch_count=4)
    stopped, stopped_calls, _ = _drive(
        deadline_seconds=100, batch_count=4, expire_after_calls=1
    )

    assert len(stopped_calls) < len(unbounded_calls)
    assert unbounded['workflow_status'] == stopped['workflow_status'] == 'finalized'


def test_the_card_says_which_batch_it_stopped_at_and_how_many_remained():
    final, _, _ = _drive(deadline_seconds=100, batch_count=4, expire_after_calls=1)

    notes = final.get('run_notes') or []
    stop = next((note for note in notes if 'предельный срок' in note), '')
    assert stop, notes
    # Named exactly, and counted from the plan GIS sent. Four batches, stopped
    # entering the second: three were never requested. Counting from
    # `MAX_BATCHES` instead -- the loop's own safety ceiling at 12, which has
    # nothing to do with how many batches this policy has -- would report
    # eleven, and a reader would go looking for seven batches that never
    # existed.
    assert 'остановлено на пакете BATCH-2' in stop
    assert 'не запрошено пакетов: 3' in stop
    # and a reader sees it, which is the other half
    assert 'Ограничения этого запуска' in run_notes_section(final)


def test_the_stop_is_recorded_once_and_not_per_batch():
    """Four batches after expiry must not produce four identical notes."""
    final, _, _ = _drive(deadline_seconds=100, batch_count=5, expire_after_calls=1)

    notes = [n for n in (final.get('run_notes') or []) if 'предельный срок' in n]
    assert len(notes) == 1, notes


def test_a_deadline_closed_cell_says_no_call_was_made():
    """«No call was made» and «three calls failed» are the same cell to a
    reader with only the status, and only one of them is recovered by rerunning
    the object."""
    _, _, submitted = _drive(deadline_seconds=100, batch_count=3, expire_after_calls=1)

    closed = [
        patch
        for payload in submitted
        for patch in payload.get('patches') or []
        if (patch.get('source_locator') or {}).get('stopped_by') == 'fill_deadline'
    ]
    assert closed, 'no cell recorded the deadline as its reason'
    note = closed[0]['retrieval_note']
    assert 'fill deadline was reached before these fields were requested' in note
    assert 'Validation feedback' not in note, 'nothing was validated; there is no feedback'


def test_a_deadline_closed_cell_is_not_reported_as_a_contract_failure():
    """The three other failure sentences all describe an answer that came back
    wrong, empty, or not at all. This one means nothing was asked."""
    _, _, submitted = _drive(deadline_seconds=100, batch_count=3, expire_after_calls=1)

    notes = [
        patch['retrieval_note']
        for payload in submitted
        for patch in payload.get('patches') or []
        if (patch.get('source_locator') or {}).get('stopped_by') == 'fill_deadline'
    ]
    assert notes
    for note in notes:
        assert 'deterministic field contract' not in note
        assert 'usable envelope' not in note


# -- the mid-batch case, which is where fields could be lost -----------------


def _wide_batch(field_count):
    """One batch big enough to be partitioned. `MAX_OWNER_FIELDS_PER_CALL` is
    18, so 54 fields is three chunks."""
    value = batch()
    value['batch_id'] = 'WIDE'
    value['fields'] = [
        {'field_key': f'f{n}', 'row_id': 1 + n // 6} for n in range(field_count)
    ]
    return value


def _drive_one_wide_batch(*, deadline_seconds, expire_after_calls, field_count=54):
    calls: list[str] = []
    submitted: list[dict] = []
    clock = _Clock()
    value = _wide_batch(field_count)
    served = {'done': False}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-wide',
                'object_name': 'Лекын',
                'datacube': {},
                'batches_total': 1,
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            submitted.append(payload)
            served['done'] = True
            return {'workflow_status': 'collecting', 'run_id': 'run-wide', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-wide',
            'xlsx': {'download_path': '/geotizer/files/run-wide/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        calls.append(task.role)
        if expire_after_calls is not None and len(calls) >= expire_after_calls:
            clock.advance(deadline_seconds + 1)
        if task.role == 'contributor':
            return 'bounded evidence'
        # A real envelope for whichever chunk this is, built from the field
        # keys in the prompt. Returning the two-field fixture instead would
        # fail validation on an eighteen-field chunk, every chunk would fall
        # through to the contract-failure envelope, and these tests would pass
        # without a single chunk ever having been answered.
        keys = sorted(set(re.findall(r'\bf\d+\b', prompt)), key=lambda k: int(k[1:]))
        assert keys, 'the owner prompt named no fields'
        raw = envelope()
        raw['batch_id'] = 'WIDE'
        raw['patches'] = [
            {
                'field_key': key,
                'value': None,
                'unit': None,
                'status': 'not_found',
                'source_refs': ['s1'],
                'source_locator': {'page_or_chunk_or_layer_or_feature_or_query': 'p.1'},
                'retrieval_note': 'nothing in the corpus',
            }
            for key in keys
        ]
        return json.dumps(raw, ensure_ascii=False)

    import open_webui.services.artifacts.geotizer.workflow as module

    original = module.FillDeadline
    module.FillDeadline = lambda seconds: original(seconds, now=clock)
    try:
        final = asyncio.run(
            run_geotizer_workflow(
                object_name='Лекын',
                project_id=None,
                model_run_id=None,
                run_id=None,
                allow_draft=True,
                gis_call=gis_call,
                agent_call=agent_call,
                fill_deadline_seconds=deadline_seconds,
            )
        )
    finally:
        module.FillDeadline = original
    return final, calls, submitted


def test_a_batch_stopped_between_chunks_still_submits_every_field():
    """The failure this could have shipped. A batch submitted with a chunk
    missing is rejected by the submission rule -- one patch per field_key -- so
    the batch is lost, `next_batch` stays set, and the run cannot finalize at
    all. The deadline would then produce less than no deadline."""
    final, calls, submitted = _drive_one_wide_batch(
        deadline_seconds=100, expire_after_calls=1
    )

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 1
    keys = [patch['field_key'] for patch in submitted[0]['patches']]
    assert len(keys) == 54
    assert len(set(keys)) == 54


def test_the_chunks_before_the_deadline_keep_their_real_answers():
    """Cooperative, not cancelling: work already done is not discarded, and the
    chunk in flight when the deadline passed still finished."""
    _, _, submitted = _drive_one_wide_batch(deadline_seconds=100, expire_after_calls=99)
    unbounded_keys = {
        patch['field_key']
        for patch in submitted[0]['patches']
        if (patch.get('source_locator') or {}).get('stopped_by') != 'fill_deadline'
    }

    assert len(unbounded_keys) == 54, 'a run inside its deadline lost fields'


def test_a_mid_batch_stop_marks_only_the_chunks_it_never_requested():
    final, _, submitted = _drive_one_wide_batch(
        deadline_seconds=100, expire_after_calls=1
    )
    patches = submitted[0]['patches']
    closed = [
        patch
        for patch in patches
        if (patch.get('source_locator') or {}).get('stopped_by') == 'fill_deadline'
    ]

    assert 0 < len(closed) < len(patches), (
        'either nothing was stopped or the whole batch was, and the first '
        'chunk had already been collected'
    )


def test_the_remaining_count_survives_a_summary_without_a_denominator():
    """`batches_total` is on every GIS summary today, so the fallback path is
    the one that only runs on the day one omits it. It counts from what has
    been applied plus the batch it stopped on -- never from `MAX_BATCHES`."""
    from open_webui.services.artifacts.geotizer.workflow import _remaining_batch_count

    state = {'applied_batches': ['A', 'B']}

    assert _remaining_batch_count(state, 2, None) == 1
    assert _remaining_batch_count(state, 2, '') == 1
    assert _remaining_batch_count({}, 0, 8) == 8
    assert _remaining_batch_count({}, 3, 8) == 5


def test_a_deadline_closed_cell_takes_the_status_the_service_accepts():
    """The deadline reuses the fallback envelope, so it inherits the deploy
    gate: `agent_contract_failed` where the service advertises it, the old
    status where it does not. The status is imprecise for this case either way
    -- «СБОЙ АГЕНТА» says an agent failed and none was called -- which is why
    `stopped_by` is in the locator and the note says it in words.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        AGENT_FAILURE_STATUS,
        EXPERT_REVIEW_STATUS,
        owner_failure_envelope,
    )

    value = batch()
    value['accepted_field_statuses'] = ['agent_contract_failed', 'filled', 'not_found']
    advertised = owner_failure_envelope(
        value, run_id='r', attempts=0, feedback=[], stopped_by_deadline=True
    )
    value.pop('accepted_field_statuses')
    older = owner_failure_envelope(
        value, run_id='r', attempts=0, feedback=[], stopped_by_deadline=True
    )

    assert {p['status'] for p in advertised['patches']} == {AGENT_FAILURE_STATUS}
    assert {p['status'] for p in older['patches']} == {EXPERT_REVIEW_STATUS}
    for env in (advertised, older):
        assert env['patches'][0]['source_locator']['stopped_by'] == 'fill_deadline'
