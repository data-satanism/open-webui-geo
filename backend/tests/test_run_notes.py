"""Every repair this code makes to an owner envelope has to reach the card.

`_produce_valid_owner_envelope` collected repair notes in a local list and
nothing read it. `normalize_source_inventory`'s source rebuilds went in; so did
`coerce_contradictory_patch_fields`'s status overrides. Both docstrings said
the notes "are surfaced as run degradations". They were surfaced nowhere, and
the coercion's own brief asked for exactly this: "record each coercion as a run
note so a silent fix stays visible".

It is the same shape as the two defects before it -- a helper whose docstring
describes a behaviour nothing wires up -- and it was mine.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from open_webui.services.artifacts.geotizer.owner_envelope import build_batch_tasks
from open_webui.services.artifacts.geotizer.terminal import run_notes_section
from open_webui.services.artifacts.geotizer.workflow import (
    _produce_valid_owner_envelope,
    run_geotizer_workflow,
)

from test_geotizer_orchestration import batch, envelope


def _run_with(raw, notes):
    value = batch()
    owner = next(task for task in build_batch_tasks(value) if task.role == 'owner')

    async def agent_call(task, prompt, object_name, datacube):
        return raw

    return asyncio.run(
        _produce_valid_owner_envelope(
            owner=owner,
            context={'batch': value, 'contributor_evidence': [], 'accepted_field_summary': []},
            next_batch=value,
            object_name='Лекын-Талбейская площадь',
            run_id='run-notes',
            agent_call=agent_call,
            datacube=None,
            run_notes=notes,
        )
    )


def test_a_coercion_reaches_the_list_the_run_carries():
    """The patch said `filled` beside a negative marker. The card must say the
    status was overridden, because it is not the owner's answer any more."""
    raw = envelope()
    raw['patches'][0].update({'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'})
    notes: list[str] = []

    _run_with(json.dumps(raw, ensure_ascii=False), notes)

    assert notes
    assert any('not_found' in note for note in notes)


def test_the_producer_still_works_without_a_notes_list():
    """The parameter is optional, and the tests that predate it pass none."""
    result = _run_with(json.dumps(envelope(), ensure_ascii=False), None)

    assert result['patches'] == envelope()['patches']


def test_a_clean_run_records_nothing():
    """A note on every card is a note nobody reads."""
    notes: list[str] = []

    _run_with(json.dumps(envelope(), ensure_ascii=False), notes)

    assert notes == []


def test_the_section_is_absent_when_there_is_nothing_to_say():
    assert run_notes_section({}) == ''
    assert run_notes_section({'run_notes': []}) == ''
    assert run_notes_section({'run_notes': ['   ']}) == ''


def test_the_section_names_every_note():
    section = run_notes_section({'run_notes': ['первое', 'второе']})

    assert 'Ограничения этого запуска' in section
    assert 'первое' in section
    assert 'второе' in section


def test_the_workflow_attaches_the_notes_to_the_terminal_payload():
    """The step the first version of this file did not cover.

    Asserting the adapter renders `final['run_notes']` while handing it a
    `final` that already carries them proves the renderer and skips the only
    thing that could be missing: whether the workflow puts them there. Deleting
    the attachment left that test green -- the self-rebuilding pattern again,
    inside the file written about it.

    So this drives the real `run_geotizer_workflow` with a GIS stub and an
    owner that returns a patch whose status contradicts its value.
    """
    value = batch()

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-notes-e2e',
                'object_name': 'Лекын',
                'datacube': {},
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'run-notes-e2e', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-notes-e2e',
            'xlsx': {'download_path': '/geotizer/files/run-notes-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        raw = envelope()
        raw['patches'][0].update(
            {'status': 'filled', 'value': 'нет данных', 'value_origin': 'direct'}
        )
        return json.dumps(raw, ensure_ascii=False)

    final = asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
        )
    )

    assert final['workflow_status'] == 'finalized'
    assert final.get('run_notes'), 'the workflow did not carry the repair out'
    assert any('not_found' in note for note in final['run_notes'])
    # and the card shows it, which is the pair of halves the defect split
    assert 'Ограничения этого запуска' in run_notes_section(final)


def test_the_notes_survive_to_the_card_through_the_real_result(monkeypatch):
    """The half that was missing. Asserting the list is populated proves the
    repair was recorded; only driving the adapter proves a reader sees it."""
    import open_webui.tools.geotizer as adapter

    final = {
        'run_id': 'run-1',
        'object_name': 'Лекын',
        'counts': {'filled': 3, 'not_found': 1, 'requires_expert_review': 0, 'conflicted': 0},
        'fill_quality': {'strict_fill_percent': 75.0, 'target_met': False},
        'xlsx': {'download_path': '/geotizer/files/run-1/geotizer.xlsx', 'sha256': 'abc'},
        'audit': {'summary': {'failed': 0, 'warnings': 0}, 'gates': {'publication': 'blocked'}},
        'run_notes': ['f1: статус исправлен с filled на not_found.'],
    }

    async def _noop(*args, **kwargs):
        return None

    async def _pair(runtime):
        from open_webui.services.artifacts.geotizer.terminal import StatusSettings

        return (None, StatusSettings())

    async def _workflow(**kwargs):
        return final

    monkeypatch.setattr(adapter, '_user_model', _noop)
    monkeypatch.setattr(adapter, '_resolve_geotizer_callable', _noop)
    monkeypatch.setattr(adapter, '_build_agent_caller', _pair)
    monkeypatch.setattr(adapter, '_build_rag_dispatcher', lambda request, user: None)
    monkeypatch.setattr(adapter, '_build_vision_evidence_caller', _noop)
    monkeypatch.setattr(adapter, 'run_geotizer_workflow', _workflow)

    result = asyncio.run(
        adapter.fill_geotizer(
            object_name='Лекын',
            __request__=object(),
            __user__={'id': 'u1'},
            __message_id__='m1',
        )
    )

    assert 'Ограничения этого запуска' in result
    assert 'статус исправлен с filled на not_found' in result
