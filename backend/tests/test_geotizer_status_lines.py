"""Tests for the GeoTeaser status lines a user reads during a run, asserted as
whole strings in both languages and both verbosities."""

from __future__ import annotations

import asyncio
import json

import pytest

from open_webui.services.artifacts.geotizer.terminal import (
    StatusSettings,
    _filled_cells,
    carry_forward_mode_line,
)
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

BATCHES = (
    ('GIS-DC', 'gis'),
    ('KB-LIC-LEGAL', 'kb'),
    ('KB-GEO', 'kb'),
    ('KB-STUDY', 'kb'),
    ('KB-RESOURCE-TECH', 'kb'),
    ('KB-GRR-FACTORS', 'kb'),
    ('WEB-VERIFY', 'web'),
    ('ASSEMBLE', 'skilled'),
)


def _batch(index: int) -> dict:
    batch_id, producer = BATCHES[index]
    return {
        'batch_id': batch_id,
        'producer': producer,
        'policy_version': 'geotizer_assignments.v2',
        'template_version': 'geotizer_object.v1',
        'fields': [{'field_key': f'{batch_id}.f1', 'row_id': index + 1}],
        'evidence_routes': [],
    }


def _envelope(batch: dict) -> str:
    return json.dumps(
        {
            'batch_id': batch['batch_id'],
            'producer': batch['producer'],
            'policy_version': batch['policy_version'],
            'template_version': batch['template_version'],
            'source_inventory': [
                {'source_id': 's1', 'source_type': 'gis', 'title': 'linked project'}
            ],
            'patches': [
                {
                    'field_key': field['field_key'],
                    'value': 'value',
                    'status': 'filled',
                    'source_refs': ['s1'],
                    'source_locator': {'layer': 'licence'},
                }
                for field in batch['fields']
            ],
        }
    )


