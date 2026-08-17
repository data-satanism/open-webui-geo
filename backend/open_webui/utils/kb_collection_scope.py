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
from collections.abc import Mapping, Sequence

from typing import Any

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


def attached_collection_ids(files: Sequence[Any] | None) -> tuple[str, ...]:
    """Collection ids a person attached to this chat message, in attach order.

    Open WebUI already carries them. Attaching a knowledge base in the chat
    pushes the whole knowledge row with `type: 'collection'` alongside the
    files, so `__files__` holds `{'type': 'collection', 'id': ...}` entries
    beside `{'type': 'file', ...}` ones -- the same discriminator every
    `__model_knowledge__` consumer in `tools/builtin.py` already reads. Nothing
    here needs new plumbing; the ids arrive on every run and were discarded.

    That is the scope defect in one sentence. `Проект ГРР Лекын-Тальбейское
    2025.pdf` lives in a collection the requester attached, and the specialist
    searched the fifty most recently touched knowledge bases instead.

    Deduplicated in first-seen order rather than sorted, because the resolved
    order is the search order and a scope that iterates a set is the same
    unpinned corpus in a smaller disguise.
    """
    seen: list[str] = []
    for item in files or ():
        if not isinstance(item, Mapping):
            continue
        if str(item.get('type') or '').strip().lower() != 'collection':
            continue
        # `id` verbatim. A collection row nests plenty else; reading one field
        # is what threw the ids away the first time.
        collection_id = str(item.get('id') or '').strip()
        if collection_id and collection_id not in seen:
            seen.append(collection_id)
    return tuple(seen)


def resolve_kb_scope(files: Sequence[Any] | None = None) -> dict[str, Any]:
    """The KB collection scope for this run, and where each entry came from.

    Two sources, unioned, because they answer different questions and change on
    different clocks. The deployment allowlist is a contour-wide bound an
    operator sets and a model cannot forge. The attachments are this object's
    own collections, chosen by the person starting the run, different for every
    project and maintained by nobody.

    Attachments come first in the resolved order. A run scoped to the object's
    own dossier should search it before the reference shelf.

    Only this adapter may read either: `services/` imports no `open_webui` and
    no environment. `unconfigured` is asserted rather than left absent because
    this side genuinely knows -- `unknown` is for a caller too old to have the
    field at all, and claiming it here would throw away the one thing this
    layer can state with certainty.
    """
    attached = attached_collection_ids(files)
    configured = kb_collection_allowlist()

    resolved: list[str] = []
    for collection_id in list(attached) + list(configured):
        if collection_id not in resolved:
            resolved.append(collection_id)

    # Per-entry provenance -- which ids arrived attached and which from the
    # allowlist -- is NOT sent. It has nowhere to land: `run_geotizer_workflow`
    # takes these two by name, `GeotizerFillRequest` is `extra="forbid"`, and
    # `GeotizerState` has no field for it. Adding a third key here raises
    # `TypeError` before the request is even built. Recording it needs a field
    # on the GIS state and is a separate change across that boundary; until
    # then the origin of an id is recoverable only from the union rule above.
    return {
        'kb_scope_status': 'configured' if resolved else 'unconfigured',
        'kb_configured_collections': resolved,
    }
