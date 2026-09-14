"""A rule may not require an identifier the answerer was never given.

Run `c0455027` marked thirteen cells `agent_contract_failed`. All thirteen are
rows r047, r048 and r049 of one chunk, and the violations name three of them:

    patches[5]  …r047.a06  resource field requires entity_id: set
                source_locator.entity_id to the identifier of the licence_area
                this value belongs to.

Three refused attributes failed a thirteen-cell chunk, twice, and the loop
stopped rather than spend a third attempt on an objection that states what is
wrong and not what would be right.

Which of the two readings it is was decided by measurement, not by argument.
`compact_batch_context` built the owner's context out of the object name, the
batch, the datacube, the search plan and the contributor evidence -- and no
scope. The run was bound to licence `МАГ04805БЭ` before its first batch ran,
and that number is the licence_area's identity. The owner was asked for it and
never told it.

So it is supply. The exit the rule offers -- `not_applicable`, «the object has
no entity at this level» -- would have been a false statement about a run that
has a licence, which is why taking the exit was not the fix either.

The prompt half matters as much as the supply: the same run wrote
`nyavlenga-deposit`, `nyavlenga_deposit` and `Нявленга` into `entity_id` on
cells of one deposit. An inventory nobody is told to copy verbatim produces a
fourth spelling.
"""

from __future__ import annotations

import pytest


LICENCE = 'МАГ04805БЭ'


def _scope(**changes):
    return {
        'licence_id': LICENCE,
        'object_name': 'Нявленга',
        'project_id': 'p1',
        **changes,
    }


def _batch(row_id):
    return {
        'batch_id': 'KB-RESOURCE-TECH',
        'producer': 'kb',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'fields': [
            {
                'field_key': f'geotizer_object.v1.r{row_id:03d}.a06',
                'row_id': row_id,
                'attribute_name': 'запасы',
            }
        ],
    }


def _context(batch, scope):
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        compact_batch_context,
    )

    return compact_batch_context(
        batch,
        owner_agent='kb',
        object_name='Нявленга',
        run_id='c0455027',
        datacube=None,
        contributor_evidence=(),
        object_scope=scope,
    )


# --- the inventory itself ---------------------------------------------------

def test_the_licence_area_entity_comes_from_the_scope_binding():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        LICENCE_AREA_ENTITY_SOURCE,
        entity_inventory,
    )

    entry = entity_inventory(_scope())[0]

    assert entry['entity_scope'] == 'licence_area'
    assert entry['entity_id'] == LICENCE
    assert entry['derived_from'] == LICENCE_AREA_ENTITY_SOURCE


@pytest.mark.parametrize('scope', (None, {}, {'licence_id': ''}, 'not a mapping'))
def test_a_run_with_no_licence_offers_no_licence_entity(scope):
    """An empty inventory is a true statement. A fabricated entry would be the
    defect this closes, wearing the other error."""
    from open_webui.services.artifacts.geotizer.owner_envelope import entity_inventory

    assert entity_inventory(scope) == []


# --- and what reaches the owner --------------------------------------------

def test_a_resource_chunk_carries_the_inventory():
    """r047 is `licence_area`-scoped, which is the scope the thirteen failing
    cells were refused for."""
    context = _context(_batch(47), _scope())

    assert [entry['entity_id'] for entry in context['entity_inventory']] == [LICENCE]


def test_a_chunk_that_asks_for_no_entity_carries_none():
    """The inventory travels with the chunks whose rules can ask for it. r001
    is not entity-scoped."""
    context = _context(_batch(1), _scope())

    assert 'entity_inventory' not in context


def test_an_entity_scoped_chunk_with_no_licence_carries_an_empty_inventory():
    """Empty rather than absent: «the inventory is empty» and «there is no
    inventory» send the owner to different answers, and only the first is true
    when a run has no licence."""
    context = _context(_batch(47), _scope(licence_id=''))

    assert context['entity_inventory'] == []


def test_the_context_still_carries_what_it_carried_before():
    """The addition must not cost the owner anything it already had."""
    context = _context(_batch(47), _scope())

    assert context['object_name'] == 'Нявленга'
    assert context['run_id'] == 'c0455027'
    assert context['batch']['batch_id'] == 'KB-RESOURCE-TECH'


# --- the prompt half --------------------------------------------------------

def test_the_owner_is_told_to_copy_the_supplied_id_rather_than_invent_one():
    from open_webui.services.artifacts.geotizer.prompts import _owner_prompt

    prompt = _owner_prompt(
        context=_context(_batch(47), _scope()),
        attempt=1,
        feedback=None,
        previous_output='',
    )

    assert 'entity_inventory' in prompt
    assert LICENCE in prompt
    assert 'verbatim' in prompt


def test_the_owner_is_told_what_an_absent_scope_means():
    """The rule's exit, stated where the owner reads its instructions rather
    than only inside the violation it is refused with."""
    from open_webui.services.artifacts.geotizer.prompts import _owner_prompt

    prompt = _owner_prompt(
        context=_context(_batch(47), _scope()),
        attempt=1,
        feedback=None,
        previous_output='',
    )

    assert 'not_applicable' in prompt
    assert 'different scope' in prompt


# --- and that the workflow actually hands the scope over -------------------
#
# Removing `object_scope=current_state.get('object_scope')` from
# `workflow._produce_and_submit_owner_batch` left every test above green: they
# call `compact_batch_context` directly, so the helper was verified and the
# wiring was not. That is the same trap as a spy that calls itself, and this
# test is the one that would have caught it.

def test_the_workflow_hands_the_run_s_scope_to_the_context():
    import asyncio
    import types

    from open_webui.services.artifacts.geotizer import workflow

    seen: dict[str, object] = {}

    class _Owner(types.SimpleNamespace):
        pass

    async def _collect(**kwargs):
        return _Owner(agent='kb'), ()

    def _record(next_batch, **kwargs):
        seen.update(kwargs)
        raise _Stop()

    class _Stop(Exception):
        pass

    original_collect = workflow._collect_chunk_evidence
    original_context = workflow.compact_batch_context
    workflow._collect_chunk_evidence = _collect
    workflow.compact_batch_context = _record
    try:
        asyncio.run(
            workflow._produce_and_submit_owner_batch(
                current_state={'object_scope': _scope(), 'fields': []},
                next_batch=_batch(47),
                object_name='Нявленга',
                run_id='c0455027',
                gis_call=None,
                agent_call=None,
                rag_dispatcher=None,
                datacube=None,
                knowledge_search_plan={},
                vision_evidence_call=None,
                vision_project_id=None,
            )
        )
    except _Stop:
        pass
    finally:
        workflow._collect_chunk_evidence = original_collect
        workflow.compact_batch_context = original_context

    assert seen['object_scope'] == _scope()