def _run(*, status=None, batches_total=8, blocked=False, object_name='Верхне-Колпинская площадь', licence_id=None) -> list[str]:
    """Drive a whole eight-batch run and return the status lines in order;
    `batches_total=None` omits that field from every summary."""
    progress = iter(range(1, len(BATCHES) + 1))
    lines: list[str] = []

    def _summary(index: int) -> dict:
        summary = {
            'workflow_status': 'collecting',
            'run_id': 'run-status',
            'object_name': 'Верхне-Колпинская площадь',
            'datacube': {},
            'gis_project': {
                'status': 'resolved',
                'project_id': 'Верхне_Колпинская_площадь',
                'object_name': 'Верхне-Колпинская площадь',
            },
            'next_batch': _batch(index) if index < len(BATCHES) else None,
        }
        if batches_total is not None:
            summary['batches_total'] = batches_total
        return summary

    async def gis_call(payload):
        if payload['action'] == 'start':
            return _summary(0)
        if payload['action'] == 'submit_batch':
            return _summary(next(progress))
        return {
            'workflow_status': 'finalized',
            'run_id': 'run-status',
            'audit': {
                'summary': {'failed': 1 if blocked else 0, 'warnings': 0},
                'gates': {
                    'publication': 'blocked' if blocked else 'allowed',
                    'draft_xlsx_rendering': 'allowed',
                },
            },
            'xlsx': {'download_path': '/geotizer/files/run-status/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        if task.task_id == 'GIS-OBJECT-PROFILE':
            return json.dumps({'profile_status': 'unavailable'})
        return _envelope(_batch([name for name, _ in BATCHES].index(task.task_id)))

    async def emitter(event):
        lines.append(event['data']['description'])

    final = asyncio.run(
        run_geotizer_workflow(
            object_name=object_name,
            licence_id=licence_id,
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
            event_emitter=emitter,
            status=status,
        )
    )
    assert final['workflow_status'] == 'finalized'
    return lines


def test_a_russian_run_reads_as_one_voice_from_first_line_to_last():
    """A default run's status lines are all Russian and arrive in the expected
    order."""
    assert _run() == [
        'Геотизер: запуск run-status — Верхне-Колпинская площадь',
        'Геотизер: уточняю параметры объекта для поиска',
        'Геотизер: пакет 1 из 8',
        'Геотизер: пакет 2 из 8',
        'Геотизер: пакет 3 из 8',
        'Геотизер: пакет 4 из 8',
        'Геотизер: пакет 5 из 8',
        'Геотизер: пакет 6 из 8',
        'Геотизер: пакет 7 из 8',
        'Геотизер: пакет 8 из 8',
        'Геотизер: финальная проверка и формирование файлов',
        'Геотизер: файл XLSX готов',
    ]


def test_the_first_line_is_the_run_id_a_timed_out_caller_needs():
    """The first status line names the run id and the object."""
    first = _run()[0]

    assert first == 'Геотизер: запуск run-status — Верхне-Колпинская площадь'


def test_the_run_line_comes_before_any_work_is_done():
    """The run line precedes every batch line."""
    lines = _run()

    assert lines.index('Геотизер: запуск run-status — Верхне-Колпинская площадь') == 0
    assert all('пакет' not in line for line in lines[:1])


def test_the_english_half_states_the_same_facts_in_the_same_order():
    """An `en` run states the same lines in English, in the same order."""
    assert _run(status=StatusSettings(language='en')) == [
        'GeoTeaser: run run-status started — Верхне-Колпинская площадь',
        'GeoTeaser: profiling the object for the knowledge search',
        'GeoTeaser: batch 1 of 8',
        'GeoTeaser: batch 2 of 8',
        'GeoTeaser: batch 3 of 8',
        'GeoTeaser: batch 4 of 8',
        'GeoTeaser: batch 5 of 8',
        'GeoTeaser: batch 6 of 8',
        'GeoTeaser: batch 7 of 8',
        'GeoTeaser: batch 8 of 8',
        'GeoTeaser: final audit and file rendering',
        'GeoTeaser: the XLSX file is ready',
    ]


def test_the_blocked_ending_is_translated_too():
    """The blocked-publication final line is emitted in both languages."""
    assert _run(blocked=True)[-1] == 'Геотизер: черновик XLSX готов; публикация заблокирована'
    assert (
        _run(status=StatusSettings(language='en'), blocked=True)[-1]
        == 'GeoTeaser: XLSX draft is ready; publication is blocked'
    )


def test_technical_appends_the_two_diagnostics_and_user_shows_neither():
    """`technical` verbosity appends the batch id and producer to each batch
    line after an em dash."""
    technical = _run(status=StatusSettings(verbosity='technical'))

    assert technical[2] == 'Геотизер: пакет 1 из 8 — GIS-DC (gis)'
    assert technical[8] == 'Геотизер: пакет 7 из 8 — WEB-VERIFY (web)'
    assert technical[9] == 'Геотизер: пакет 8 из 8 — ASSEMBLE (skilled)'
    assert ' — ' in technical[2]


def test_technical_in_english_uses_the_same_separator_and_the_same_pair():
    technical = _run(status=StatusSettings(language='en', verbosity='technical'))

    assert technical[2] == 'GeoTeaser: batch 1 of 8 — GIS-DC (gis)'
    assert technical[9] == 'GeoTeaser: batch 8 of 8 — ASSEMBLE (skilled)'


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_user_verbosity_leaks_no_batch_id_and_no_producer(language):
    """At `user` verbosity no line names a batch id or a producer, in either
    language."""
    lines = _run(status=StatusSettings(language=language))

    for batch_id, producer in BATCHES:
        for line in lines:
            assert batch_id not in line, line
            assert f'({producer})' not in line, line


def test_a_service_too_old_to_send_the_total_drops_the_denominator():
    """Without `batches_total` the batch line drops the denominator."""
    lines = _run(batches_total=None)

    assert lines[2] == 'Геотизер: пакет 1'
    assert lines[9] == 'Геотизер: пакет 8'
    assert not any('None' in line for line in lines)


def test_the_fallback_keeps_both_valves_and_both_languages():
    assert _run(batches_total=None, status=StatusSettings(language='en'))[2] == 'GeoTeaser: batch 1'
    assert (
        _run(batches_total=None, status=StatusSettings(verbosity='technical'))[2]
        == 'Геотизер: пакет 1 — GIS-DC (gis)'
    )
    assert (
        _run(
            batches_total=None,
            status=StatusSettings(language='en', verbosity='technical'),
        )[2]
        == 'GeoTeaser: batch 1 — GIS-DC (gis)'
    )


@pytest.mark.parametrize('total', [0, -1, '', 'eight', None, {}])
def test_an_unusable_total_is_treated_as_no_total_rather_than_printed(total):
    """A non-positive or non-numeric total renders the batch line without a
    denominator."""
    line = StatusSettings().batch_line(n=3, total=total, batch_id='KB-GEO', producer='kb')

    assert line == 'Геотизер: пакет 3'


def test_an_unknown_language_falls_back_to_russian_rather_than_raising():
    """An unknown `STATUS_LANGUAGE` falls back to Russian, and the language is
    matched case-insensitively."""
    assert StatusSettings(language='ру').say('ready') == 'Геотизер: файл XLSX готов'
    assert StatusSettings(language='').say('ready') == 'Геотизер: файл XLSX готов'
    assert StatusSettings(language='EN').say('ready') == 'GeoTeaser: the XLSX file is ready'


def test_verbosity_is_read_the_way_the_orchestration_tool_reads_it():
    """`STATUS_VERBOSITY` is stripped and matched case-insensitively."""
    assert StatusSettings(verbosity=' TECHNICAL ').technical is True
    assert StatusSettings(verbosity='user').technical is False
    assert StatusSettings(verbosity='').technical is False


def test_the_parallel_key_line_comes_out_of_the_table_like_the_rest():
    """The parallel-key line comes from the phrase table in both languages."""
    fields = {'run_id': 'run-new', 'abandoned_run_id': 'run-orphan'}

    assert StatusSettings().say('parallel_key', **fields) == (
        'Геотизер: этот ключ уже занят параллельным запуском; '
        'продолжаю в запуске run-new, запуск run-orphan оставлен незавершённым'
    )
    assert StatusSettings(language='en').say('parallel_key', **fields) == (
        'GeoTeaser: this key is already held by a parallel run; '
        'continuing in run run-new, run run-orphan left unfinished'
    )


def test_both_languages_define_the_same_keys():
    """`PHRASE` defines the same keys for `ru` and `en`."""
    from open_webui.services.artifacts.geotizer.terminal import PHRASE

    assert set(PHRASE['ru']) == set(PHRASE['en'])
    assert set(PHRASE) == {'ru', 'en'}


@pytest.mark.parametrize(
    ('count', 'expected'),
    [
        (1, 'заполненной ячейки'),
        (2, 'заполненных ячейки'),
        (4, 'заполненных ячейки'),
        (5, 'заполненных ячеек'),
        (11, 'заполненных ячеек'),
        (12, 'заполненных ячеек'),
        (14, 'заполненных ячеек'),
        (21, 'заполненной ячейки'),
        (22, 'заполненных ячейки'),
        (25, 'заполненных ячеек'),
        (101, 'заполненной ячейки'),
        (111, 'заполненных ячеек'),
        (351, 'заполненной ячейки'),
    ],
)
def test_the_cell_count_agrees_with_its_numeral(count, expected):
    """`_filled_cells` uses the Russian numeral form that agrees with the
    count, including 11-14."""
    assert _filled_cells(count) == expected


def test_the_mode_line_uses_the_agreeing_form():
    """`carry_forward_mode_line` uses the agreeing numeral form."""
    carried = {
        'carried_field_count': 1,
        'run_mode': 'carry_forward',
        'parent_run_ids': ['run-0'],
        'derived_from': '',
    }

    line = carry_forward_mode_line(carried, filled=1)

    assert 'из 1 заполненной ячейки' in line
    assert 'заполненных ячеек' not in line


def test_a_run_with_no_object_name_says_so_rather_than_trailing_a_dash():
    """A run with no name and no licence prints `—` as the object in the run
    line."""
    lines = _run(object_name='')

    started = [line for line in lines if line.startswith('Геотизер: запуск')]
    assert started, lines
    assert started[0] == 'Геотизер: запуск run-status — —'
    assert not started[0].rstrip().endswith('—  ')


def test_a_licence_first_run_is_named_by_its_licence_and_not_by_a_dash():
    """A run with no name is named by its licence in the run line."""
    lines = _run(object_name='', licence_id='МАГ04805БЭ')

    started = [line for line in lines if line.startswith('Геотизер: запуск')]
    assert started[0] == 'Геотизер: запуск run-status — МАГ04805БЭ'


def test_a_run_with_neither_a_name_nor_a_licence_still_falls_back_to_a_dash():
    """A run with neither a name nor a licence prints `—` in the run line."""
    lines = _run(object_name='')

    started = [line for line in lines if line.startswith('Геотизер: запуск')]
    assert started[0] == 'Геотизер: запуск run-status — —'
