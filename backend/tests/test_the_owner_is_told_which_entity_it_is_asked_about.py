"""An entity-scoped chunk's owner is given the entity inventory its rules can ask for.
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
    """A scope with no licence yields an empty inventory."""
    from open_webui.services.artifacts.geotizer.owner_envelope import entity_inventory

    assert entity_inventory(scope) == []


def test_a_resource_chunk_carries_the_inventory():
    """A chunk with a `licence_area`-scoped row carries the licence entity."""
    context = _context(_batch(47), _scope())

    assert [entry['entity_id'] for entry in context['entity_inventory']] == [LICENCE]


def test_a_chunk_that_asks_for_no_entity_carries_none():
    """A chunk with no entity-scoped row carries no `entity_inventory`."""
    context = _context(_batch(1), _scope())

    assert 'entity_inventory' not in context


def test_an_entity_scoped_chunk_with_no_licence_carries_an_empty_inventory():
    """An entity-scoped chunk in a run with no licence carries an empty
    `entity_inventory`."""
    context = _context(_batch(47), _scope(licence_id=''))

    assert context['entity_inventory'] == []


def test_the_context_still_carries_what_it_carried_before():
    """The context still carries the object name, the run id and the batch."""
    context = _context(_batch(47), _scope())

    assert context['object_name'] == 'Нявленга'
    assert context['run_id'] == 'c0455027'
    assert context['batch']['batch_id'] == 'KB-RESOURCE-TECH'


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
    """The owner prompt states when `not_applicable` applies to an entity-scoped row."""
    from open_webui.services.artifacts.geotizer.prompts import _owner_prompt

    prompt = _owner_prompt(
        context=_context(_batch(47), _scope()),
        attempt=1,
        feedback=None,
        previous_output='',
    )

    assert 'not_applicable' in prompt
    assert 'different scope' in prompt


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
