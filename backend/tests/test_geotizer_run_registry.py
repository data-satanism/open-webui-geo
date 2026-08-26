"""The idempotency mechanism, from the workflow down to the file on disk.

`test_geotizer_run_idempotency.py` covers `resolve_run` against hand-written
registries and locks, and it always passed. What it could not see is that
nothing called it: `resolve_run`, `run_key`, `RunRegistry` and `CaptureLock` had
no reference anywhere in `backend/` or `scripts/` outside that one file, so the
"permanent idempotency mechanism" expected result 7 asks for was a protocol with
no implementation and a decision procedure no run reached. Every command started
a fresh GIS run; the only way to resume one was for the caller to already know
its `run_id`.

So the tests here are deliberately the ones that file could not contain:

  the workflow reaches the registry at all, and a repeated command returns the
  original run instead of starting a second;

  the binding survives a new process, because a registry that only outlives the
  request is the Redis lock the assignment already ruled out;

  two callers racing with no lock -- which is the production configuration --
  produce one recorded run and one abandoned one, never two answers;

  a run is scoped to the person who asked for it, because the binding is one
  deployment-wide directory and the evidence a run collects is bounded by the
  requester's grants;

  and a reused run whose GIS project disagrees with a pinned request is refused,
  while one whose *name* GIS canonicalised is not -- the first version compared
  the typed name to GIS's resolved one and refused every repeat forever.
"""

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


# -- the file on disk ------------------------------------------------------


def test_a_binding_is_found_by_a_registry_that_never_saw_it_written(tmp_path):
    """The property the whole module exists for, and the one an in-memory
    registry cannot have: a second process, over the same directory, sees the
    binding. Two separate instances stand in for two containers."""
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
    """A retry that got as far as recording and then failed must be able to
    record again -- it is the same binding, not a second one."""
    registry.record(_key(), 'run-1')
    registry.record(_key(), 'run-1')

    assert registry.find(_key()) == 'run-1'


def test_two_different_requests_do_not_share_a_binding(registry):
    registry.record(_key(), 'run-1')
    registry.record(_key(allow_draft=False), 'run-2')

    assert registry.find(_key()) == 'run-1'
    assert registry.find(_key(allow_draft=False)) == 'run-2'


def test_the_file_is_named_by_digest_and_not_by_the_object_name(registry, tmp_path):
    """The key is canonical JSON containing whatever the user typed. A file
    name is not a place to put that."""
    registry.record(_key(), 'run-1')

    written = list((tmp_path / 'geotizer_runs').iterdir())

    assert len(written) == 1
    assert written[0].name == f'{_key().digest}.json'
    assert 'Лекын' in written[0].read_text(encoding='utf-8')  # inside, where it is safe


