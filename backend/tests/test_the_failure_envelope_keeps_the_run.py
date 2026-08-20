"""An unhandled exception that loses the run id turns a recoverable run into a
lost one, which is worse than the crash it came with.

The `AttributeError` on batch 2 came back as

    {"status": "geotizer_failed", "code": "AttributeError",
     "message": "'str' object has no attribute 'get'",
     "run_id": null, "resumable": false}

A run existed. Batch 1 had been applied and was sitting in the GIS store. The
generic handler had nothing to report it with: `run_id` is the argument the
caller passed, which is empty on a fresh fill, and `exc.run_id` is carried only
by the orchestration errors that set it — a bare `AttributeError` has none.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import recovered_run_id


class _Carrying(Exception):
    run_id = 'from-the-exception'


def test_a_run_this_call_started_is_recovered():
    """The case that was lost. Nothing but `started_run` knows about it."""
    assert recovered_run_id({'run_id': 'run-abc'}, AttributeError('boom'), None) == 'run-abc'


def test_an_error_carrying_its_own_run_id_still_wins_over_the_request():
    assert recovered_run_id({}, _Carrying(), 'requested') == 'from-the-exception'


def test_a_resume_falls_back_to_what_it_was_asked_to_continue():
    assert recovered_run_id({}, AttributeError('boom'), 'requested') == 'requested'


def test_a_started_run_outranks_both():
    """A resume that then started a different run would be misreported by the
    requested id, and the started one is the run that actually exists."""
    assert (
        recovered_run_id({'run_id': 'actually-started'}, _Carrying(), 'requested')
        == 'actually-started'
    )


def test_a_failure_before_any_run_existed_reports_none():
    """`resumable` is derived from this, so inventing an id here would promise
    a resume that cannot work."""
    assert recovered_run_id({}, AttributeError('boom'), None) is None
    assert recovered_run_id(None, AttributeError('boom'), '') is None


def test_the_workflow_hands_the_id_out_before_it_can_crash():
    """The wiring. A recovery path reading a mapping nothing writes is the same
    defect one layer along, which this pipeline has now produced eight times."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    from test_geotizer_orchestration import batch, envelope

    started: dict = {}

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-that-existed',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': batch(),
            }
        raise AttributeError("'str' object has no attribute 'get'")

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'evidence'
        return json.dumps(envelope(), ensure_ascii=False)

    try:
        asyncio.run(
            run_geotizer_workflow(
                object_name='Лекын',
                project_id=None,
                model_run_id=None,
                run_id=None,
                allow_draft=True,
                gis_call=gis_call,
                agent_call=agent_call,
                started_run=started,
            )
        )
    except Exception:
        pass

    assert started.get('run_id') == 'run-that-existed'
    assert recovered_run_id(started, AttributeError('boom'), None) == 'run-that-existed'
