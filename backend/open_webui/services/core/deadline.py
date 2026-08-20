"""A wall-clock bound on a whole fill, checked rather than enforced.

Five things bound a fill today and none of them bounds the fill. A completion,
a tool call and a specialist each bound one unit of work, and Open WebUI's
request timeout bounds the caller's patience -- which is not the same thing at
all: when it fires, a tool call already running in the event loop is not
cancelled, `gis_service` is a separate process that never hears about it, and
the user gets an error with no state, no card and no artefacts. A fill makes
around seventy-five specialist calls inside one request, so the case this
leaves open is the one where nothing individually times out and the fill still
never ends.

Two properties make this a backstop rather than a budget, and both are
structural rather than a matter of picking a good number:

  - it is **checked, never enforced**. Nothing here cancels anything. There is
    no `wait_for` around the run, so work already in flight finishes; expiry
    only stops the next specialist call from being made.
  - it is checked **between units** -- between batches, and between chunks
    inside a batch -- so the granularity of the overshoot is one chunk, not one
    fill.

`None` and zero mean no deadline, which is what a caller that sets nothing
gets. A deadline that has never been configured must not be a deadline of
zero.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class FillDeadline:
    """Whether a fill may still start new work.

    `now` is injected so a test can drive expiry without sleeping. It is read
    on every call rather than sampled once: a deadline that latched its answer
    would report the state of the world at construction time, which for a
    six-hour bound is the one moment it is guaranteed not to have expired.
    """

    __slots__ = ('seconds', '_now', '_started')

    def __init__(
        self,
        seconds: float | None = None,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.seconds = float(seconds) if seconds else 0.0
        self._now = now
        self._started = now()

    @property
    def configured(self) -> bool:
        return self.seconds > 0

    def elapsed(self) -> float:
        return max(0.0, self._now() - self._started)

    def expired(self) -> bool:
        return self.configured and self.elapsed() >= self.seconds