def test_a_corrupt_binding_is_refused_rather_than_read_as_absent(registry, tmp_path):
    """Returning None here would start a second run over inputs that already
    have one, which is the single failure this module exists to prevent."""
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
    """Deliberate, and worth a test rather than a comment. Clearing a binding
    because GIS answered 404 would manufacture the duplicate run the mechanism
    exists to prevent -- a misconfigured store answers 404 too."""
    callers = []
    for path in sorted((REPO_ROOT / 'backend/open_webui').rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        if '.forget(' in text and 'geotizer_run_registry' not in path.name:
            callers.append(str(path.relative_to(REPO_ROOT)))

    assert callers == []


# -- building it for a contour ---------------------------------------------


def test_a_writable_data_dir_gets_a_registry(tmp_path):
    assert isinstance(build_run_registry(tmp_path, environ={}), FileRunRegistry)


def test_the_env_switch_turns_it_off(tmp_path):
    assert build_run_registry(tmp_path, environ={ENABLE_ENV: 'false'}) is None


@pytest.mark.parametrize('value', ['0', 'FALSE', 'no', 'Off'])
def test_the_switch_is_read_the_way_an_operator_would_write_it(tmp_path, value):
    assert build_run_registry(tmp_path, environ={ENABLE_ENV: value}) is None


def test_a_filesystem_without_hardlinks_degrades_instead_of_failing(tmp_path, monkeypatch):
    """`record` links, so the probe must link.

    Testing only writability while depending on os.link turns a filesystem
    without hardlink support into an outage rather than the degradation this
    function exists to provide: every command would pass the probe, reach
    `record`, raise `RunRegistryUnavailable` -- and do it *after* starting a GIS
    run, so each failed command would leave one behind.
    """
    import open_webui.utils.geotizer_run_registry as module

    def _no_links(src, dst):
        raise OSError(1, 'Operation not permitted')

    monkeypatch.setattr(module.os, 'link', _no_links)

    assert build_run_registry(tmp_path, environ={}) is None


def test_a_zero_byte_binding_is_refused_before_a_run_is_started(registry, tmp_path):
    """The branch that briefly returned None here was the worst option available.

    `find` answering None sends `resolve_run` to `start`, GIS creates a run,
    `record` reaches os.link, gets FileExistsError because the empty file is
    still there, re-reads, gets None again, and raises "already bound to None".
    Every attempt leaked one more GIS run and the key never became usable. The
    refusal has to come from `find`, because that is the only point before
    anything has been started.
    """
    registry.root.mkdir(parents=True, exist_ok=True)
    (registry.root / f'{_key().digest}.json').write_bytes(b'')

    with pytest.raises(RunRegistryUnavailable) as excinfo:
        registry.find(_key())

    assert 'empty file' in str(excinfo.value)
    assert str(registry.root) in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_zero_byte_binding_leaks_no_run_however_often_it_is_retried(registry):
    """A wedged binding refuses its own key forever, and that is now bounded.

    Before request identity, a key that could not be read was a permanent hole:
    every later request for the same object produced the same key and hit the
    same unreadable file. Now only retries of the one tool call reach it -- the
    next user message keys differently and runs. `test_a_wedged_binding_no_
    longer_blocks_the_next_request` is the other half.
    """
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
    """`mkstemp`, not a name composed from pid and thread id. Two async tasks in
    one thread share both, and a scratch file left by a crash made every later
    call raise while the cleanup deleted a file this call had not created."""
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
    """A missing optimisation must not become an outage: without a registry the
    tool does exactly what it did before this existed."""
    blocked = tmp_path / 'blocked'
    blocked.write_text('not a directory', encoding='utf-8')

    assert build_run_registry(blocked, environ={}) is None


# -- the workflow actually reaches it --------------------------------------


class _Gis:
    """The GIS state machine, far enough to answer `start` and `get`."""

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
        # `next_batch: None` means the run has no owner work left, so the
        # workflow goes straight to finalize without needing agents, vision or a
        # template. What is under test here is which run it is working on.
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
        # Required with no default. Empty is honest here: `_Gis` returns
        # `next_batch: None`, so no batch is ever planned and nothing in these
        # tests reaches a producer lookup. What is under test is which run the
        # workflow works on, not how it routes one.
        'run_registry': registry,
        'requester_id': 'user-1',
        # The default matches `_key()`, so a test that records a binding by hand
        # and then runs the workflow is talking about one request.
        'attempt_key': 'msg-1',
    }
    return await run_geotizer_workflow(**{**fields, **overrides})


@pytest.mark.asyncio
async def test_retrying_one_tool_call_returns_the_first_run(registry):
    """Idempotency, at the level it was found: `workflow.py` resumed only when
    the caller passed `run_id`, and otherwise sent `action: 'start'` every time.

    "The same command" means the same tool call -- the same `__message_id__` --
    which is what a dropped stream or a second replica taking the same work
    looks like. A *second user message* asking the same thing is a different
    event and gets a different run; that is the test below.
    """
    gis = _Gis()

    first = await _run(gis, registry, attempt_key='msg-1')
    second = await _run(gis, registry, attempt_key='msg-1')

    assert first['run_id'] == second['run_id'] == 'run-1'
    assert gis.started == 1
    # One `start`, and the repeat comes in through `get` -- the same door an
    # explicit `run_id` resume uses.
    assert [call['action'] for call in gis.calls].count('start') == 1
    assert 'get' in [call['action'] for call in gis.calls]


@pytest.mark.asyncio
async def test_a_second_user_message_fills_the_object_again(registry):
    """The defect this key composition exists to fix.

    A user asked for a fresh card, supplied no `run_id`, and got the previous
    run's id, coverage and download link back. `GeotizerService.start()` mints a
    uuid unconditionally, so a repeated id means `start` was never reached --
    the key had bound. And it had to: the key held `project_id`, the artifact
    set and a hash of the inputs, all of which describe *what was asked* and
    none of which describes *when*. Two identical commands a week apart were one
    key, so an object could be filled exactly once, forever.
    """
    gis = _Gis()

    first = await _run(gis, registry, attempt_key='msg-monday')
    second = await _run(gis, registry, attempt_key='msg-tuesday')

    assert first['run_id'] != second['run_id']
    assert gis.started == 2
    assert not first.get('reused_run_from_registry')


