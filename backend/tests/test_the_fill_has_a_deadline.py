"""A whole fill has a deadline that stops agent calls but still closes and submits every batch, so the run finalizes."""

from __future__ import annotations

import asyncio
import json
import re


from open_webui.services.core.deadline import FillDeadline
from open_webui.services.artifacts.geotizer.terminal import run_notes_section
from open_webui.services.artifacts.geotizer.workflow import (
    DEFAULT_FILL_DEADLINE_SECONDS,
    resolve_fill_deadline,
    run_geotizer_workflow,
)

from test_geotizer_orchestration import batch, envelope


class _Clock:
    """A hand-cranked monotonic clock. Nothing here sleeps."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_an_unconfigured_deadline_never_expires():
    """A deadline of zero is unconfigured and never expires."""
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
    """`FillDeadline.expired` reads the clock on every call."""
    clock = _Clock()
    deadline = FillDeadline(10, now=clock)
    for _ in range(3):
        assert deadline.expired() is False
    clock.advance(11)

    assert deadline.expired() is True


def test_the_default_is_six_hours():
    assert DEFAULT_FILL_DEADLINE_SECONDS == 21600
    assert resolve_fill_deadline(None) == (21600.0, None)


def test_a_small_deadline_is_allowed_and_announced():
    """A small configured deadline is accepted and reported in a note."""
    seconds, note = resolve_fill_deadline('600')

    assert seconds == 600.0
    assert note and '600' in note


def test_garbage_falls_back_and_says_so():
    seconds, note = resolve_fill_deadline('soon')

    assert seconds == float(DEFAULT_FILL_DEADLINE_SECONDS)
    assert note and 'not a number' in note


def test_a_negative_deadline_is_refused():
    """A negative deadline falls back to the default with a note, rather than being treated as zero."""
    seconds, note = resolve_fill_deadline('-1')

    assert seconds == float(DEFAULT_FILL_DEADLINE_SECONDS)
    assert note and 'negative' in note


def test_an_explicit_zero_disables_it_without_a_complaint():
    assert resolve_fill_deadline('0') == (0.0, None)


def _drive(*, deadline_seconds, batch_count=3, expire_after_calls=None):
    """Run the real workflow against a GIS stub that serves `batch_count` batches.

    `expire_after_calls` moves the clock past the deadline once that many agent
    calls have been made. Returns the final payload, the agent roles called and
    the submitted payloads.
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
    """A run that finishes inside its deadline submits every batch and records no deadline note."""
    final, calls, submitted = _drive(deadline_seconds=21600, batch_count=3)

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 3
    assert calls, 'the run made no agent calls at all'
    assert not any('предельный срок' in note for note in final.get('run_notes') or [])


def test_an_expired_deadline_stops_the_calling_and_not_the_submitting():
    """After the deadline expires every batch is still submitted and the run finalizes."""
    final, calls, submitted = _drive(
        deadline_seconds=100, batch_count=4, expire_after_calls=1
    )

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 4, 'a batch was left outstanding and GIS would refuse'


def test_the_run_stops_making_agent_calls_once_the_deadline_passes():
    """An expired deadline reduces the number of agent calls the run makes."""
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
    assert 'остановлено на пакете BATCH-2' in stop
    assert 'не запрошено пакетов: 3' in stop
    assert 'Ограничения этого запуска' in run_notes_section(final)


def test_the_stop_is_recorded_once_and_not_per_batch():
    """The deadline stop produces one run note however many batches remain."""
    final, _, _ = _drive(deadline_seconds=100, batch_count=5, expire_after_calls=1)

    notes = [n for n in (final.get('run_notes') or []) if 'предельный срок' in n]
    assert len(notes) == 1, notes


def test_a_deadline_closed_cell_says_no_call_was_made():
    """A deadline-closed cell says it was never requested and carries no validation feedback."""
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
    """A deadline-closed cell's note mentions neither the field contract nor a usable envelope."""
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


def _wide_batch(field_count):
    """One batch of `field_count` fields named `f0`, `f1`, …, six to a row."""
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
    """A batch stopped between chunks is submitted with one patch for every field."""
    final, calls, submitted = _drive_one_wide_batch(
        deadline_seconds=100, expire_after_calls=1
    )

    assert final['workflow_status'] == 'finalized'
    assert len(submitted) == 1
    keys = [patch['field_key'] for patch in submitted[0]['patches']]
    assert len(keys) == 54
    assert len(set(keys)) == 54


def test_the_chunks_before_the_deadline_keep_their_real_answers():
    """Chunks answered before the deadline, including the one in flight, keep their answers."""
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
    """`_remaining_batch_count` counts from applied batches plus one when `batches_total` is absent."""
    from open_webui.services.artifacts.geotizer.workflow import _remaining_batch_count

    state = {'applied_batches': ['A', 'B']}

    assert _remaining_batch_count(state, 2, None) == 1
    assert _remaining_batch_count(state, 2, '') == 1
    assert _remaining_batch_count({}, 0, 8) == 8
    assert _remaining_batch_count({}, 3, 8) == 5


def test_a_deadline_closed_cell_takes_the_status_the_service_accepts():
    """A deadline-closed cell takes the failure status the service advertises
    and records `stopped_by: fill_deadline`."""
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
