"""The terminal envelope from `run_geotizer_workflow` carries the strict and basic completeness pair to the card."""

from __future__ import annotations

import asyncio
import json

from open_webui.services.artifacts.geotizer.terminal import completeness_lines
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

BC4AF304_COMPLETENESS = {
    'required': 351,
    'filled': 202,
    'not_found': 71,
    'not_applicable': 18,
    'conflicted': 31,
    'requires_expert_review': 29,
    'agent_contract_failed': 0,
    'strict': {'filled': 202, 'of': 351},
    'basic': {'filled': 258, 'of': 351},
}


def _envelope_from_a_finalize_that_carries(completeness):
    """Run the workflow for real, with the GIS server stubbed at the wire."""

    async def gis_call(payload):
        if payload['action'] == 'start':
            return {
                'workflow_status': 'collecting',
                'run_id': 'pair-e2e',
                'object_name': 'Лекын-Тальбейская площадь',
                'datacube': {},
                'next_batch': None,
            }
        if payload['action'] == 'submit_batch':
            return {
                'workflow_status': 'collecting',
                'run_id': 'pair-e2e',
                'next_batch': None,
            }
        return {
            'workflow_status': 'finalized',
            'run_id': 'pair-e2e',
            'object_name': 'Лекын-Тальбейская площадь',
            'counts': {
                key: value
                for key, value in completeness.items()
                if isinstance(value, int)
            },
            'audit': {
                'completeness': completeness,
                'summary': {'failed': 0, 'warnings': 0},
                'gates': {'publication': 'blocked'},
            },
            'xlsx': {'download_path': '/geotizer/files/pair-e2e/geotizer.xlsx'},
        }

    async def agent_call(task, prompt, object_name, datacube):
        return json.dumps({'patches': []}, ensure_ascii=False)

    return asyncio.run(
        run_geotizer_workflow(
            object_name='Лекын-Тальбейская площадь',
            project_id=None,
            model_run_id=None,
            run_id=None,
            allow_draft=True,
            gis_call=gis_call,
            agent_call=agent_call,
        )
    )


def test_the_envelope_carries_both_figures():
    """The finalized envelope carries both the strict and the basic completeness figures."""
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    assert final['workflow_status'] == 'finalized'
    completeness = final['audit']['completeness']
    assert completeness['strict'] == {'filled': 202, 'of': 351}
    assert completeness['basic'] == {'filled': 258, 'of': 351}


def test_the_pair_is_not_in_the_status_counts():
    """Neither `strict` nor `basic` appears in the envelope's `counts`."""
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    assert 'strict' not in final['counts']
    assert 'basic' not in final['counts']


def test_the_card_built_from_that_envelope_has_one_zapolneno():
    """The markdown built from the envelope has one «Заполнено» line stating both counts with their rates."""
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    text = completeness_lines(final)

    headlines = [
        line for line in text.splitlines() if line.startswith('- Заполнено')
    ]
    assert len(headlines) == 1, headlines
    assert '202 из 351 (57.5%, строго)' in headlines[0]
    assert '258 из 351 (73.5%, с учётом расхождений)' in headlines[0]


def test_a_deployment_that_sends_no_pair_still_reports_its_one_figure():
    """An envelope with no completeness pair prints the single filled count."""
    without = {
        key: value
        for key, value in BC4AF304_COMPLETENESS.items()
        if key not in ('strict', 'basic')
    }
    final = _envelope_from_a_finalize_that_carries(without)

    text = completeness_lines(final)

    headlines = [
        line for line in text.splitlines() if line.startswith('- Заполнено')
    ]
    assert len(headlines) == 1, headlines
    assert headlines[0].startswith('- Заполнено: 202')
    assert 'строго' not in headlines[0]


def test_a_card_with_no_cells_is_not_reported_as_an_older_deployment():
    """A pair with `of: 0` prints an undetermined-completeness line, not the no-pair line."""
    zero = {
        'required': 0,
        'strict': {'filled': 0, 'of': 0},
        'basic': {'filled': 0, 'of': 0},
    }
    final = _envelope_from_a_finalize_that_carries(zero)

    text = completeness_lines(final)

    headline = next(
        line for line in text.splitlines() if line.startswith('- Заполнено')
    )
    assert 'не определено' in headline
    assert 'не содержит ни одной ячейки' in headline
    assert headline != '- Заполнено: 0'
