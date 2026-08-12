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
    """Structured GIS failure that must not be reinterpreted by the parent LLM."""

    def __init__(self, details: Mapping[str, Any]):
        self.details = dict(details)
        super().__init__(json.dumps(self.details, ensure_ascii=False))


__all__ = ['GeotizerGisError', 'GeotizerOrchestrationError']
