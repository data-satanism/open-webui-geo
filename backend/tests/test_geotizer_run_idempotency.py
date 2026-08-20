"""CORE-BOUNDARY-01 action 6: the persistent run key.

`project_id + artifact_set + frozen_inputs_hash` identifies a run. Repeating
the command with the same key must return the original one, and an expired
Redis lock must not be able to produce a second.
"""

from __future__ import annotations

import pytest

from open_webui.services.core.idempotency import (
    ARTIFACT_KINDS,
    IdempotencyError,
    RunKey,
    canonical_json,
    frozen_inputs_hash,
    resolve_run,
    run_key,
)

INPUTS = {
    'sources': {'snapshot_id': 'src-2026-08-12', 'item_count': 41},
    'gis': {'snapshot_id': 'gis-2026-08-10'},
    'index': {'snapshot_id': 'idx-7'},
    'contract_versions': {'dossier_schema': 1, 'cpr_requirements': 'cpr_requirements.v1'},
    'acl_decision': 'partial',
}


class Registry:
    """The persistent half. Deliberately refuses a rebind."""

    def __init__(self):
        self.rows: dict[str, str] = {}
        self.reads = 0

    def find(self, key: RunKey) -> str | None:
        self.reads += 1
        return self.rows.get(key.value)

    def record(self, key: RunKey, run_id: str) -> None:
        existing = self.rows.get(key.value)
        if existing is not None and existing != run_id:
            raise AssertionError(f'key already bound to {existing}')
        self.rows[key.value] = run_id


class Lock:
    def __init__(self, *, grants: bool = True):
        self.grants = grants
        self.acquired = 0
        self.released = 0

    def acquire(self, key: RunKey) -> bool:
        self.acquired += 1
        return self.grants

    def release(self, key: RunKey) -> None:
        self.released += 1


@pytest.fixture
def key():
    return run_key(
        project_id='lekyn-talbeyskaya',
        artifact_set=['cpr_readiness', 'geotizer_object'],
        frozen_inputs_hash=frozen_inputs_hash(INPUTS),
    )


# -- forming the key -------------------------------------------------------


def test_the_key_is_the_three_parts_the_assignment_names(key):
    assert key.project_id == 'lekyn-talbeyskaya'
    assert key.artifact_set == ('cpr_readiness', 'geotizer_object')
    assert len(key.frozen_inputs_hash) == 64


def test_the_artifact_set_is_a_set(key):
    """Asking for the CPR and the workbook is one request whichever order they
    were named in, and asking twice for one artefact is not two requests."""
    other = run_key(
        project_id='lekyn-talbeyskaya',
        artifact_set=['geotizer_object', 'cpr_readiness', 'cpr_readiness'],
        frozen_inputs_hash=frozen_inputs_hash(INPUTS),
    )

    assert other == key
    assert other.value == key.value


def test_a_different_artifact_set_is_a_different_run(key):
    other = run_key(
        project_id='lekyn-talbeyskaya',
        artifact_set=['cpr_readiness'],
        frozen_inputs_hash=frozen_inputs_hash(INPUTS),
    )

    assert other.value != key.value


def test_inputs_hash_the_same_however_the_mapping_was_built():
    reordered = dict(reversed(list(INPUTS.items())))

    assert frozen_inputs_hash(reordered) == frozen_inputs_hash(INPUTS)


def test_a_changed_input_is_a_different_run(key):
    moved = {**INPUTS, 'gis': {'snapshot_id': 'gis-2026-08-11'}}

    assert frozen_inputs_hash(moved) != key.frozen_inputs_hash


def test_a_nested_change_still_changes_the_hash():
    deeper = {**INPUTS, 'sources': {'snapshot_id': 'src-2026-08-12', 'item_count': 42}}

    assert frozen_inputs_hash(deeper) != frozen_inputs_hash(INPUTS)


def test_canonical_json_is_stable_and_compact():
    assert canonical_json({'b': 1, 'a': [2, 3]}) == '{"a":[2,3],"b":1}'


def test_non_ascii_survives_the_canonical_form():
    assert 'Лекын' in canonical_json({'object': 'Лекын'})


@pytest.mark.parametrize(
    'kwargs,message',
    [
        ({'project_id': '  '}, 'project_id is required'),
        ({'artifact_set': []}, 'at least one artefact'),
        ({'artifact_set': ['a_nice_pdf']}, 'unknown artefact'),
        ({'frozen_inputs_hash': 'nope'}, 'sha256 digest'),
        ({'frozen_inputs_hash': 'A' * 64}, 'sha256 digest'),
    ],
)
def test_a_key_that_cannot_be_formed_is_refused(kwargs, message):
    base = {
        'project_id': 'lekyn-talbeyskaya',
        'artifact_set': ['cpr_readiness'],
        'frozen_inputs_hash': frozen_inputs_hash(INPUTS),
    }
    with pytest.raises(IdempotencyError, match=message):
        run_key(**{**base, **kwargs})


def test_empty_inputs_are_refused():
    with pytest.raises(IdempotencyError, match='non-empty'):
        frozen_inputs_hash({})


