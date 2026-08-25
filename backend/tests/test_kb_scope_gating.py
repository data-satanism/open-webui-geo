"""The strict refusal belongs to the allowlist, not to every caller.

`grep_knowledge_files` and `query_knowledge_files` are shared by every model on
the contour. The file's own docstring commits to leaving an unconfigured caller
alone -- «an unset variable must not brick knowledge search for callers who
never asked to be scoped» -- and ten refusals ran regardless of configuration,
which contradicted it. On any contour, a model whose `meta.knowledge` named a
since-deleted collection went from «search the rest» to «search nothing and
return an error».

Four cases, and the pair that matters is the second half: those are the ones
that fail if the gate is removed. Verified that way rather than asserted --
`test_the_gate_is_what_makes_the_unset_cases_pass` deletes it and requires
them to break, because a test that has never seen the behaviour absent proves
only that the current code is the current code.

**These are behavioural, not marker-based, on purpose.** Both functions are
large, active upstream bodies with fork logic threaded through them -- the
highest-conflict surface in the fork. A merge that rewrites a function body
takes any `# GEOTIZER-SEAM` marker with it and a marker count still passes.
An assertion about what the function *does* fails.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from open_webui.tools.builtin import query_knowledge_files
from open_webui.utils.kb_collection_scope import KB_COLLECTION_ALLOWLIST_ENV

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


async def query(kb_state, *, knowledge, model_knowledge, allowlist=None, grants=()):
    kb_state.install(_Knowledges(knowledge), grants=_AccessGrants(grants))
    return await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=model_knowledge,
        __collection_allowlist__=allowlist or (),
    )


# -- allowlist SET: the strict refusal, which does not change ----------------


@pytest.mark.asyncio
async def test_set_and_id_outside_the_allowlist_is_refused_naming_the_id(kb):
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a'), _Knowledge('other')],
        model_knowledge=attached('other'),
        allowlist=('geo-a',),
    )

    payload = json.loads(result)
    assert payload['scope_fault'] == 'collection'
    assert payload['id'] == 'other'
    assert KB_COLLECTION_ALLOWLIST_ENV in payload['error']


@pytest.mark.asyncio
async def test_set_and_id_missing_is_refused_naming_the_id(kb):
    """One bad entry fails the whole call under an allowlist, and that is
    correct: a partial allowlist searches a corpus nobody configured and
    reports it as a complete answer."""
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a')],
        model_knowledge=attached('geo-a', 'deleted-kb'),
        allowlist=('geo-a', 'deleted-kb'),
    )

    payload = json.loads(result)
    assert payload['id'] == 'deleted-kb'
    assert 'does not exist' in payload['error']
    assert kb.queried == [], 'nothing may be searched once the scope is broken'


@pytest.mark.asyncio
async def test_set_and_id_unreadable_is_refused_naming_the_id(kb):
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a'), _Knowledge('locked', user_id='someone-else')],
        model_knowledge=attached('geo-a', 'locked'),
        allowlist=('geo-a', 'locked'),
    )

    payload = json.loads(result)
    assert payload['id'] == 'locked'
    assert 'no read grant' in payload['error']


# -- allowlist UNSET: upstream's behaviour, with the diagnosis added ---------


@pytest.mark.asyncio
async def test_unset_and_id_missing_is_skipped_and_the_others_still_search(kb):
    """The case the ungated refusal broke. Upstream searched the remaining
    collections; the fork searched none and returned an error."""
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a')],
        model_knowledge=attached('deleted-kb', 'geo-a'),
    )

    assert 'scope_fault' not in result
    assert kb.queried == [['geo-a']]


@pytest.mark.asyncio
async def test_unset_and_id_unreadable_is_skipped_and_the_others_still_search(kb):
    """A shared model referencing a collection only some users can read
    returned partial results per user upstream, and an error for the rest
    under the ungated refusal."""
    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a'), _Knowledge('locked', user_id='someone-else')],
        model_knowledge=attached('locked', 'geo-a'),
    )

    assert 'scope_fault' not in result
    assert kb.queried == [['geo-a']]


@pytest.mark.asyncio
async def test_unset_and_no_ids_at_all_is_the_upstream_fall_through(kb):
    """Unchanged: with nothing attached and nothing configured, the search
    enumerates every collection the user can read, exactly as before."""
    registry = kb.install(_Knowledges([_Knowledge('geo-a'), _Knowledge('geo-b')]))

    await query_knowledge_files(
        'кровля пласта',
        __request__=_request(),
        __user__=USER,
        __model_knowledge__=[],
        __collection_allowlist__=(),
    )

    assert registry.searched_everything == 1


@pytest.mark.asyncio
async def test_the_skip_is_logged_so_a_mistyped_id_is_still_diagnosable(kb, caplog):
    """Upstream's bare `continue` is the defect this work identified: a
    mistyped id produces exactly the reply an empty corpus produces. An
    unconfigured contour keeps upstream's result and gains the diagnosis."""
    with caplog.at_level('INFO', logger='open_webui.tools.builtin'):
        await query(
            kb,
            knowledge=[_Knowledge('geo-a')],
            model_knowledge=attached('typoed-kb', 'geo-a'),
        )

    logged = ' '.join(record.getMessage() for record in caplog.records)
    assert 'typoed-kb' in logged
    assert KB_COLLECTION_ALLOWLIST_ENV in logged


@pytest.mark.asyncio
async def test_the_gate_is_what_makes_the_unset_cases_pass(kb, monkeypatch):
    """Verification by deletion. With the gate removed -- `_refuse_or_skip`
    always refusing, which is what the code did before this change -- the two
    unset cases must fail. If they still pass, the gate is not what is
    producing the behaviour and these tests are watching something else."""
    import open_webui.tools.builtin as builtin

    monkeypatch.setattr(
        builtin,
        '_refuse_or_skip',
        lambda allowlist, kind, item_id, reason: builtin._scope_error(kind, item_id, reason),
    )

    result = await query(
        kb,
        knowledge=[_Knowledge('geo-a')],
        model_knowledge=attached('deleted-kb', 'geo-a'),
    )

    payload = json.loads(result)
    assert payload['id'] == 'deleted-kb', 'the gate removal should restore the refusal'
    assert kb.queried == [], 'and nothing should have been searched'