@pytest.mark.asyncio
async def test_a_reused_run_says_so_on_the_state_it_returns(registry):
    """Derived from the registry resolving to a prior run, never from an
    inspection of the request. By the time the card is composed a replay and a
    first execution produce the same terminal payload, so this is the only place
    the difference is still visible."""
    gis = _Gis()

    await _run(gis, registry, attempt_key='msg-1')
    second = await _run(gis, registry, attempt_key='msg-1')

    assert second['reused_run_from_registry'] == 'run-1'


def test_a_retry_and_a_re_ask_are_different_keys():
    """The composition, stated on its own. Everything else in the key describes
    the question; only this describes the request."""
    assert _key(attempt_key='msg-1').value == _key(attempt_key='msg-1').value
    assert _key(attempt_key='msg-1').value != _key(attempt_key='msg-2').value


def test_a_caller_with_no_request_identity_keys_as_it_always_did():
    """`None` is a value like any other, so a programmatic caller degrades to
    the old input-only key rather than to no idempotency at all. The adapter
    logs it, because falling back silently is the shape of the defect."""
    assert _key(attempt_key=None).value == _key(attempt_key=None).value
    assert _key(attempt_key=None).value != _key(attempt_key='msg-1').value


@pytest.mark.asyncio
async def test_without_a_registry_every_command_starts_a_run(registry):
    """The old behaviour, kept reachable and kept tested: `None` is what an
    unwritable DATA_DIR produces, and it must still work."""
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
    """`begin_attempt` was keyed on the `run_id` parameter alone, so a run
    reached through the key arrived with run_id=None and was written into the
    shadow A/B dataset as a first attempt. The comparison would have been
    counting resumes as fresh runs."""
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
    """Resuming a named run is the caller saying which run they mean. The key
    must not second-guess it."""
    gis = _Gis()

    result = await _run(gis, registry, run_id='run-99')

    assert result['run_id'] == 'run-99'
    assert gis.started == 0


@pytest.mark.asyncio
async def test_a_reused_run_is_not_refused_because_gis_renamed_the_object(registry):
    """The regression that made the first version of the reuse guard unusable.

    GIS sets `state.object_name` to `resolved.name or object_name`, and its
    resolver casefolds, folds `ё` to `е` and strips `площадь`/`участок`/`объект`
    before matching. The guard compared that byte-for-byte against what the user
    typed, so it fired on the ordinary path: the first command worked and every
    repeat was refused forever -- worse than no idempotency, because only the
    retries fail and the first success hides it.
    """
    gis = _Gis(object_name='Лекын-Тальбейский')  # GIS's canonical form, not the typed one

    first = await _run(gis, registry)
    second = await _run(gis, registry)

    assert first['run_id'] == second['run_id']
    assert gis.started == 1


def test_two_users_asking_the_same_question_do_not_share_a_run():
    """The run collects KB, GIS and web evidence as the requesting user, bounded
    by their grants. The binding is one deployment-wide directory, so without the
    requester in the key the second asker is handed the first asker's evidence --
    including whatever they could see and the asker cannot."""
    assert _key(requester_id='user-1').value != _key(requester_id='user-2').value


def test_an_unattributed_key_is_refused_rather_than_shared():
    with pytest.raises(Exception, match='requesting user'):
        _key(requester_id='')


@pytest.mark.asyncio
async def test_no_requester_means_no_reuse_rather_than_a_shared_binding(registry):
    """Degrade the safe way. If the adapter cannot say who is asking, the run
    behaves as it did before idempotency existed instead of binding a key that
    every caller would match."""
    gis = _Gis()

    await _run(gis, registry, requester_id=None)
    await _run(gis, registry, requester_id=None)

    assert gis.started == 2


@pytest.mark.asyncio
async def test_a_reused_run_resolved_to_another_project_is_refused(registry):
    registry.record(_key(project_id='prj-2'), 'run-1')
    gis = _Gis()  # resolves to prj-1

    with pytest.raises(Exception, match='refusing to return it'):
        await _run(gis, registry, project_id='prj-2')


