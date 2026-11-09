"""What a person attached to this message, read out of `__files__`.

`query_knowledge_files` and `grep_knowledge_files` fall through to *every*
knowledge base the requesting user can read whenever nothing scopes them --
`limit=50` for the first, `limit=200` for the second, both ordered
`updated_at DESC` by `models/knowledge.py`. Run `b389ffe6` searched four
food-extrusion collections that way. Worse, the window moves: any edit to any
knowledge base on the contour, by anyone, for any reason, reorders it, so two
GeoTeaser runs hours apart searched different corpora and nothing recorded the
difference. The 67-cell spread between those runs is that churn, not model
variance.

This module reads the scope the run already carries. Open WebUI pushes an
attached knowledge base into `__files__` as `{'type': 'collection', 'id': ...}`
beside the files, so the ids arrive on every run; they were being discarded.

**There was a second source here and it is gone.** `KB_COLLECTION_ALLOWLIST`
was a deployment-wide permitted set, read from the environment and unioned in.
It could only subtract from what Open WebUI's access control had already
decided per user -- role, then ownership, then grants, on every call -- which
is how a specialist came to search four food-extrusion collections while the
operator could see the geology corpus as admin. And it contradicted the rule
this scope exists to express: collections are attached by the user in chat,
per run, and must not be hardcoded, remembered between runs, or promoted to a
permanent permitted set. A user can misclick an attachment, and a collection
that was right last month can be outdated today. An attachment is a statement
about this run, not a grant.

So an unattached run is not scoped, and the two builtins keep the behaviour
they have for every caller on the contour. They are shared by every model
rather than owned by GeoTeaser, which is why the remedy for an unscoped search
is now the recording of it -- `searched_collections`, `result_collection_ids`
and the per-file collection map on `run_log.json` -- rather than a fence in
front of it. That is the opposite trade from `PRODUCER_KIND_MAP`, which
refuses to run when it is unset, and the difference is deliberate: that valve
configures one GeoTeaser run, these are two general tools.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from typing import Any

#: How Open WebUI tags a knowledge base inside `__files__`.
COLLECTION_ENTRY_TYPE = 'collection'


def _entry_type(item: Any) -> str:
    return str((item or {}).get('type') or '').strip().lower() if isinstance(item, Mapping) else ''


def visual_source_files(files: Sequence[Any] | None) -> list[Any]:
    """`__files__` minus the knowledge collections: what the vision path may have.

    One list, two consumers, each taking its own kind. `__files__` mixes files a
    person attached with knowledge bases they attached, and the vision path took
    the whole list as visual sources -- so attaching a collection for retrieval
    made the run demand the Geological Vision tool and abort before its first
    batch. Pre-existing and dormant, because until the scope work nobody had a
    reason to attach one.

    A collection can legitimately hold images, so the inference was not absurd.
    But the vision path wants fetchable file ids, and `vision_collection_url`
    already says "these images are the visual evidence" explicitly. Keeping that
    explicit is what stops a document collection attached for retrieval being
    silently enrolled as imagery.

    Entries verbatim, and anything that is not a collection is kept -- including
    shapes with no `type` at all. The filter's job is to remove one known kind,
    never to decide what counts as a file.
    """
    return [item for item in (files or ()) if _entry_type(item) != COLLECTION_ENTRY_TYPE]


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
        if _entry_type(item) != COLLECTION_ENTRY_TYPE:
            continue
        # `id` verbatim. A collection row nests plenty else; reading one field
        # is what threw the ids away the first time.
        collection_id = str(item.get('id') or '').strip()
        if collection_id and collection_id not in seen:
            seen.append(collection_id)
    return tuple(seen)


def resolve_kb_scope(files: Sequence[Any] | None = None) -> dict[str, Any]:
    """The KB collection scope for this run: the collections the user attached.

    One source, and deliberately one. There was a second -- a deployment-wide
    `KB_COLLECTION_ALLOWLIST`, unioned in here -- and it violated the rule this
    scope exists to express: collections are attached per run, in chat, and
    must not be hardcoded, remembered between runs, or promoted to a permanent
    permitted set. A user can misclick an attachment, and a collection that was
    right last month can be outdated today. An attachment is a statement about
    this run, not a grant.

    It also subtracted from access control rather than adding to it. Open WebUI
    already decides what a user may read -- role, then ownership, then grants
    including group membership, on every call -- and a contour-wide permitted
    set could only narrow that, which is how a specialist came to search four
    food-extrusion collections while the operator could see the geology corpus
    as admin.

    Only this adapter may read the attachments: `services/` imports no
    `open_webui` and no environment. `unconfigured` is asserted rather than
    left absent because this side genuinely knows -- `unknown` is for a caller
    too old to have the field at all.
    """
    resolved: list[str] = []
    for collection_id in attached_collection_ids(files):
        if collection_id not in resolved:
            resolved.append(collection_id)

    # Two keys, and only two. `run_geotizer_workflow` takes them by name,
    # `GeotizerFillRequest` is `extra="forbid"`, and `GeotizerState` has no
    # field for anything else -- a third key here raises `TypeError` before the
    # request is even built. This mattered while the ids had two possible
    # origins and per-entry provenance had nowhere to land; with the allowlist
    # gone there is one origin, so the constraint costs nothing.
    return {
        'kb_scope_status': 'configured' if resolved else 'unconfigured',
        'kb_configured_collections': resolved,
    }
