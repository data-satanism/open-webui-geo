"""Two things the card knew and did not say.

«Геотизер: пакет 3 из 8» counted ordinals. The batch is a section of the card
-- geology, licence, resources -- and the plan naming it arrives on every
progress response, so the ordinal was the one part of it carrying no
information. `assignment_policy.v3` puts a label beside each batch and
`next_batch` carries it here.

And 25 of the CPR template's 33 sections have no card block at all. That was
visible only by opening the DOCX, where it was stated twenty-five times, once
under each of them. It is not a coverage gap in the batch plan -- all 107
spreadsheet rows are owned -- it is the section-to-field mapping at 51 of 351,
and extending it is a Domain Reviewer decision.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import (
    StatusSettings,
    template_section_line,
)


# -- the batch line ----------------------------------------------------------


def test_the_batch_line_names_the_section():
    line = StatusSettings(language='ru').batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'Геотизер: пакет 3 из 8 — геологическое строение'


def test_a_service_that_sends_no_label_gives_the_line_it_always_gave():
    """`assignment_policy.v2` has no labels, so an older GIS sends none. The
    line degrades to the ordinal rather than to «— None»."""
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
    """The id and the producer are diagnostics; the label is the part a reader
    can act on. Turning diagnostics on must not push it off the line."""
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
    """It names a section of a Russian CPR template. Rendering it in English
    would name a section that does not exist."""
    line = StatusSettings(language='en').batch_line(
        n=3, total=8, batch_id='KB-GEO', producer='kb', label='геологическое строение'
    )

    assert line == 'GeoTeaser: batch 3 of 8 — геологическое строение'


def test_the_workflow_hands_the_line_the_label_it_received():
    """The wiring. A label the service sends and the workflow drops is the
    lookup-table problem with extra steps."""
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


# -- the template-gap line ---------------------------------------------------


def test_the_card_says_how_much_of_the_template_it_cannot_reach():
    line = template_section_line(
        {'template_sections': {'readable': True, 'unmapped_count': 25, 'unmapped': ['3.6']}}
    )

    assert '25' in line
    assert 'Domain Reviewer' in line


def test_a_template_the_service_could_not_read_says_nothing():
    """«we could not tell» is not «there is no gap», and it is also not a gap.

    Both halves are checked separately on purpose. A `readable: false` carrying
    `unmapped_count: None` is refused by the count check whether or not the
    readable flag is read at all, so it proves nothing about the flag; a
    `readable: false` carrying a number is the case that needs the flag, and it
    is the shape a partial or stale response takes.
    """
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
    """A line rendered from a key nothing attaches is the same defect one layer
    up, which this pipeline has now produced seven times."""
    from pathlib import Path

    import open_webui.tools.geotizer as adapter

    assert 'template_section_line(final)' in Path(adapter.__file__).read_text(
        encoding='utf-8'
    )
