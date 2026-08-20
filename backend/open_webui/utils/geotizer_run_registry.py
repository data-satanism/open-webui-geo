"""The persistent half of the run key: a file per key under `DATA_DIR`.

`services/core/idempotency.py` decides whether a run is new. It cannot store
anything -- it is in the pure core and defines `RunRegistry` as a protocol for
exactly that reason -- so until this module existed the mechanism had no
implementation, no caller, and nothing but its own unit tests. Expected result 7
asks for a *permanent* idempotency mechanism, and a protocol with no
implementation is not one.

**Why the filesystem.** The requirement is that the binding outlives the lock,
the process and the container, and `DATA_DIR` is the volume this deployment
already keeps across restarts -- `geomas_rag_shadow/` lives beside this. A
database table would outlive more, and if a migration is ever added this module
is the only thing that changes; the protocol above it and the workflow below it
do not know which it is.

**Why no lock.** `resolve_run` takes an optional `CaptureLock` and production
passes `None`. There is no Redis in this contour, and a lock invented here would
be a second thing that can expire while claiming to prevent what the key already
prevents. What stops a duplicate is `record` binding atomically: the payload is
written to a scratch file and `os.link`ed into place, so the binding appears
with its content and the first writer wins. The loser reads the winner's run id
and gives up its own. Two concurrent starts therefore cost one orphaned GIS run, never two
answers -- which is the trade `resolve_run` already documents for an expired
lock, arrived at from the other direction.

**What this deliberately does not do.** It does not delete bindings. A key whose
run GIS no longer holds is an operational fact -- the state store was wiped or
rotated -- and the caller reports it rather than clearing the binding and
starting again, because "GIS said 404" is also what a misconfigured store says,
and auto-clearing on that would manufacture the duplicate run the whole
mechanism exists to prevent. `forget` is here for an operator to call, and no
code path calls it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from open_webui.services.core.idempotency import RunKey

log = logging.getLogger(__name__)

DIRECTORY_NAME = 'geotizer_runs'

# Off is a deliberate value, not the absence of a setting: a contour that has a
# reason to want every command to start a fresh run should be able to say so
# without editing code, and the reason should be visible in its environment.
ENABLE_ENV = 'GEOMAS_RUN_IDEMPOTENCY'


class RunRegistryUnavailable(RuntimeError):
    """The registry directory cannot be used, and the caller must decide."""


class FileRunRegistry:
    """`RunKey` -> run id, one small JSON file per key, named by digest.

    The digest rather than the key: the key is canonical JSON containing an
    object name, and a file name is not a place to put user input.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: RunKey) -> Path:
        return self.root / f'{key.digest}.json'

    def find(self, key: RunKey) -> str | None:
        try:
            raw = self._path(key).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RunRegistryUnavailable(f'cannot read the run registry: {exc}') from exc
        try:
            record = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # A corrupt binding is not "no binding". Answering None here would
            # start a second run over inputs that already have one, which is the
            # single failure this module exists to prevent, so it refuses.
            #
            # A zero-byte file is the same thing and briefly had its own branch
            # returning None, on the reasoning that an empty file names no run so
            # nothing is lost by treating the key as unbound. That was wrong in
            # the worst available way. `find` answers None, `resolve_run` calls
            # `start`, GIS creates a run, `record` reaches `os.link` and gets
            # `FileExistsError` because the empty file is still there, re-reads,
            # gets None again, and raises "already bound to None". Every attempt
            # leaves one more orphaned GIS run and the key never becomes usable.
            # Refusing costs an operator one `forget`; the branch cost a run per
            # command, forever, with an error message that named no cause.
            raise RunRegistryUnavailable(
                f'the run registry entry for {key.digest[:12]} is not readable '
                f'({"empty file" if not raw.strip() else exc}). No run can be bound to this '
                f'key until it is removed: {self._path(key)}'
            ) from exc
        run_id = record.get('run_id')
        return str(run_id) if run_id else None

    def record(self, key: RunKey, run_id: str) -> None:
        """Bind, or refuse. Atomic against another process doing the same.

        Written to a scratch file first and then linked into place, because the
        binding has to become visible *with its content*, not before it.
        `os.open(..., O_CREAT | O_EXCL)` on the final path -- which is what this
        did first -- makes the create atomic and leaves the file empty until the
        write lands. A concurrent `find` in that window reads zero bytes, and
        `find` treats unparseable content as a corrupt binding and raises. So
        the loser of a race got `RunRegistryUnavailable` instead of the winner's
        run id, which is the one answer this class exists to give it.

        `os.link` is atomic and fails with `FileExistsError` if the key is
        already bound, so it keeps the property `O_EXCL` was there for: the first
        writer wins, and a second writer never silently overwrites -- which is
        how a registry becomes a cache.
        """
        if not str(run_id or '').strip():
            raise ValueError('run_id is required to bind a key')
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                'key': json.loads(key.value),
                'run_id': run_id,
                # Not read by anything. It is here for the operator looking at a
                # directory of digests and asking which of them is from today.
                'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        # `mkstemp`, not a name built from pid and thread id. Two async tasks in
        # one thread share both, so the composed name was not unique where this
        # code actually runs; and if a crash left one behind, `O_EXCL` on it
        # turned every later call into `RunRegistryUnavailable` while the
        # `finally` cheerfully deleted a scratch file this call had not created.
        # `mkstemp` is unique by construction and creates the file itself, so
        # the cleanup below can only ever remove our own.
        #
        # Same directory as the target, so the link cannot cross a filesystem.
        try:
            handle, scratch_name = tempfile.mkstemp(dir=self.root, prefix='.bind-', suffix='.tmp')
        except OSError as exc:
            raise RunRegistryUnavailable(f'cannot write the run registry: {exc}') from exc
        scratch = Path(scratch_name)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(scratch, 0o600)
            try:
                os.link(scratch, self._path(key))
            except FileExistsError:
                existing = self.find(key)
                if existing == run_id:
                    return
                raise ValueError(
                    f'run key is already bound to {existing!r}; refusing to rebind to {run_id!r}'
                ) from None
        except OSError as exc:
            raise RunRegistryUnavailable(f'cannot write the run registry: {exc}') from exc
        finally:
            try:
                scratch.unlink()
            except FileNotFoundError:
                pass

    def forget(self, key: RunKey) -> bool:
        """Drop a binding whose run no longer exists. For an operator, by hand.

        Nothing in this repository calls it, and that is the point -- see the
        module docstring. Returns whether there was anything to drop.
        """
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return False
        return True


