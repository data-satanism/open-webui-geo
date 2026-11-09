"""The run idempotency mechanism, from the workflow down to the file on disk."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer.workflow import (  # noqa: E402
    UNRESOLVABLE_RUN_ID,
    geotizer_run_identity,
    run_geotizer_workflow,
)
from open_webui.services.geotizer.errors import GeotizerOrchestrationError  # noqa: E402
from open_webui.services.core.idempotency import frozen_inputs_hash, resolve_run, run_key  # noqa: E402
from open_webui.utils.geotizer_run_registry import (  # noqa: E402
    ENABLE_ENV,
    FileRunRegistry,
    RunRegistryUnavailable,
    build_run_registry,
)


@pytest.fixture
def registry(tmp_path):
    return FileRunRegistry(tmp_path / 'geotizer_runs')


def _key(**overrides):
    fields = {
        'requester_id': 'user-1',
        'object_name': 'Лекын-Тальбейская площадь',
        'project_id': None,
        'model_run_id': None,
        'allow_draft': True,
        'vision_collection_url': None,
        'attached_file_ids': None,
        'run_mode': 'clean',
        'attempt_key': 'msg-1',
        'rag_dispatcher': None,
    }
    return geotizer_run_identity(**{**fields, **overrides})


def test_a_binding_is_found_by_a_registry_that_never_saw_it_written(tmp_path):
    """A second registry instance over the same directory finds a binding the first one
    wrote."""
    writer = FileRunRegistry(tmp_path / 'runs')
    writer.record(_key(), 'run-1')

    reader = FileRunRegistry(tmp_path / 'runs')

    assert reader.find(_key()) == 'run-1'


def test_an_unbound_key_is_absent_rather_than_an_error(registry):
    assert registry.find(_key()) is None


def test_rebinding_a_key_to_a_different_run_is_refused(registry):
    registry.record(_key(), 'run-1')

    with pytest.raises(ValueError, match='already bound'):
        registry.record(_key(), 'run-2')

    assert registry.find(_key()) == 'run-1'


def test_recording_the_same_run_twice_is_not_an_error(registry):
    """Recording the same run for the same key twice is not an error."""
    registry.record(_key(), 'run-1')
    registry.record(_key(), 'run-1')

    assert registry.find(_key()) == 'run-1'


def test_two_different_requests_do_not_share_a_binding(registry):
    registry.record(_key(), 'run-1')
    registry.record(_key(allow_draft=False), 'run-2')

    assert registry.find(_key()) == 'run-1'
    assert registry.find(_key(allow_draft=False)) == 'run-2'


def test_the_file_is_named_by_digest_and_not_by_the_object_name(registry, tmp_path):
    """A binding file is named by the key digest and holds the object name inside."""
    registry.record(_key(), 'run-1')

    written = list((tmp_path / 'geotizer_runs').iterdir())

    assert len(written) == 1
    assert written[0].name == f'{_key().digest}.json'
    assert 'Лекын' in written[0].read_text(encoding='utf-8')


def test_a_corrupt_binding_is_refused_rather_than_read_as_absent(registry, tmp_path):
    """A corrupt binding file makes `find` raise `RunRegistryUnavailable` rather than
    return None."""
    registry.record(_key(), 'run-1')
    path = tmp_path / 'geotizer_runs' / f'{_key().digest}.json'
    path.write_text('{ this is not json', encoding='utf-8')

    with pytest.raises(RunRegistryUnavailable):
        registry.find(_key())


def test_an_empty_run_id_is_refused(registry):
    with pytest.raises(ValueError, match='run_id is required'):
        registry.record(_key(), '')


def test_forget_drops_a_binding_and_reports_whether_there_was_one(registry):
    registry.record(_key(), 'run-1')

    assert registry.forget(_key()) is True
    assert registry.forget(_key()) is False
    assert registry.find(_key()) is None


def test_nothing_in_the_repository_calls_forget():
    """No module under `backend/open_webui` other than the registry calls `.forget(`."""
    callers = []
    for path in sorted((REPO_ROOT / 'backend/open_webui').rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        if '.forget(' in text and 'geotizer_run_registry' not in path.name:
            callers.append(str(path.relative_to(REPO_ROOT)))

    assert callers == []


def test_a_writable_data_dir_gets_a_registry(tmp_path):
    assert isinstance(build_run_registry(tmp_path, environ={}), FileRunRegistry)


def test_the_env_switch_turns_it_off(tmp_path):
    assert build_run_registry(tmp_path, environ={ENABLE_ENV: 'false'}) is None


@pytest.mark.parametrize('value', ['0', 'FALSE', 'no', 'Off'])
def test_the_switch_is_read_the_way_an_operator_would_write_it(tmp_path, value):
    assert build_run_registry(tmp_path, environ={ENABLE_ENV: value}) is None


def test_a_filesystem_without_hardlinks_degrades_instead_of_failing(tmp_path, monkeypatch):
    """`build_run_registry` returns None when `os.link` fails on the data dir."""
    import open_webui.utils.geotizer_run_registry as module

    def _no_links(src, dst):
        raise OSError(1, 'Operation not permitted')

    monkeypatch.setattr(module.os, 'link', _no_links)

    assert build_run_registry(tmp_path, environ={}) is None


def test_a_zero_byte_binding_is_refused_before_a_run_is_started(registry, tmp_path):
    """`find` raises `RunRegistryUnavailable` naming the empty file and the registry
    root for a zero-byte binding."""
    registry.root.mkdir(parents=True, exist_ok=True)
    (registry.root / f'{_key().digest}.json').write_bytes(b'')

    with pytest.raises(RunRegistryUnavailable) as excinfo:
        registry.find(_key())

    assert 'empty file' in str(excinfo.value)
    assert str(registry.root) in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_zero_byte_binding_leaks_no_run_however_often_it_is_retried(registry):
    """Retrying `resolve_run` over a zero-byte binding raises every time and never calls
    `start`."""
    registry.root.mkdir(parents=True, exist_ok=True)
    (registry.root / f'{_key().digest}.json').write_bytes(b'')
    starts = []

    async def start():
        starts.append(1)
        return f'run-{len(starts)}'

    for _ in range(3):
        with pytest.raises(RunRegistryUnavailable):
            await resolve_run(_key(), registry=registry, start=start)

    assert starts == []


def test_a_stale_scratch_file_does_not_wedge_record(registry):
    """Stale scratch files in the registry root do not stop `record`."""
    registry.root.mkdir(parents=True, exist_ok=True)
    for stale in ('.bind-abc.tmp', f'.{_key().digest}.{__import__("os").getpid()}.0.tmp'):
        (registry.root / stale).write_text('left by a crash', encoding='utf-8')

    registry.record(_key(), 'run-1')

    assert registry.find(_key()) == 'run-1'


def test_record_leaves_no_scratch_behind(registry):
    registry.record(_key(), 'run-1')
    try:
        registry.record(_key(), 'run-2')
    except ValueError:
        pass

    leftovers = [p.name for p in registry.root.iterdir() if p.name.startswith('.bind-')]

    assert leftovers == []


def test_an_unwritable_data_dir_degrades_instead_of_failing(tmp_path):
    """`build_run_registry` returns None when the data dir is not writable."""
    blocked = tmp_path / 'blocked'
    blocked.write_text('not a directory', encoding='utf-8')

    assert build_run_registry(blocked, environ={}) is None


class _Gis:
    """A fake GIS service answering `start`, `get` and `finalize`."""

    def __init__(self, *, object_name='Лекын-Тальбейская площадь'):
        self.calls: list[dict] = []
        self.started = 0
        self.object_name = object_name

    async def __call__(self, payload):
        self.calls.append(payload)
        if payload['action'] == 'start':
            self.started += 1
            return self._state(f'run-{self.started}')
        if payload['action'] == 'get':
            return self._state(payload['run_id'])
        if payload['action'] == 'finalize':
            return {
                **self._state(payload['run_id']),
                'workflow_status': 'finalized',
                'xlsx': {
                    'download_path': f'/geotizer/files/{payload["run_id"]}/geotizer.xlsx'
                },
            }
        raise AssertionError(f'unexpected action {payload["action"]}')

    def _state(self, run_id):
        return {
            'run_id': run_id,
            'object_name': self.object_name,
            'workflow_status': 'collecting',
            'gis_project': {'status': 'resolved', 'project_id': 'prj-1'},
            'next_batch': None,
        }


async def _run(gis, registry, **overrides):
    fields = {
        'object_name': 'Лекын-Тальбейская площадь',
        'project_id': None,
        'model_run_id': None,
        'run_id': None,
        'allow_draft': True,
        'gis_call': gis,
        'agent_call': None,
        'run_registry': registry,
        'requester_id': 'user-1',
        'attempt_key': 'msg-1',
    }
    return await run_geotizer_workflow(**{**fields, **overrides})


@pytest.mark.asyncio
async def test_retrying_one_tool_call_returns_the_first_run(registry):
    """Repeating one tool call returns the first run through `get` and starts no second
    run."""
    gis = _Gis()

    first = await _run(gis, registry, attempt_key='msg-1')
    second = await _run(gis, registry, attempt_key='msg-1')

    assert first['run_id'] == second['run_id'] == 'run-1'
    assert gis.started == 1
    assert [call['action'] for call in gis.calls].count('start') == 1
    assert 'get' in [call['action'] for call in gis.calls]


@pytest.mark.asyncio
async def test_a_second_user_message_fills_the_object_again(registry):
    """A second user message with the same inputs starts a new run."""
    gis = _Gis()

    first = await _run(gis, registry, attempt_key='msg-monday')
    second = await _run(gis, registry, attempt_key='msg-tuesday')

    assert first['run_id'] != second['run_id']
    assert gis.started == 2
    assert not first.get('reused_run_from_registry')


@pytest.mark.asyncio
async def test_a_reused_run_says_so_on_the_state_it_returns(registry):
    """A run reached through the registry carries `reused_run_from_registry` with its
    run id."""
    gis = _Gis()

    await _run(gis, registry, attempt_key='msg-1')
    second = await _run(gis, registry, attempt_key='msg-1')

    assert second['reused_run_from_registry'] == 'run-1'


def test_a_retry_and_a_re_ask_are_different_keys():
    """The same `attempt_key` gives the same key and a different one gives a different
    key."""
    assert _key(attempt_key='msg-1').value == _key(attempt_key='msg-1').value
    assert _key(attempt_key='msg-1').value != _key(attempt_key='msg-2').value


def test_a_caller_with_no_request_identity_keys_as_it_always_did():
    """`attempt_key=None` gives a stable key distinct from any keyed request."""
    assert _key(attempt_key=None).value == _key(attempt_key=None).value
    assert _key(attempt_key=None).value != _key(attempt_key='msg-1').value


@pytest.mark.asyncio
async def test_without_a_registry_every_command_starts_a_run(registry):
    """Without a registry every command starts a new run."""
    gis = _Gis()

    await _run(gis, None)
    await _run(gis, None)

    assert gis.started == 2


@pytest.mark.asyncio
async def test_a_changed_input_is_a_different_run(registry):
    gis = _Gis()

    await _run(gis, registry)
    await _run(gis, registry, allow_draft=False)

    assert gis.started == 2


@pytest.mark.asyncio
async def test_a_run_reached_through_the_key_is_recorded_as_a_retry(registry):
    """A run reached through the key is passed to `begin_attempt` as a retry with reason
    `run_key_reuse`."""
    attempts = []

    class _Dispatcher:
        class settings:
            mode = 'shadow'
            collections = ()
            index_version = 'idx-1'

        async def begin_attempt(self, **kwargs):
            attempts.append(kwargs)
            return None

        def submit_shadow(self, *a, **k):
            return None

        async def execute_active(self, *a, **k):
            return None

    gis = _Gis()
    dispatcher = _Dispatcher()

    await _run(gis, registry, rag_dispatcher=dispatcher)
    await _run(gis, registry, rag_dispatcher=dispatcher)

    assert [a['is_retry'] for a in attempts] == [False, True]
    assert [a['retry_reason'] for a in attempts] == [None, 'run_key_reuse']


@pytest.mark.asyncio
async def test_an_explicit_run_id_still_wins(registry):
    """An explicit `run_id` is resumed without starting a run."""
    gis = _Gis()

    result = await _run(gis, registry, run_id='run-99')

    assert result['run_id'] == 'run-99'
    assert gis.started == 0


@pytest.mark.asyncio
async def test_a_reused_run_is_not_refused_because_gis_renamed_the_object(registry):
    """A reused run is accepted when GIS returns a canonicalised object name."""
    gis = _Gis(object_name='Лекын-Тальбейский')

    first = await _run(gis, registry)
    second = await _run(gis, registry)

    assert first['run_id'] == second['run_id']
    assert gis.started == 1


def test_two_users_asking_the_same_question_do_not_share_a_run():
    """Two requesters get different keys for the same question."""
    assert _key(requester_id='user-1').value != _key(requester_id='user-2').value


def test_an_unattributed_key_is_refused_rather_than_shared():
    with pytest.raises(Exception, match='requesting user'):
        _key(requester_id='')


@pytest.mark.asyncio
async def test_no_requester_means_no_reuse_rather_than_a_shared_binding(registry):
    """Without a `requester_id` every command starts a new run."""
    gis = _Gis()

    await _run(gis, registry, requester_id=None)
    await _run(gis, registry, requester_id=None)

    assert gis.started == 2


@pytest.mark.asyncio
async def test_a_reused_run_resolved_to_another_project_is_refused(registry):
    registry.record(_key(project_id='prj-2'), 'run-1')
    gis = _Gis()

    with pytest.raises(Exception, match='refusing to return it'):
        await _run(gis, registry, project_id='prj-2')


@pytest.mark.asyncio
async def test_a_failed_start_binds_nothing(registry):
    """A failed `start` leaves the key unbound."""

    async def gis(payload):
        if payload['action'] == 'start':
            return {'error': {'code': 'gis_unreachable'}}
        raise AssertionError('should not get past start')

    with pytest.raises(Exception):
        await _run(gis, registry)

    assert registry.find(_key()) is None


@pytest.mark.asyncio
async def test_a_start_without_a_run_id_binds_nothing(registry):
    async def gis(payload):
        return {'workflow_status': 'collecting', 'next_batch': None}

    with pytest.raises(Exception, match='without returning a run_id'):
        await _run(gis, registry)

    assert registry.find(_key()) is None


@pytest.mark.asyncio
async def test_two_callers_racing_produce_one_binding_and_one_abandoned_run(registry):
    """Two concurrent `resolve_run` calls without a lock end with one binding given to
    both and one abandoned run."""
    both_started = asyncio.Event()
    started = []

    async def start(name):
        started.append(name)
        if len(started) == 1:
            await both_started.wait()
        else:
            both_started.set()
        return f'run-{name}'

    key = _key()
    first, second = await asyncio.gather(
        resolve_run(key, registry=registry, start=lambda: start('a')),
        resolve_run(key, registry=registry, start=lambda: start('b')),
    )

    assert sorted(started) == ['a', 'b'], 'both callers must reach start or this is not a race'
    bound = registry.find(key)
    assert {first.run_id, second.run_id} == {bound}, 'both callers must be given the one binding'
    abandoned = [r.abandoned_run_id for r in (first, second) if r.abandoned_run_id]
    assert len(abandoned) == 1
    assert abandoned[0] != bound


@pytest.mark.asyncio
async def test_the_loser_of_a_true_race_names_the_run_it_abandoned(tmp_path):
    """The loser of a race returns the winner's run, names its own run as abandoned and
    reports `joined_existing`."""

    class _RacingRegistry(FileRunRegistry):
        def __init__(self, root):
            super().__init__(root)
            self.reads = 0

        def find(self, key):
            self.reads += 1
            if self.reads == 2:
                super().record(key, 'run-from-the-winner')
                return None
            return super().find(key)

    registry = _RacingRegistry(tmp_path / 'runs')

    resolution = await resolve_run(_key(), registry=registry, start=lambda: 'run-mine')

    assert resolution.run_id == 'run-from-the-winner'
    assert resolution.abandoned_run_id == 'run-mine'
    assert resolution.joined_existing is True


@pytest.mark.asyncio
async def test_clean_is_what_gis_is_asked_for_when_the_caller_says_nothing(registry):
    """`run_mode` defaults to `clean` in the `start` call."""
    gis = _Gis()

    await _run(gis, registry)

    start = next(c for c in gis.calls if c['action'] == 'start')
    assert start['run_mode'] == 'clean'


@pytest.mark.asyncio
async def test_carry_forward_is_passed_through_when_it_is_asked_for(registry):
    gis = _Gis()

    await _run(gis, registry, run_mode='carry_forward')

    start = next(c for c in gis.calls if c['action'] == 'start')
    assert start['run_mode'] == 'carry_forward'


@pytest.mark.asyncio
async def test_the_configured_kb_scope_is_recorded_on_the_run(registry):
    """The configured KB scope and collections are sent with `start`."""
    gis = _Gis()

    await _run(
        gis,
        registry,
        kb_scope_status='configured',
        kb_configured_collections=('geo-a', 'geo-b'),
    )

    start = next(c for c in gis.calls if c['action'] == 'start')
    assert start['kb_scope_status'] == 'configured'
    assert start['kb_configured_collections'] == ['geo-a', 'geo-b']


@pytest.mark.asyncio
async def test_a_caller_that_says_nothing_records_unknown_rather_than_unconfigured(registry):
    """A caller that passes no KB scope sends `kb_scope_status` None and no collections."""
    gis = _Gis()

    await _run(gis, registry)

    start = next(c for c in gis.calls if c['action'] == 'start')
    assert start['kb_scope_status'] is None
    assert start['kb_configured_collections'] == []


def test_the_adapter_states_the_scope_it_can_see():
    """`_kb_scope` reports `unconfigured` with no attached collections and `configured`
    with the attached collection ids."""
    from open_webui.tools.geotizer import _kb_scope

    assert _kb_scope() == {'kb_scope_status': 'unconfigured', 'kb_configured_collections': []}

    assert _kb_scope([
        {'type': 'file', 'id': 'f-1'},
        {'type': 'collection', 'id': 'geo-a'},
        {'type': 'collection', 'id': 'geo-b'},
    ]) == {
        'kb_scope_status': 'configured',
        'kb_configured_collections': ['geo-a', 'geo-b'],
    }


def test_a_clean_run_and_a_carry_forward_run_are_different_runs():
    """`clean` and `carry_forward` requests have different keys."""
    assert _key(run_mode='clean').value != _key(run_mode='carry_forward').value


class _GisWithNoSuchRun(_Gis):
    """A fake GIS whose `get` finds no run.

    `raises` selects raising `error` or answering with a not-found body."""

    def __init__(self, *, raises: bool, error: str = '404 Not Found'):
        super().__init__()
        self.raises = raises
        self.error = error

    async def __call__(self, payload):
        if payload['action'] == 'get':
            self.calls.append(payload)
            if self.raises:
                raise RuntimeError(self.error)
            return {'error': 'run not found', 'run_id': None}
        return await super().__call__(payload)


@pytest.mark.parametrize('raises', [True, False], ids=['gis_raises', 'gis_answers'])
@pytest.mark.asyncio
async def test_a_run_id_that_resolves_to_nothing_names_both_ways_out(registry, raises):
    """An unresolvable `run_id` raises `UNRESOLVABLE_RUN_ID`, which names omitting
    `run_id` and `carry_forward`."""
    gis = _GisWithNoSuchRun(raises=raises)

    with pytest.raises(GeotizerOrchestrationError) as refusal:
        await _run(gis, registry, run_id='run-that-was-deleted')

    message = str(refusal.value)
    assert message == UNRESOLVABLE_RUN_ID
    assert 'Omit run_id' in message, 'the way to start a new run is not named'
    assert 'carry_forward' in message, 'the way to keep the old values is not named'


@pytest.mark.asyncio
async def test_an_unresolvable_run_id_does_not_quietly_become_a_fresh_run(registry):
    """An unresolvable `run_id` is refused without starting a run."""
    gis = _GisWithNoSuchRun(raises=True)

    with pytest.raises(GeotizerOrchestrationError):
        await _run(gis, registry, run_id='run-that-was-deleted')

    assert gis.started == 0
    assert [call['action'] for call in gis.calls] == ['get']


@pytest.mark.parametrize(
    'error',
    [
        '502 Bad Gateway',
        'Connection timed out',
        'Expecting value: line 1 column 1 (char 0)',
    ],
)
@pytest.mark.asyncio
async def test_a_service_that_is_merely_unreachable_is_not_a_missing_run(registry, error):
    """A transport error on `get` propagates unchanged rather than as
    `UNRESOLVABLE_RUN_ID`."""
    gis = _GisWithNoSuchRun(raises=True, error=error)

    with pytest.raises(Exception) as failure:  # noqa: PT011
        await _run(gis, registry, run_id='run-1')

    assert UNRESOLVABLE_RUN_ID not in str(failure.value)
    assert error in str(failure.value)


def test_a_healthy_state_is_not_read_as_a_missing_run_because_of_its_contents():
    """`_run_is_missing` ignores `not_found` and `404` inside a healthy state and
    detects a not-found error body."""
    from open_webui.services.artifacts.geotizer.workflow import _run_is_missing

    state = {
        'run_id': '404b1c22-0000-4000-8000-00000000404f',
        'workflow_status': 'collecting',
        'counts': {'filled': 12, 'not_found': 339},
        'fields': [{'field_key': 'k1', 'status': 'not_found'}],
        'xlsx': {'sha256': '404' + 'a' * 61},
    }

    assert _run_is_missing(state, None) is False
    assert _run_is_missing({'error': 'run not found'}, None) is True


@pytest.mark.asyncio
async def test_the_adapter_passes_the_real_user_and_files_into_the_identity(monkeypatch, tmp_path):
    """`fill_geotizer` passes the user id, the attached files and a registry to the
    workflow."""
    from open_webui.tools import geotizer as tool

    seen = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        return {
            'run_id': 'run-1',
            'object_name': 'Лекын',
            'workflow_status': 'finalized',
            'next_batch': None,
            'xlsx': {'download_path': '/geotizer/files/run-1/geotizer.xlsx', 'sha256': 'a' * 64},
            'audit': {'passed': True, 'failed': [], 'warnings': []},
        }

    async def _noop(*args, **kwargs):
        return None

    async def _noop_agent_caller(*args, **kwargs):
        return None, {}, None

    monkeypatch.setattr(tool, '_user_model', _noop)
    monkeypatch.setattr(tool, '_resolve_geotizer_callable', _noop)
    monkeypatch.setattr(tool, '_build_agent_caller', _noop_agent_caller)
    monkeypatch.setattr(tool, '_build_rag_dispatcher', lambda *a, **k: None)
    monkeypatch.setattr(tool, '_build_vision_evidence_caller', _noop)
    monkeypatch.setattr(tool, 'run_geotizer_workflow', _capture)
    monkeypatch.setattr(tool, 'GEOMAS_RUNTIME_DATA_DIR', tmp_path)

    await tool.fill_geotizer(
        object_name='Лекын',
        __request__=object(),
        __user__={'id': 'user-42'},
        __files__=[{'type': 'file', 'id': 'f1'}, {'file': {'id': 'f2'}}],
    )

    assert seen['requester_id'] == 'user-42'
    assert seen['attached_file_ids'] == [{'type': 'file', 'id': 'f1'}, {'file': {'id': 'f2'}}]
    assert seen['run_registry'] is not None
    key = geotizer_run_identity(
        requester_id=seen['requester_id'],
        object_name='Лекын',
        project_id=None,
        model_run_id=None,
        allow_draft=True,
        vision_collection_url=None,
        attached_file_ids=seen['attached_file_ids'],
    )
    assert key.value != _key(object_name='Лекын', requester_id='user-42').value


@pytest.mark.asyncio
async def test_two_concurrent_records_of_one_key_give_both_callers_the_winner(registry):
    """A second `record` of a bound key raises `already bound` and leaves the first
    binding readable."""
    registry.record(_key(), 'run-winner')

    with pytest.raises(ValueError, match='already bound'):
        registry.record(_key(), 'run-loser')

    assert registry.find(_key()) == 'run-winner'
    assert json.loads((registry.root / f'{_key().digest}.json').read_text(encoding='utf-8'))['run_id'] == 'run-winner'


def test_an_unpinned_request_is_scoped_by_the_object_name():
    key = _key()

    assert key.project_id == 'object:Лекын-Тальбейская площадь'
    assert key.artifact_set == ('geotizer_object',)


def test_a_pinned_request_is_scoped_by_the_project():
    assert _key(project_id='prj-1').project_id == 'prj-1'


def test_an_object_scope_can_never_be_read_as_a_project_id():
    """An object scope never equals a project id of the same text."""
    assert _key(project_id='Лекын-Тальбейская площадь').project_id != _key().project_id


@pytest.mark.parametrize(
    'change',
    [
        {'object_name': 'Другая площадь'},
        {'project_id': 'prj-1'},
        {'model_run_id': 'mr-1'},
        {'allow_draft': False},
        {'vision_collection_url': 'https://example.invalid/c/1'},
        {'attached_file_ids': [{'id': 'file-1'}]},
        {'requester_id': 'user-2'},
        {'run_mode': 'carry_forward'},
    ],
)
def test_every_input_a_caller_can_vary_changes_the_run(change):
    """Each caller-variable input changes the key."""
    assert _key(**change).value != _key().value


def test_attachment_order_is_not_a_different_request():
    """Attaching two maps is one question however the client ordered them."""
    a, b = {'id': 'a'}, {'id': 'b'}
    assert _key(attached_file_ids=[a, b]).value == _key(attached_file_ids=[b, a]).value
    assert _key(attached_file_ids=[a, a]).value == _key(attached_file_ids=[a]).value


@pytest.mark.parametrize(
    'item',
    [
        {'type': 'file', 'id': 'f1'},
        {'type': 'file', 'file': {'id': 'f1'}},
        {'file_id': 'f1'},
        {'source': {'id': 'f1'}},
        {'type': 'file', 'name': 'map.png'},
        'map.png',
    ],
)
def test_an_attachment_of_any_shape_changes_the_run(item):
    """An attachment of any shape changes the key."""
    assert _key(attached_file_ids=[item]).value != _key().value


def test_two_different_attachments_are_two_different_runs():
    assert (
        _key(attached_file_ids=[{'id': 'f1'}]).value
        != _key(attached_file_ids=[{'id': 'f2'}]).value
    )
    assert (
        _key(attached_file_ids=[{'name': 'a.png'}]).value
        != _key(attached_file_ids=[{'name': 'b.png'}]).value
    )


def test_the_same_attachment_in_two_shapes_is_not_silently_one_run():
    """The same file id at two different paths gives two different keys."""
    assert (
        _key(attached_file_ids=[{'id': 'f1'}]).value
        != _key(attached_file_ids=[{'file': {'id': 'f1'}}]).value
    )


def test_whitespace_is_not_a_different_request():
    assert _key(project_id='  ').value == _key(project_id=None).value
    assert _key(object_name=' Лекын-Тальбейская площадь ').value == _key().value


def test_the_retrieval_index_is_part_of_the_identity():
    """A different index answers different questions from the same sources."""

    class _Settings:
        def __init__(self, version):
            self.index_version = version
            self.collections = ('geo-v2',)
            self.mode = 'shadow'

    class _Dispatcher:
        def __init__(self, version):
            self.settings = _Settings(version)

    assert _key(rag_dispatcher=_Dispatcher('idx-7')).value != _key().value
    assert (
        _key(rag_dispatcher=_Dispatcher('idx-7')).value
        != _key(rag_dispatcher=_Dispatcher('idx-8')).value
    )


def test_the_key_is_what_the_assignment_names_it(registry, tmp_path):
    """The stored record holds `project_id`, `artifact_set`, `frozen_inputs_hash` and
    the `run_id`."""
    registry.record(_key(), 'run-1')

    stored = json.loads((tmp_path / 'geotizer_runs' / f'{_key().digest}.json').read_text(encoding='utf-8'))

    assert set(stored['key']) == {'project_id', 'artifact_set', 'frozen_inputs_hash'}
    assert stored['run_id'] == 'run-1'
    assert stored['key']['frozen_inputs_hash'] == _key().frozen_inputs_hash


def test_the_identity_is_formed_the_same_way_by_hand():
    """`geotizer_run_identity` equals `run_key` built by hand from the same inputs."""
    expected = run_key(
        project_id='object:Лекын-Тальбейская площадь',
        artifact_set=('geotizer_object',),
        frozen_inputs_hash=frozen_inputs_hash(
            {
                'requester_id': 'user-1',
                'object_name': 'Лекын-Тальбейская площадь',
                'project_id': None,
                'model_run_id': None,
                'allow_draft': True,
                'vision_collection_url': None,
                'attached_sources': [],
                'run_mode': 'clean',
                'licence_id': None,
                'licence_layer_id': None,
                'attempt_key': 'msg-1',
                'rag': None,
                'kb_scope': {'status': None, 'collections': []},
            }
        ),
    )

    assert _key() == expected


def test_the_kb_collection_scope_is_part_of_the_identity():
    """The KB scope status and collections are part of the key."""
    scoped = _key(kb_scope_status='configured', kb_configured_collections=('geo-a', 'geo-b'))

    assert scoped.value != _key(kb_scope_status='unconfigured').value
    assert scoped.value != _key().value
    assert scoped.value != _key(kb_scope_status='configured', kb_configured_collections=('geo-a',)).value


@pytest.mark.asyncio
async def test_a_wedged_binding_no_longer_blocks_the_next_request(registry):
    """A wedged binding refuses its own tool call without starting a run, and the next
    user message is served."""
    wedged = _key(attempt_key='msg-wedged')
    registry.root.mkdir(parents=True, exist_ok=True)
    (registry.root / f'{wedged.digest}.json').write_bytes(b'')
    gis = _Gis()

    for _ in range(3):
        with pytest.raises(RunRegistryUnavailable):
            await _run(gis, registry, attempt_key='msg-wedged')
    assert gis.started == 0

    result = await _run(gis, registry, attempt_key='msg-next')

    assert result['run_id'] == 'run-1'
    assert gis.started == 1


def test_two_licences_of_one_registry_are_two_runs():
    """Two licences of one project have different keys, and a licence changes the key."""
    first = _key(project_id='Лекын-Талбейская площадь', licence_id='СЛХ025834ТП')
    second = _key(project_id='Лекын-Талбейская площадь', licence_id='КРР034111БГ')

    assert first.value != second.value
    assert first.value != _key(project_id='Лекын-Талбейская площадь').value


def test_the_layer_that_disambiguates_is_part_of_the_identity():
    """The licence layer is part of the key."""
    annulled = _key(licence_id='КРР034111БГ', licence_layer_id='Licenses_annul')
    current = _key(licence_id='КРР034111БГ', licence_layer_id='Licenses_2024_2025')

    assert annulled.value != current.value
