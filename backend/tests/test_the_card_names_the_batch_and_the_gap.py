"""Tests that the batch status line names the batch's section label, and that
the card states how many template sections it cannot reach."""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    StatusSettings,
    template_section_line,
)


def test_the_batch_line_names_the_section():
    line = StatusSettings(language='ru').batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'Геотизер: пакет 3 из 8 — геологическое строение'


def test_a_service_that_sends_no_label_gives_the_line_it_always_gave():
    """A missing or blank label leaves the ordinal-only batch line."""
    settings = StatusSettings(language='ru')

    assert settings.batch_line(n=3, total=8, batch_id='KB-GEO', producer='kb') == (
        'Геотизер: пакет 3 из 8'
    )
    assert settings.batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label=None
    ) == 'Геотизер: пакет 3 из 8'
    assert settings.batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='   '
    ) == 'Геотизер: пакет 3 из 8'


def test_the_label_survives_the_technical_valve():
    """At `technical` verbosity the label precedes the batch id and producer."""
    line = StatusSettings(language='ru', verbosity='technical').batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'Геотизер: пакет 3 из 8 — геологическое строение — KB-GEO (kb)'


def test_the_label_survives_a_missing_denominator():
    line = StatusSettings(language='ru').batch_line(
        n=3, total=None, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'Геотизер: пакет 3 — геологическое строение'


def test_the_english_line_carries_the_label_untranslated():
    """The English batch line carries the Russian label untranslated."""
    line = StatusSettings(language='en').batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'GeoTeaser: batch 3 of 8 — геологическое строение'


def test_the_workflow_hands_the_line_the_label_it_received():
    """The workflow passes the batch's `label` to the status line."""
    import asyncio
    import json

    from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

    from test_geotizer_orchestration import batch, envelope

    value = batch()
    value['label'] = 'геологическое строение'
    lines: list[str] = []

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'run-label',
                'object_name': 'Лекын',
                'datacube': {},
                'batches_total': 1,
                'next_batch': value,
            }
        if payload['action'] == 'submit_batch':
            return {'workflow_status': 'collecting', 'run_id': 'run-label', 'next_batch': None}
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-label',
            'xlsx': {'download_path': '/geotizer/files/run-label/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.role == 'contributor':
            return 'bounded evidence'
        return json.dumps(envelope(), ensure_ascii=False)

    async def emitter(event):
        data = (event or {}).get('data') or {}
        text = (data.get('description') or data.get('content') or '')
        if text:
            lines.append(str(text))

    asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            event_emitter=emitter,
            status=StatusSettings(language='ru'),
        )
    )

    assert any('геологическое строение' in line for line in lines), lines


def test_the_card_says_how_much_of_the_template_it_cannot_reach():
    line = template_section_line(
        {'template_sections': {'readable': True, 'unmapped_count': 25, 'unmapped': ['3.6']}}
    )

    assert '25' in line
    assert 'Domain Reviewer' in line


def test_a_template_the_service_could_not_read_says_nothing():
    """An unreadable template gives no line, whatever count it carries."""
    assert template_section_line(
        {'template_sections': {'readable': False, 'unmapped_count': None, 'unmapped': []}}
    ) == ''
    assert template_section_line(
        {'template_sections': {'readable': False, 'unmapped_count': 25, 'unmapped': []}}
    ) == ''


def test_a_fully_mapped_template_says_nothing():
    assert template_section_line(
        {'template_sections': {'readable': True, 'unmapped_count': 0, 'unmapped': []}}
    ) == ''


def test_a_service_older_than_the_field_says_nothing():
    assert template_section_line({}) == ''
    assert template_section_line({'template_sections': None}) == ''


def test_the_card_reads_the_key_the_service_writes():
    """The adapter calls `run_detail_lines`, and `terminal` calls
    `template_section_line(final)`."""
    from pathlib import Path

    import open_webui.tools.geotizer as adapter

    import open_webui.services.artifacts.geotizer.terminal as terminal

    assert 'run_detail_lines(' in Path(adapter.__file__).read_text(encoding='utf-8')
    assert 'template_section_line(final)' in Path(terminal.__file__).read_text(
        encoding='utf-8'
    )
