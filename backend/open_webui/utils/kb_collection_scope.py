"""The collection allowlist the shared knowledge-base builtins search within.

`query_knowledge_files` and `grep_knowledge_files` fall through to *every*
knowledge base the requesting user can read whenever nothing scopes them --
`limit=50` for the first, `limit=200` for the second, both ordered
`updated_at DESC` by `models/knowledge.py`. Run `b389ffe6` searched four
food-extrusion collections that way. Worse, the window moves: any edit to any
knowledge base on the contour, by anyone, for any reason, reorders it, so two
GeoTeaser runs hours apart searched different corpora and nothing recorded the
difference. The 67-cell spread between those runs is that churn, not model
variance.

This module holds the one part of the remedy that lives in a repository: a
deployment-wide allowlist, read from the environment and injected server-side
by `get_builtin_tools`. It cannot be supplied by a model.

**The default is empty and empty means "not configured".** These two builtins
are shared by every model on the contour rather than owned by GeoTeaser, so an
unconfigured deployment keeps exactly the behaviour it has today instead of
losing knowledge search entirely. That is the opposite trade from
`PRODUCER_KIND_MAP`, which refuses to run when it is unset, and the difference
is deliberate: that valve configures one GeoTeaser run, this configures every
caller of two general tools.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from open_webui.utils.geotizer_rag_runtime import parse_collection_names

KB_COLLECTION_ALLOWLIST_ENV = 'KB_COLLECTION_ALLOWLIST'


def kb_collection_allowlist(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """The configured collection ids, in configured order, deduplicated.

    Ordered rather than a set, and returned as a tuple, because the resolved
    order *is* the search order: a scope that iterates a set is the same
    unpinned corpus the allowlist exists to remove, in a smaller disguise.

    Read on every call rather than frozen at import, so a contour that changes
    the variable does not need the reason for its stale corpus explained to it
    a second time.
    """
    environ = os.environ if environ is None else environ
    return parse_collection_names(environ.get(KB_COLLECTION_ALLOWLIST_ENV, ''))