def build_run_registry(data_dir: str | Path, environ=None) -> FileRunRegistry | None:
    """The registry for this contour, or None with a reason in the log.

    None is a supported state and the workflow treats it as "no idempotency",
    which is what every run did before this existed. A read-only `DATA_DIR`
    should degrade to the old behaviour rather than stop the tool: refusing to
    run at all would turn a missing optimisation into an outage.
    """
    environ = os.environ if environ is None else environ
    setting = str(environ.get(ENABLE_ENV, 'true')).strip().lower()
    if setting in {'0', 'false', 'no', 'off'}:
        log.info('GeoTeaser run idempotency is off by %s=%s', ENABLE_ENV, setting)
        return None

    root = Path(data_dir) / DIRECTORY_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        # A unique probe per caller. A fixed `.writable` path meant two
        # overlapping callers raced on one file: the second `unlink` raised
        # `FileNotFoundError`, the `except OSError` below read that as "DATA_DIR
        # is not writable", and idempotency switched itself off on a directory
        # that was writable all along -- for the caller that would otherwise
        # have reused a run.
        #
        # The probe links as well as writes, because `record` links. Testing
        # only writability while depending on `os.link` turns a filesystem
        # without hardlink support into an outage instead of the degradation
        # this function exists to provide: every command would reach `record`,
        # raise `RunRegistryUnavailable`, and fail -- after starting a GIS run.
        with tempfile.NamedTemporaryFile(dir=root, prefix='.probe-', suffix='.tmp') as probe:
            linked = Path(probe.name + '.link')
            os.link(probe.name, linked)
            linked.unlink()
    except OSError as exc:
        log.warning(
            'GeoTeaser run idempotency is unavailable: %s is not writable (%s). '
            'Every command will start a new run.',
            root,
            exc,
        )
        return None
    return FileRunRegistry(root)


__all__ = [
    'DIRECTORY_NAME',
    'ENABLE_ENV',
    'FileRunRegistry',
    'RunRegistryUnavailable',
    'build_run_registry',
]
