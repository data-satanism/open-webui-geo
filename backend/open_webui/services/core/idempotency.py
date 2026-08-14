"""The persistent identity of a dossier run.

CORE-BOUNDARY-01 action 6. A run is identified by

    project_id + artifact_set + frozen_inputs_hash

and repeating the command with the same key returns the original run rather
than producing a second one.

**A Redis lock is not this key.** A lock stops two starts racing each other for
a few seconds; it expires, and the moment it does, a retry that consults only
the lock starts a fresh run over the same inputs. The assignment names that
case directly -- "Redis lock expired and a duplicate run was created" -- and
the answer is that the lock guards the *capture* while the key guards the
*identity*. The key outlives the lock, the process and the container.

This module is artefact-neutral: `artifact_set` is a set of names, and nothing
here knows what a CPR section or a GeoTeaser field is. The protocols are
defined here and implemented in the effect shell, so the pure core can decide
whether a run is new without being able to write anything.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

# The artefacts a run may be asked for. Mirrors the `artifact_set` enum in
# GMM's `contracts/evidence/project-dossier-manifest.schema.json`; a name
# outside it is a caller error, not a new artefact.
ARTIFACT_KINDS = (
    'audit',
    'cpr_readiness',
    'expert_action_list',
    'gap_list',
    'geotizer_object',
    'source_report',
)

SHA256_LENGTH = 64


class IdempotencyError(ValueError):
    """Raised when a run key cannot be formed from what the caller supplied."""


def canonical_json(payload: Any) -> str:
    """One byte string per value, whatever order it arrived in.

    Sorted keys and no incidental whitespace, because the hash of the frozen
    inputs has to survive a dict being built in a different order by a
    different code path.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def frozen_inputs_hash(inputs: Mapping[str, Any]) -> str:
    """The digest of everything a run was frozen against.

    Source, GIS and index snapshot ids, contract versions, ACL decision -- the
    caller decides what belongs; this decides how it is hashed. Two runs whose
    inputs differ in any recorded way get different hashes and are different
    runs, which is the point: reusing a run whose inputs moved would serve a
    stale answer under a fresh request.
    """
    if not isinstance(inputs, Mapping) or not inputs:
        raise IdempotencyError('frozen inputs must be a non-empty mapping')
    return hashlib.sha256(canonical_json(inputs).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class RunKey:
    project_id: str
    artifact_set: tuple[str, ...]
    frozen_inputs_hash: str

    @property
    def value(self) -> str:
        """The persistent key, as it is stored and compared."""
        return canonical_json(
            {
                'project_id': self.project_id,
                'artifact_set': list(self.artifact_set),
                'frozen_inputs_hash': self.frozen_inputs_hash,
            }
        )

    @property
    def digest(self) -> str:
        """A fixed-width form, for a store that wants a short column."""
        return hashlib.sha256(self.value.encode('utf-8')).hexdigest()


def run_key(
    *,
    project_id: str,
    artifact_set: Iterable[str],
    frozen_inputs_hash: str,
) -> RunKey:
    if not str(project_id or '').strip():
        raise IdempotencyError('project_id is required')

    # Sorted and de-duplicated: asking for the CPR and the workbook is the same
    # request whichever order they were named in, and asking twice for the same
    # artefact is not a different request.
    artifacts = tuple(sorted({str(name) for name in artifact_set}))
    if not artifacts:
        raise IdempotencyError('artifact_set must name at least one artefact')
    unknown = [name for name in artifacts if name not in ARTIFACT_KINDS]
    if unknown:
        raise IdempotencyError(f'unknown artefact(s): {unknown}')

    digest = str(frozen_inputs_hash or '')
    if len(digest) != SHA256_LENGTH or not all(c in '0123456789abcdef' for c in digest):
        raise IdempotencyError('frozen_inputs_hash must be a lowercase sha256 digest')

    return RunKey(
        project_id=str(project_id).strip(),
        artifact_set=artifacts,
        frozen_inputs_hash=digest,
    )


class RunRegistry(Protocol):
    """The persistent mapping from key to run. Outlives the lock."""

    def find(self, key: RunKey) -> str | None:
        """The run id recorded for this key, or None."""

    def record(self, key: RunKey, run_id: str) -> None:
        """Bind this key to this run. Recording an already-bound key with a
        different run id is a programming error the implementation must
        refuse -- the key is the identity, not a cache entry."""


class CaptureLock(Protocol):
    """A short-lived, best-effort claim on starting a run.

    It exists so two concurrent requests do not both do the expensive work. It
    is allowed to expire, to be lost on a restart, and to be unavailable
    entirely; none of those may produce a second run.
    """

    def acquire(self, key: RunKey) -> bool:
        """True if this caller may proceed to start the run."""

    def release(self, key: RunKey) -> None: ...


@dataclass(frozen=True)
class RunResolution:
    run_id: str
    reused: bool
    # True when the lock was held by someone else and the key was already
    # bound, i.e. the other caller finished first. Recorded so a caller can
    # tell "your run" from "someone else's run that answers your question".
    joined_existing: bool = False
    # A run this caller started and then gave up, because another caller bound
    # the key first. Reported rather than swallowed: it is a real run sitting in
    # the state store that nothing will ever finish, and an operator counting
    # runs needs to know why there is one more than there are answers.
    abandoned_run_id: str | None = None


async def _resolved(value: Any) -> Any:
    """`start` may be a plain callable or a coroutine function.

    The only reason this function is a coroutine at all: in production `start`
    posts `action: 'start'` to the GIS service, and that is `await`ed. The
    registry and the lock stay synchronous because a run key is a few hundred
    bytes of local state, and making a protocol async to accommodate one caller
    that does not need it costs every implementation an `async def`.
    """
    if inspect.isawaitable(value):
        return await value
    return value


async def resolve_run(
    key: RunKey,
    *,
    registry: RunRegistry,
    start,
    lock: CaptureLock | None = None,
) -> RunResolution:
    """Return the run for `key`, starting one only if none exists.

    The registry is consulted first and last. Between those two reads the lock
    may or may not have been held; either way the second read is what decides,
    so an expired lock costs a wasted `start` at most -- never a second
    recorded run.

    With no lock at all -- which is the production configuration, because there
    is no Redis here and a fake lock would be worse than none -- two callers can
    both reach `start`. That is the wasted start the docstring above allows, and
    the binding is what settles it: `record` is atomic, the loser is told which
    run won, and it returns that one with its own named in `abandoned_run_id`.
    Never two answers; at worst one orphaned run.
    """
    existing = registry.find(key)
    if existing is not None:
        return RunResolution(run_id=existing, reused=True)

    acquired = lock.acquire(key) if lock is not None else True
    try:
        # Read again under the claim. A caller that lost the race, or whose
        # lock had already expired while another caller finished, must return
        # that run rather than start its own.
        existing = registry.find(key)
        if existing is not None:
            return RunResolution(run_id=existing, reused=True, joined_existing=not acquired)
        if not acquired:
            raise IdempotencyError('another caller holds the capture lock for this key and has not recorded a run yet')
        run_id = await _resolved(start())
        try:
            registry.record(key, run_id)
        except Exception:
            # A registry that refuses a rebind is doing what the protocol asks.
            # Whether this caller lost a race or the store is broken is decided
            # by what is bound now -- not by the exception type, which every
            # implementation spells differently.
            winner = registry.find(key)
            if winner is None or winner == run_id:
                raise
            return RunResolution(
                run_id=winner,
                reused=True,
                joined_existing=True,
                abandoned_run_id=run_id,
            )
        return RunResolution(run_id=run_id, reused=False)
    finally:
        if lock is not None and acquired:
            lock.release(key)


__all__ = [
    'ARTIFACT_KINDS',
    'CaptureLock',
    'IdempotencyError',
    'RunKey',
    'RunRegistry',
    'RunResolution',
    'canonical_json',
    'frozen_inputs_hash',
    'resolve_run',
    'run_key',
]
