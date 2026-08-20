"""What a user actually reads while a run is going, asserted verbatim.

GeoTeaser emitted five status lines. Four were English -- «GeoTeaser: batch 3
GIS-DC (gis)» -- while the orchestration tool narrated the specialist half of
the same message in Russian, and the batch line spent its width on two strings
nobody outside this repository can read: a batch id from a hash-pinned policy
asset and a producer whose meaning left with the mapping layer deleted in
422ff06. A count is what a reader can act on; the other two are what an
operator needs when a batch stalls, which is what `STATUS_VERBOSITY` is for.

Every assertion here is on the whole string, never on a substring. Russian
inflects and a wrong case ending is a real defect that `'пакет' in line` cannot
see, so the tests are written so that they fail on one letter.
"""

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

# The eight owner batches `assignment_policy.json` plans, in the order
# `gis_service` hands them out. Named here rather than generated, so the batch
# ids the technical line is asserted against are the real ones.
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


def _run(*, status=None, batches_total=8, blocked=False) -> list[str]:
    """Drive a whole eight-batch run and return the lines, in order.

    `batches_total=None` is the version skew this has to survive: a GIS service
    older than the field sends a summary without one, and `.get` returns `None`.
    """
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
            object_name='Верхне-Колпинская площадь',
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


# -- the transcript, whole and in order --------------------------------------