@pytest.mark.asyncio
async def test_a_failed_start_binds_nothing(registry):
    """A key bound to a run that never started can never be satisfied and can
    never be retried."""

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


# -- the race, with no lock, which is how production runs ------------------


@pytest.mark.asyncio
async def test_two_callers_racing_produce_one_binding_and_one_abandoned_run(registry):
    """No `CaptureLock` is passed in production -- there is no Redis here and a
    lock invented for the occasion would be a second thing that can expire.
    `record` binding atomically is what settles it: the loser is told which run
    won and reports its own as abandoned rather than answering with it.

    Genuinely concurrent, through `asyncio.gather`. The first version awaited
    `resolve_run` twice in sequence, so the second call short-circuited on its
    very first `registry.find` and never reached the callable that held the
    entire race -- it was asserting that a second command reuses a binding,
    which is a different property, already covered above.
    """
    both_started = asyncio.Event()
    started = []

    async def start(name):
        started.append(name)
        if len(started) == 1:
            # Hold the first caller inside `start` until the second has passed
            # both of its registry reads and reached its own start.
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
    """Both callers pass the first read, both start, and only one can bind.
    The other must hand back the winner's run and say what it left behind --
    an orphaned GIS run is a real thing an operator will count."""

    class _RacingRegistry(FileRunRegistry):
        def __init__(self, root):
            super().__init__(root)
            self.reads = 0

        def find(self, key):
            self.reads += 1
            # Empty for both of this caller's reads; the other caller binds
            # in between this one's start and its record.
            if self.reads == 2:
                super().record(key, 'run-from-the-winner')
                return None
            return super().find(key)

    registry = _RacingRegistry(tmp_path / 'runs')

    resolution = await resolve_run(_key(), registry=registry, start=lambda: 'run-mine')

    assert resolution.run_id == 'run-from-the-winner'
    assert resolution.abandoned_run_id == 'run-mine'
    assert resolution.joined_existing is True


# -- GT-GIS-01: run_mode reaches GIS ---------------------------------------


@pytest.mark.asyncio
async def test_clean_is_what_gis_is_asked_for_when_the_caller_says_nothing(registry):
    """The default at every layer. A caller that says nothing gets a run built
    from its own evidence, which is the answer to "fill this object again"."""
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


# -- the KB collection scope reaches GIS ------------------------------------


@pytest.mark.asyncio
async def test_the_configured_kb_scope_is_recorded_on_the_run(registry):
    """The configured allowlist, sent at start because that is when it is known
    and complete. It is not a trace of what the specialist searched: that call
    returns a string and its tool results never come back structurally, so no
    layer in this architecture holds the answer."""
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
    """Three states, not two. `unconfigured` is a claim that the corpus was
    every collection the requesting user could read; a caller that never
    mentioned the field has not made that claim, and recording it for them is
    the same substitution that defaulted a silent `run_mode` to `clean`."""
    gis = _Gis()

    await _run(gis, registry)

    start = next(c for c in gis.calls if c['action'] == 'start')
    assert start['kb_scope_status'] is None
    assert start['kb_configured_collections'] == []


def test_the_adapter_states_the_scope_it_can_see(monkeypatch):
    """`unknown` is for a caller too old to have the field. Open WebUI is not
    that caller -- it reads the variable -- so it asserts whichever of the two
    facts is true, including the unwelcome one."""
    from open_webui.tools.geotizer import _kb_scope
    from open_webui.utils.kb_collection_scope import KB_COLLECTION_ALLOWLIST_ENV

    monkeypatch.delenv(KB_COLLECTION_ALLOWLIST_ENV, raising=False)
    assert _kb_scope() == {'kb_scope_status': 'unconfigured', 'kb_configured_collections': []}

    monkeypatch.setenv(KB_COLLECTION_ALLOWLIST_ENV, '["geo-a","geo-b"]')
    assert _kb_scope() == {
        'kb_scope_status': 'configured',
        'kb_configured_collections': ['geo-a', 'geo-b'],
    }


def test_a_clean_run_and_a_carry_forward_run_are_different_runs():
    """They answer different questions over the same inputs. Sharing a binding
    would hand a clean request back the carried card it asked to avoid."""
    assert _key(run_mode='clean').value != _key(run_mode='carry_forward').value


