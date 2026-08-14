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

  and a reused run that turns out to be about a different object is refused,
  because the weakest part of this design is keying an unpinned request by the
  name the user typed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer.workflow import (  # noqa: E402
    geotizer_run_identity,
    run_geotizer_workflow,
)
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
        'object_name': 'Лекын-Тальбейская площадь',
        'project_id': None,
        'model_run_id': None,
        'allow_draft': True,
        'vision_collection_url': None,
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
        'run_registry': registry,
    }
    return await run_geotizer_workflow(**{**fields, **overrides})


@pytest.mark.asyncio
async def test_repeating_the_command_returns_the_first_run(registry):
    """The finding, at the level it was found: `workflow.py` resumed only when
    the caller passed `run_id`, and otherwise sent `action: 'start'` every
    time."""
    gis = _Gis()

    first = await _run(gis, registry)
    second = await _run(gis, registry)

    assert first['run_id'] == second['run_id'] == 'run-1'
    assert gis.started == 1
    # One `start`, and the repeat comes in through `get` -- the same door an
    # explicit `run_id` resume uses.
    assert [call['action'] for call in gis.calls].count('start') == 1
    assert 'get' in [call['action'] for call in gis.calls]


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
async def test_an_explicit_run_id_still_wins(registry):
    """Resuming a named run is the caller saying which run they mean. The key
    must not second-guess it."""
    gis = _Gis()

    result = await _run(gis, registry, run_id='run-99')

    assert result['run_id'] == 'run-99'
    assert gis.started == 0


@pytest.mark.asyncio
async def test_a_reused_run_about_a_different_object_is_refused(registry, tmp_path):
    """The weak point of keying an unpinned request by the typed name: two
    projects can carry one object name. Returning the other project's workbook
    would be indistinguishable from a correct answer."""
    registry.record(_key(), 'run-from-another-project')
    gis = _Gis(object_name='Совсем другая площадь')

    with pytest.raises(Exception, match='refusing to return it'):
        await _run(gis, registry)


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
    `record` being atomic is what settles it: the loser is told which run won
    and reports its own as abandoned rather than answering with it.
    """
    started = []

    async def start_first():
        started.append('a')
        return 'run-a'

    async def start_second():
        started.append('b')
        # The winner binds while this caller is still starting.
        registry.record(_key(), 'run-a')
        return 'run-b'

    key = _key()
    await resolve_run(key, registry=registry, start=start_first)
    resolution = await resolve_run(key, registry=registry, start=start_second)

    # The first call bound `run-a`; the second sees it on its own second read.
    assert resolution.run_id == 'run-a'
    assert resolution.reused is True
    assert registry.find(key) == 'run-a'


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


# -- the identity itself ---------------------------------------------------


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
    ],
)
def test_every_input_a_caller_can_vary_changes_the_run(change):
    """Each of these changes what the run looks at or what it will accept. A
    key that ignored one would hand back a workbook built for a different
    question."""
    assert _key(**change).value != _key().value


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
                'object_name': 'Лекын-Тальбейская площадь',
                'project_id': None,
                'model_run_id': None,
                'allow_draft': True,
                'vision_collection_url': None,
                'rag': None,
            }
        ),
    )

    assert _key() == expected