def test_every_artifact_kind_is_the_manifest_vocabulary():
    """Mirrors the artifact_set enum in GMM's dossier manifest schema. A name
    invented here would produce a key no manifest could describe."""
    assert ARTIFACT_KINDS == (
        'audit',
        'cpr_readiness',
        'expert_action_list',
        'gap_list',
        'geotizer_object',
        'source_report',
    )


# -- resolving a run -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_first_call_starts_a_run(key):
    registry = Registry()

    result = await resolve_run(key, registry=registry, start=lambda: 'run-1')

    assert result.run_id == 'run-1'
    assert result.reused is False
    assert registry.rows[key.value] == 'run-1'


@pytest.mark.asyncio
async def test_repeating_the_command_returns_the_original_run(key):
    registry = Registry()
    starts = []

    def start():
        starts.append(1)
        return f'run-{len(starts)}'

    first = await resolve_run(key, registry=registry, start=start)
    second = await resolve_run(key, registry=registry, start=start)

    assert first.run_id == second.run_id == 'run-1'
    assert second.reused is True
    assert len(starts) == 1


@pytest.mark.asyncio
async def test_an_expired_lock_does_not_produce_a_second_run(key):
    """The case the assignment names. The lock is gone -- acquire succeeds
    again because nothing is holding it -- and the key is what stops the
    duplicate."""
    registry = Registry()
    lock = Lock()
    await resolve_run(key, registry=registry, start=lambda: 'run-1', lock=lock)

    second = await resolve_run(
        key,
        registry=registry,
        start=lambda: pytest.fail('a second run was started'),
        lock=lock,
    )

    assert second.run_id == 'run-1'
    assert second.reused is True


@pytest.mark.asyncio
async def test_no_lock_at_all_still_gives_one_run(key):
    """Redis being unavailable must not turn one run into two."""
    registry = Registry()
    await resolve_run(key, registry=registry, start=lambda: 'run-1', lock=None)

    second = await resolve_run(
        key,
        registry=registry,
        start=lambda: pytest.fail('a second run was started'),
        lock=None,
    )

    assert second.run_id == 'run-1'


@pytest.mark.asyncio
async def test_losing_the_race_after_the_winner_recorded_joins_that_run(key):
    """The registry is empty on the first read and bound by the second: the
    other caller finished in between. That is the read that decides."""

    class RacingRegistry(Registry):
        def find(self, lookup):
            found = super().find(lookup)
            self.rows[lookup.value] = 'run-from-the-winner'
            return found

    registry = RacingRegistry()
    lock = Lock(grants=False)

    result = await resolve_run(
        key,
        registry=registry,
        start=lambda: pytest.fail('should not start'),
        lock=lock,
    )

    assert result.run_id == 'run-from-the-winner'
    assert result.reused is True
    assert result.joined_existing is True


@pytest.mark.asyncio
async def test_losing_the_race_before_the_winner_recorded_is_refused_not_duplicated(key):
    """The only outcome that is an error. Starting anyway would be the
    duplicate the key exists to prevent."""
    registry = Registry()
    lock = Lock(grants=False)

    with pytest.raises(IdempotencyError, match='capture lock'):
        await resolve_run(
            key,
            registry=registry,
            start=lambda: pytest.fail('should not start'),
            lock=lock,
        )

    assert registry.rows == {}


@pytest.mark.asyncio
async def test_the_registry_is_read_before_and_under_the_claim(key):
    registry = Registry()
    lock = Lock()

    await resolve_run(key, registry=registry, start=lambda: 'run-1', lock=lock)

    assert registry.reads == 2
    assert lock.acquired == 1


@pytest.mark.asyncio
async def test_the_lock_is_released_even_when_starting_raises(key):
    registry = Registry()
    lock = Lock()

    def start():
        raise RuntimeError('GIS was unreachable')

    with pytest.raises(RuntimeError):
        await resolve_run(key, registry=registry, start=start, lock=lock)

    assert lock.released == 1
    assert registry.rows == {}


@pytest.mark.asyncio
async def test_a_failed_start_leaves_the_key_free_for_a_retry(key):
    registry = Registry()
    attempts = []

    def start():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('GIS was unreachable')
        return 'run-2'

    with pytest.raises(RuntimeError):
        await resolve_run(key, registry=registry, start=start)
    result = await resolve_run(key, registry=registry, start=start)

    assert result.run_id == 'run-2'
    assert result.reused is False


@pytest.mark.asyncio
async def test_a_key_already_bound_answers_without_touching_the_lock(key):
    """The cheap path, and the common one: the second request for the same
    artefacts over the same inputs never reaches Redis at all."""
    registry = Registry()
    registry.rows[key.value] = 'run-1'
    lock = Lock(grants=False)

    result = await resolve_run(key, registry=registry, start=lambda: 'run-2', lock=lock)

    assert result.run_id == 'run-1'
    assert lock.acquired == 0
    assert lock.released == 0


def test_the_digest_form_is_fixed_width_and_agrees_with_the_value(key):
    import hashlib

    assert key.digest == hashlib.sha256(key.value.encode('utf-8')).hexdigest()
    assert len(key.digest) == 64