# -- GT-GIS-01: a run_id that resolves to nothing --------------------------


class _GisWithNoSuchRun(_Gis):
    """GIS as it behaves when the run volume no longer has the state.

    `raises` picks which of the two shapes: the HTTP client raising on a 404, or
    a 200 carrying a not-found body -- both reach the workflow and neither used
    to be distinguishable from a transport fault.
    """

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
    """§3.3. The model was handed a `run_id` it could not resolve and had no
    word for what the user actually wanted, so it asked them to supply another
    one. The refusal now carries the two operations that exist."""
    gis = _GisWithNoSuchRun(raises=raises)

    with pytest.raises(GeotizerOrchestrationError) as refusal:
        await _run(gis, registry, run_id='run-that-was-deleted')

    message = str(refusal.value)
    assert message == UNRESOLVABLE_RUN_ID
    assert 'Omit run_id' in message, 'the way to start a new run is not named'
    assert 'carry_forward' in message, 'the way to keep the old values is not named'


@pytest.mark.asyncio
async def test_an_unresolvable_run_id_does_not_quietly_become_a_fresh_run(registry):
    """The refusal is the point. Falling back to `start` would answer a resume
    request with a different run under a different id, which is the silent
    substitution §5 rules out -- and it would do it while the user still thinks
    they are looking at the run they named."""
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
    """The narrow half of `_run_is_missing`, and the reason it is narrow.

    Telling someone their run is gone when GIS is down throws away a run that is
    still there: they start over, the old one is never finalized, and the work
    it did is lost to a message about a fault that lasted thirty seconds. The
    transport error propagates unchanged so the adapter reports it as what it is.
    """
    gis = _GisWithNoSuchRun(raises=True, error=error)

    with pytest.raises(Exception) as failure:  # noqa: PT011 - the type is the assertion
        await _run(gis, registry, run_id='run-1')

    assert UNRESOLVABLE_RUN_ID not in str(failure.value)
    assert error in str(failure.value)


def test_a_healthy_state_is_not_read_as_a_missing_run_because_of_its_contents():
    """The other direction of the same narrowness, and the one a body scan gets
    wrong.

    A run state says `not_found` on every field it could not fill -- 339 of them
    on the card that started all of this -- and `404` falls out of any long hex
    string by chance. Reading the whole document for either would report the
    healthiest possible reply as a run that does not exist.
    """
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


# -- the adapter's wiring, which nothing else reaches ----------------------


@pytest.mark.asyncio
async def test_the_adapter_passes_the_real_user_and_files_into_the_identity(monkeypatch, tmp_path):
    """The only place a real user id enters the run key, and it had no test.

    Everything above builds identities by calling `geotizer_run_identity`
    directly, so a `fill_geotizer` that passed the wrong field -- or nothing --
    would leave all of it green while every production run shared one key.
    """
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
        # The seam returns the caller and the parsed PRODUCER_KIND_MAP valve; a
        # bare `None` unpacks into a TypeError that `fill_geotizer` catches and
        # renders as a terminal envelope, so `_capture` would never run and every
        # assertion below would fail on a missing key instead of a wrong one.
        return None, {}

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
    # And the pieces compose into a key that reflects both.
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


# -- the identity itself ---------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_records_of_one_key_give_both_callers_the_winner(registry):
    """Exercises the link path itself, which the gather test above does not.

    That test races `resolve_run`, and both callers reach `record` only if the
    scheduler interleaves them that way. This one calls `record` twice directly,
    which is the operation the O_EXCL-to-os.link rewrite changed, and asserts
    the property the rewrite exists for: the second caller is told which run won
    rather than silently overwriting it or reading a half-written file.
    """
    registry.record(_key(), 'run-winner')

    with pytest.raises(ValueError, match='already bound'):
        registry.record(_key(), 'run-loser')

    assert registry.find(_key()) == 'run-winner'
    # And the binding was readable at every moment, which is what the empty-file
    # window broke: a reader between create and write got zero bytes.
    assert json.loads((registry.root / f'{_key().digest}.json').read_text(encoding='utf-8'))['run_id'] == 'run-winner'


def test_an_unpinned_request_is_scoped_by_the_object_name():
    key = _key()

    assert key.project_id == 'object:Лекын-Тальбейская площадь'
    assert key.artifact_set == ('geotizer_object',)