def test_a_russian_run_reads_as_one_voice_from_first_line_to_last():
    """The default, and the whole deliverable: eleven lines, no English left.

    Compared as a list so that an inserted, dropped or reordered line fails
    here rather than being absorbed by a per-line check.
    """
    assert _run() == [
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


def test_the_english_half_states_the_same_facts_in_the_same_order():
    """A deployment switched to `en` is the same run reported to a different
    reader. The two tables saying different things is how a bilingual contour
    ends up with two accounts of one run."""
    assert _run(status=StatusSettings(language='en')) == [
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
    """The line that only a failing audit produces. It was English, it is not
    in the briefing's table, and leaving it is the half-translated state the
    whole change exists to remove -- so it is asserted, not assumed."""
    assert _run(blocked=True)[-1] == 'Геотизер: черновик XLSX готов; публикация заблокирована'
    assert (
        _run(status=StatusSettings(language='en'), blocked=True)[-1]
        == 'GeoTeaser: XLSX draft is ready; publication is blocked'
    )


# -- the two valves ----------------------------------------------------------


def test_technical_appends_the_two_diagnostics_and_user_shows_neither():
    """The batch id and the producer are what names a batch that stalled, and
    nothing a reader can act on. `technical` keeps them for the same reason the
    orchestration tool keeps its per-round tool names behind the same valve."""
    technical = _run(status=StatusSettings(verbosity='technical'))

    assert technical[1] == 'Геотизер: пакет 1 из 8 — GIS-DC (gis)'
    assert technical[7] == 'Геотизер: пакет 7 из 8 — WEB-VERIFY (web)'
    assert technical[8] == 'Геотизер: пакет 8 из 8 — ASSEMBLE (skilled)'
    # The em dash is the orchestration tool's separator for exactly this tail;
    # a hyphen here would be a second scheme.
    assert ' — ' in technical[1]


def test_technical_in_english_uses_the_same_separator_and_the_same_pair():
    technical = _run(status=StatusSettings(language='en', verbosity='technical'))

    assert technical[1] == 'GeoTeaser: batch 1 of 8 — GIS-DC (gis)'
    assert technical[8] == 'GeoTeaser: batch 8 of 8 — ASSEMBLE (skilled)'


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_user_verbosity_leaks_no_batch_id_and_no_producer(language):
    """Asserted as absence over the whole run, not just on one line. Every
    batch id and every producer name, in either language: the point of the
    valve is that `user` never sees them."""
    lines = _run(status=StatusSettings(language=language))

    for batch_id, producer in BATCHES:
        for line in lines:
            assert batch_id not in line, line
            assert f'({producer})' not in line, line


# -- the version skew --------------------------------------------------------


def test_a_service_too_old_to_send_the_total_drops_the_denominator():
    """`batches_total` is a response field, so a GIS service built before it
    sends none. «из None» is the skew reaching the user; the number simply
    going away keeps the line true, and is what a newer WebUI against an older
    service shows."""
    lines = _run(batches_total=None)

    assert lines[1] == 'Геотизер: пакет 1'
    assert lines[8] == 'Геотизер: пакет 8'
    assert not any('None' in line for line in lines)


def test_the_fallback_keeps_both_valves_and_both_languages():
    assert _run(batches_total=None, status=StatusSettings(language='en'))[1] == 'GeoTeaser: batch 1'
    assert (
        _run(batches_total=None, status=StatusSettings(verbosity='technical'))[1]
        == 'Геотизер: пакет 1 — GIS-DC (gis)'
    )
    assert (
        _run(
            batches_total=None,
            status=StatusSettings(language='en', verbosity='technical'),
        )[1]
        == 'GeoTeaser: batch 1 — GIS-DC (gis)'
    )


@pytest.mark.parametrize('total', [0, -1, '', 'eight', None, {}])
def test_an_unusable_total_is_treated_as_no_total_rather_than_printed(total):
    """«пакет 3 из 0» is not a fact about anything, and neither is «из eight».
    The only honest renderings are the real count and no count."""
    line = StatusSettings().batch_line(n=3, total=total, batch_id='KB-GEO', producer='kb')

    assert line == 'Геотизер: пакет 3'


# -- the phrase table itself -------------------------------------------------


def test_an_unknown_language_falls_back_to_russian_rather_than_raising():
    """`STATUS_LANGUAGE` is a free-text valve an operator types into. A typo
    must cost the language, not the run -- the same fallback the orchestration
    tool's `_lang` makes."""
    assert StatusSettings(language='ру').say('ready') == 'Геотизер: файл XLSX готов'
    assert StatusSettings(language='').say('ready') == 'Геотизер: файл XLSX готов'
    assert StatusSettings(language='EN').say('ready') == 'GeoTeaser: the XLSX file is ready'


def test_verbosity_is_read_the_way_the_orchestration_tool_reads_it():
    """Same normalisation, so one stored value cannot mean `technical` to one
    half of the run and `user` to the other."""
    assert StatusSettings(verbosity=' TECHNICAL ').technical is True
    assert StatusSettings(verbosity='user').technical is False
    assert StatusSettings(verbosity='').technical is False


def test_the_parallel_key_line_comes_out_of_the_table_like_the_rest():
    """It was the one Russian line, built by hand at the call site. Left there
    it would have been the only line an `en` deployment could not switch."""
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
    """A key present in one table and missing from the other is a `KeyError`
    raised mid-run, on the deployment that switched language and nowhere else.
    """
    from open_webui.services.artifacts.geotizer.terminal import PHRASE

    assert set(PHRASE['ru']) == set(PHRASE['en'])
    assert set(PHRASE) == {'ru', 'en'}


# -- numerals ---------------------------------------------------------------


@pytest.mark.parametrize(
    ('count', 'expected'),
    [
        (1, 'заполненной ячейки'),
        (2, 'заполненных ячейки'),
        (4, 'заполненных ячейки'),
        (5, 'заполненных ячеек'),
        # 11-14 take the 5+ form whatever their last digit says, which is the
        # rule a naive `count == 1` check gets wrong first.
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
    """Russian numerals govern three different forms, and the card had one.

    «из 1 заполненных ячеек» is wrong in the case a reader is most likely to
    look at closely -- a card carrying a single carried field. 11-14 is the
    other trap: they take the 5+ form despite ending in 1-4.
    """
    assert _filled_cells(count) == expected


def test_the_mode_line_uses_the_agreeing_form():
    """The helper is only worth having if the sentence actually calls it."""
    carried = {
        'carried_field_count': 1,
        'run_mode': 'carry_forward',
        'parent_run_ids': ['run-0'],
        'derived_from': '',
    }

    line = carry_forward_mode_line(carried, filled=1)

    assert 'из 1 заполненной ячейки' in line
    assert 'заполненных ячеек' not in line
