"""An id that cannot be used is named and skipped. It is never refused.

`grep_knowledge_files` and `query_knowledge_files` are shared by every model on
the contour. Upstream's bare `continue` past an unresolvable id is the defect
this file exists for: a mistyped collection id produced exactly the reply an
empty corpus produces -- fewer hits, no error, no log line -- and the two are
opposite diagnoses, one a character to fix and the other a corpus to fill.

**The refusals that stood here belonged to `KB_COLLECTION_ALLOWLIST`, and it
is gone.** A deployment-wide permitted set could only subtract from what Open
WebUI's access control had already decided per user -- role, then ownership,
then grants, on every call -- and it contradicted the rule the per-run scope
exists to express: collections are attached by the user in chat, per run, and
must not be hardcoded, remembered between runs, or promoted to a permanent
permitted set. An attachment is a statement about this run, not a grant.

The fence and the alarm were one function. Removing both would have left
neither, so the alarm stayed and lost its condition: every unusable id is now
named, on every contour, exactly as an unconfigured one already had it. The
four cases below were the unconfigured half of this file and are now the whole
of it.

`test_the_naming_is_what_produces_the_diagnosis` deletes `_skip_unresolvable`'s
body and requires the log assertion to break, because a test that has never
seen the behaviour absent proves only that the current code is the current
code.

**These are behavioural, not marker-based, on purpose.** Both functions are
large, active upstream bodies with fork logic threaded through them -- the
highest-conflict surface in the fork. A merge that rewrites a function body
takes any `# GEOTIZER-SEAM` marker with it and a marker count still passes.
An assertion about what the function *does* fails.
"""

from __future__ import annotations

import pytest

from open_webui.tools.builtin import query_knowledge_files

from test_kb_collection_scope import (  # noqa: F401 - the `kb` fixture
    USER,
    _AccessGrants,
    _Knowledge,
    _Knowledges,
    _request,
    kb,
)


def attached(*ids):
    return [{'type': 'collection', 'id': kid} for kid in ids]


async def query(kb_state, *, knowledge, model_knowledge, grants=()):
    kb_state.install(_Knowledges(knowledge), grants=_AccessGrants(grants))
    return await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=model_knowledge,
    )


@pytest.mark.asyncio
async def test_an_id_that_does_not_exist_is_skipped_and_the_others_still_search(kb):
    """The case a refusal broke. Upstream searched the remaining collections;
    the gated fork searched none and returned an error, on any contour that had
    the variable set."""
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a')],
        model_knowledge=attached('deleted-kb', 'geo-a'),
    )

    assert 'scope_fault' not in result
    assert kb.queried == [['geo-a']]


@pytest.mark.asyncio
async def test_an_unreadable_id_is_skipped_and_the_others_still_search(kb):
    """A shared model referencing a collection only some users can read returns
    partial results per user, which is Open WebUI's own answer: the grant check
    is per user on every call, and the skip is what carries that answer through
    rather than replacing it with an error."""
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a'), _Knowledge('locked', user_id='someone-else')],
        model_knowledge=attached('locked', 'geo-a'),
    )

    assert 'scope_fault' not in result
    assert kb.queried == [['geo-a']]


@pytest.mark.asyncio
async def test_no_ids_at_all_is_the_upstream_fall_through(kb):
    """Unchanged, and now unbounded by anything but access control: with
    nothing attached, the search enumerates every collection the user can read.

    This is why the recording is not optional. `searched_collections` and
    `result_collection_ids` are what make this call visible on `run_log.json`
    afterwards -- there is no longer a fence that would have stopped it."""
    registry = kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[],
    )

    assert registry.searched_everything == 1


@pytest.mark.asyncio
async def test_the_skip_is_logged_so_a_mistyped_id_is_still_diagnosable(kb, caplog):
    """The alarm, on its own now. It names the id and says what was wrong with
    it, which is the whole difference between a typo and an empty corpus."""
    with caplog.at_level('INFO', logger='open_webui.tools.builtin'):
        await query(
            kb,
            knowledge=[_Knowledge('geo-a')],
            model_knowledge=attached('typoed-kb', 'geo-a'),
        )

    logged = ' '.join(record.getMessage() for record in caplog.records)
    assert 'typoed-kb' in logged
    assert 'does not exist' in logged
    # And never the name of the removed variable, which would send a reader to
    # a setting that no longer exists.
    assert 'KB_COLLECTION_ALLOWLIST' not in logged


@pytest.mark.asyncio
async def test_the_naming_is_what_produces_the_diagnosis(kb, caplog, monkeypatch):
    """Verification by deletion. With `_skip_unresolvable` emptied -- upstream's
    bare `continue`, which is what the code did before any of this -- the search
    must still succeed and the id must vanish from the log.

    Both halves are asserted. If only the log went quiet the skip might have
    become a refusal; if only the search still worked the naming might be
    coming from somewhere else and this test would be watching nothing."""
    import open_webui.tools.builtin as builtin

    monkeypatch.setattr(builtin, '_skip_unresolvable', lambda *_args, **_kwargs: None)

    with caplog.at_level('INFO', logger='open_webui.tools.builtin'):
        result = await query(
            kb,
            knowledge=[_Knowledge('geo-a')],
            model_knowledge=attached('typoed-kb', 'geo-a'),
        )

    logged = ' '.join(record.getMessage() for record in caplog.records)
    assert 'typoed-kb' not in logged, 'the naming should come from _skip_unresolvable'
    assert 'scope_fault' not in result
    assert kb.queried == [['geo-a']], 'and the skip itself is upstream, not ours'
