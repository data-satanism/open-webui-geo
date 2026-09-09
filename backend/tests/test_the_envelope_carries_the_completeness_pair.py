"""§3. Does the terminal envelope carry the pair, or is it lost on the way?

`test_both_completeness_figures_reach_the_envelope` claimed to answer this and
did not. It handed `completeness_lines` a dict spelled by hand and checked what
came back -- a test of the writer, wearing the envelope's name. A writer test
cannot tell you the envelope carries anything; it tells you what the writer
does with what you gave it.

So this drives the real `run_geotizer_workflow` with a GIS stub whose
`finalize` returns the audit block runs `0b5ae763` and `bc4af304` actually
returned, and asserts on the mapping the workflow hands back.

The answer, for the record: the envelope carries the pair. Both runs' saved
states hold `audit.completeness.strict = 98/202` and `.basic = 124/258`, the
fork's `final` is the finalize response widened only by `{**final, ...}`
spreads that add keys, and the assertions below hold. Nothing was lost in
transport. The card printed the pair AND a strict-only line above it, and
whatever read the card met the strict-only one first.
"""

from __future__ import annotations

import asyncio
import json

from open_webui.services.artifacts.geotizer.terminal import completeness_lines
from open_webui.services.artifacts.geotizer.workflow import run_geotizer_workflow

#: `audit.completeness` exactly as run `bc4af304` recorded it, trimmed to the
#: keys this file reads. `strict`/`basic` sit here and nowhere else: they are
#: NOT in `counts`, which is the flat status dict, and a fixture that puts
#: them there tests a shape the service does not emit.
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
    """The §3 question, asked of the envelope."""
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    assert final['workflow_status'] == 'finalized'
    completeness = final['audit']['completeness']
    assert completeness['strict'] == {'filled': 202, 'of': 351}
    assert completeness['basic'] == {'filled': 258, 'of': 351}


def test_the_pair_is_not_in_the_status_counts():
    """Where it is NOT. `counts` is `_summary`'s flat status dict and is always
    non-empty, so a reader falling back through it never reaches the pair --
    which is how the fork came to build its «Заполнено» line from a number that
    could only ever be the strict one."""
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    assert 'strict' not in final['counts']
    assert 'basic' not in final['counts']


def test_the_card_built_from_that_envelope_has_one_zapolneno():
    """Both halves in one place: the envelope carries the pair, and the
    markdown built from it says so once.

    Runs `0b5ae763` and `bc4af304` failed here, not upstream. The envelope was
    right; the markdown carried «- Заполнено: 202» and, two lines down,
    «- Заполнено: 202 из 351 (строго) · 258 из 351 (с учётом расхождений)».
    """
    final = _envelope_from_a_finalize_that_carries(BC4AF304_COMPLETENESS)

    text = completeness_lines(final)

    headlines = [
        line for line in text.splitlines() if line.startswith('- Заполнено')
    ]
    assert len(headlines) == 1, headlines
    assert '202 из 351 (строго)' in headlines[0]
    assert '258 из 351 (с учётом расхождений)' in headlines[0]


def test_a_deployment_that_sends_no_pair_still_reports_its_one_figure():
    """Version skew degrades to the previous card, not to a wrong one."""
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