def test_a_pinned_request_is_scoped_by_the_project():
    assert _key(project_id='prj-1').project_id == 'prj-1'


def test_an_object_scope_can_never_be_read_as_a_project_id():
    """`object:` is the marker. Without it a synthetic scope and a real GIS
    project id are the same string, and a project literally named after its
    object would collide with the unpinned request for it."""
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
    """Each of these changes what the run looks at or what it will accept. A
    key that ignored one would hand back a workbook built for a different
    question."""
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
        {'type': 'file', 'name': 'map.png'},          # no id anywhere
        'map.png',                                     # not even a mapping
    ],
)
def test_an_attachment_of_any_shape_changes_the_run(item):
    """`__files__` is `metadata['files']` verbatim and the items are not one
    shape. The first version read `item['id']`, so anything nesting or omitting
    it produced an empty string, got filtered out, and left the key identical to
    the no-attachment case -- replaying the earlier workbook and never opening
    the map, which is the exact defect putting attachments in the key was for."""
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
    """Stated rather than assumed: the fingerprint is per id *path*, so the same
    file arriving as `id` and as `file.id` reads as two sources. That direction
    is safe -- it starts a fresh run rather than replaying a stale one -- and it
    is here so the behaviour is a decision instead of a surprise."""
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
    """`project_id + artifact_set + frozen_inputs_hash`, and the stored record
    keeps all three readable -- a directory of digests is unusable otherwise."""
    registry.record(_key(), 'run-1')

    stored = json.loads((tmp_path / 'geotizer_runs' / f'{_key().digest}.json').read_text(encoding='utf-8'))

    assert set(stored['key']) == {'project_id', 'artifact_set', 'frozen_inputs_hash'}
    assert stored['run_id'] == 'run-1'
    assert stored['key']['frozen_inputs_hash'] == _key().frozen_inputs_hash


def test_the_identity_is_formed_the_same_way_by_hand():
    """Guards the composition itself: if `geotizer_run_identity` quietly dropped
    an input, every test above would still agree with it."""
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
                'attempt_key': 'msg-1',
                'rag': None,
                'kb_scope': {'status': None, 'collections': []},
            }
        ),
    )

    assert _key() == expected


def test_the_kb_collection_scope_is_part_of_the_identity():
    """A run bounded to the configured geology collections and a run that fell
    through to the fifty most recently touched knowledge bases answered
    different questions. Reusing the second's card for the first hands back the
    unpinned corpus the allowlist was configured to stop, under a fresh
    request that asked for the opposite."""
    scoped = _key(kb_scope_status='configured', kb_configured_collections=('geo-a', 'geo-b'))

    assert scoped.value != _key(kb_scope_status='unconfigured').value
    assert scoped.value != _key().value
    assert scoped.value != _key(kb_scope_status='configured', kb_configured_collections=('geo-a',)).value


# -- the wedged key, and what bounds it -------------------------------------


@pytest.mark.asyncio
async def test_a_wedged_binding_no_longer_blocks_the_next_request(registry):
    """The P1, confirmed rather than assumed.

    An unreadable binding refuses its own key forever -- `find` raises rather
    than returning `None`, deliberately, because reading a corrupt binding as
    absent would start the second run the mechanism exists to prevent. Before
    request identity that was permanent for the object: every later command
    produced the same key and hit the same file, so one corrupt byte took the
    object out of service.

    It is now bounded by the request. The wedged key belongs to one tool call;
    the next user message keys differently and runs. No expiry and no repair
    path is needed, because nothing durable is blocked -- and neither was added,
    since a sweep that deleted bindings it could not read would be the
    `forget()` call `test_nothing_in_the_repository_calls_forget` exists to
    forbid.
    """
    wedged = _key(attempt_key='msg-wedged')
    registry.root.mkdir(parents=True, exist_ok=True)
    (registry.root / f'{wedged.digest}.json').write_bytes(b'')
    gis = _Gis()

    # The tool call that owns the wedged key stays refused, however often it is
    # retried, and leaks no run.
    for _ in range(3):
        with pytest.raises(RunRegistryUnavailable):
            await _run(gis, registry, attempt_key='msg-wedged')
    assert gis.started == 0

    # The next user message is a different key and is served.
    result = await _run(gis, registry, attempt_key='msg-next')

    assert result['run_id'] == 'run-1'
    assert gis.started == 1
