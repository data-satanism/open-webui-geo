"""Shared GeoTeaser exception types.

CORE-BOUNDARY-01 action 1. These were declared in two places -- the
orchestration module and the Workspace-facing tool -- so the tool had to import
the orchestration module to raise a GIS failure. They belong to the pure core:
no exception type here knows anything about Open WebUI.

## Drift from the production lineage

The production `geoteaser 2.2.0` Tool carries six exception types with a
different hierarchy and different casing:

    geoteaserOrchestrationError(ValueError)
      geoteaserError
        geoteaserArgumentError
        geoteaserRuntimeError
        geoteaserGisError
        geoteaserBudgetError

This repository carries two, and `GeotizerGisError` derives directly from
`GeotizerOrchestrationError` rather than through an intermediate
`geoteaserError`. The names are not renamed to match: the divergence is one of
the 62 `merge` rows in `GMM/operations/gt-conv-01/semantic-diff.json` and
belongs to whoever reconciles the two lineages. Renaming here would hide the
decision instead of making it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class GeotizerOrchestrationError(ValueError):
    """Raised when the deterministic orchestration contract is violated."""


class GeotizerGisError(GeotizerOrchestrationError):
    """Structured GIS failure that must not be reinterpreted by the parent LLM.

    **`details` is whatever the GIS side returned, and that is three shapes.**
    `workflow.py` raises this with `error or violations or state`: a mapping, a
    list of strings, or a plain string. The constructor took `dict(details)`
    and so accepted exactly one of them.

    An error class that raises while constructing an error is the worst place
    for a type assumption. `dict('...')` iterates a string into characters and
    fails on the first, `dict([...])` reads a list element as a key-value pair
    and fails on that -- and either way the traceback names `errors.py` and the
    thing the GIS side actually objected to is destroyed before anyone reads
    it. That is what run `475dc4f5`'s `dictionary update sequence element #0
    has length 1` was, chased across several rounds while an AST sweep of every
    `dict(x)` on the start-to-first-batch path found nothing -- correctly,
    because the call is here, on a path only reached when GIS returns a
    failure.

    The number in that message is the length of the first element, which says
    which shape arrived: a realistic violations list gives the length of its
    first sentence, and **`length 1` means a bare string** (or, implausibly, a
    list of one-character strings). So `475dc4f5` was `error` as a string
    rather than `violations` as a list. Both crashed; only one did on that run.

    Normalising rather than refusing is deliberate. A boundary whose job is to
    carry a failure outward must not have a failure mode of its own, and the
    caller passing an awkward shape is exactly the moment it is needed.
    """

    def __init__(self, details: Any = None):
        if isinstance(details, Mapping):
            self.details = dict(details)
        elif isinstance(details, (list, tuple)):
            # `violations` verbatim. Wrapped under its own key rather than
            # stringified, because the list is the finding and joining it into
            # a sentence is the loss this class exists to prevent.
            self.details = {'violations': list(details)}
        elif details is None:
            self.details = {}
        else:
            self.details = {'message': str(details)}
        super().__init__(json.dumps(self.details, ensure_ascii=False, default=str))


def ensure_state_can_continue(state: Mapping[str, Any]) -> None:
    status = state.get('workflow_status')
    if status == 'needs_input':
        raise GeotizerOrchestrationError(json.dumps(state.get('error') or state, ensure_ascii=False))
    if status == 'validation_failed':
        raise GeotizerOrchestrationError(json.dumps(state.get('violations') or state, ensure_ascii=False))
    if status not in {'collecting', 'finalized'}:
        raise GeotizerOrchestrationError(f'Unsupported GeoTeaser workflow_status: {status!r}')


__all__ = [
    'GeotizerGisError',
    'GeotizerOrchestrationError',
    'ensure_state_can_continue',
]
