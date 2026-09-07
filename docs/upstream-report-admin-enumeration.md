# Upstream report: the enumeration branch drops the admin bypass every named lookup honours

Ready to file against `open-webui/open-webui`. **Not filed from this repository** —
see "Status" at the bottom.

Verified unfixed at **v0.11.3**, the latest release at the time of writing, and at
the pinned **v0.11.1** this fork builds on.

## What happens

An admin account sees only the knowledge bases it created, through every tool that
has to *find* a collection before reading one. Naming a collection by id works;
enumerating does not. The same account, in the same request, gets two different
answers about what it may read.

## Why

Every knowledge search in `backend/open_webui/tools/` has two shapes.

**Named** — the id is checked one row at a time, and role is in the check:

```python
user_role == 'admin'
or kb.user_id == user_id
or await AccessGrants.has_access(
    user_id=user_id, resource_type='knowledge',
    resource_id=kb.id, permission='read',
    user_group_ids=set(user_group_ids),
)
```

**Enumerated** — the corpus comes from a SQL filter:

```python
filter={'query': '', 'user_id': user_id, 'group_ids': user_group_ids}
```

`AccessGrants.has_permission_filter` reads exactly two keys off that dict, `user_id`
and `group_ids`, and turns them into «owner OR has a matching grant»
(`backend/open_webui/models/access_grants.py`). Ownership and grants are in both
shapes. **Role is in only the first.**

The routers already handle this. `GET /api/v1/knowledge/` at
`backend/open_webui/routers/knowledge.py` omits both keys for an admin:

```python
if not user.role == 'admin' or not BYPASS_ADMIN_ACCESS_CONTROL:
    if groups:
        filter['group_ids'] = [group.id for group in groups]
    filter['user_id'] = user.id
```

With neither key present, `has_permission_filter` builds no principal condition and
returns the query untouched. The tools never picked this up.

## Affected branches

| File | Function | Enumeration call |
|---|---|---|
| `tools/builtin.py` | `list_knowledge_bases` | `Knowledges.search_knowledge_bases` |
| `tools/builtin.py` | `search_knowledge_bases` | `Knowledges.search_knowledge_bases` |
| `tools/builtin.py` | `search_knowledge_files`, `else` arm | `Knowledges.search_knowledge_files` |
| `tools/builtin.py` | `grep_knowledge_files`, `else` arm | `Knowledges.search_knowledge_bases` |
| `tools/builtin.py` | `query_knowledge_files`, `else` arm | `Knowledges.search_knowledge_bases` |
| `tools/builtin.py` | `query_knowledge_bases` (semantic) | `Knowledges.search_knowledge_bases` |
| `tools/knowledge_fs.py` | `_get_accessible_kb_ids`, `else` arm | `Knowledges.search_knowledge_bases` |

In `search_knowledge_files` and `_get_accessible_kb_ids` the correct check sits
three lines above the branch that omits it, inside the same function.

`search_notes` in `tools/builtin.py` has the same shape for a different resource:
it passes `user_id` plus `group_ids` with no role, while `view_note` beside it
short-circuits on `__user__.get('role') != 'admin'`. Not fixed here; reported for
completeness.

## Suggested fix

Omit both keys for an admin, exactly as the routers do — in the query, not per row.
A per-row check afterwards would be one round trip per collection, and `limit` is
applied by the database after the filter, so rows would be dropped behind the cut
rather than admitted.

## One question for maintainers

The routers gate this bypass on `BYPASS_ADMIN_ACCESS_CONTROL`; the named lookups in
the tools do not consult it and pass on bare `user_role == 'admin'`. Making the
enumeration match the named lookup beside it means bare role; making it match the
router means the flag. **They should agree, and today they do not** — which is the
larger inconsistency, and the one worth deciding before the smaller one is patched.
The flag defaults to true, so on any deployment that has not set it the two are
identical.

## Status

Not filed. This repository's GitHub access is scoped to its own organisation, and
filing on a third-party project is an outward-facing action to be taken
deliberately rather than as a side effect of a fork patch. The text above is ready
to paste.

The fork carries the fix meanwhile, declared in `scripts/check_upstream_footprint.py`
for both files and held by
`backend/tests/test_an_admin_enumerates_what_an_admin_may_read.py`. **The
declaration for `tools/knowledge_fs.py` should end when this is fixed upstream** —
that is the expiry the fork patch exists to have.
