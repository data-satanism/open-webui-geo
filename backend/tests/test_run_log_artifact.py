"""`run_log.json` was written by one service, served by neither, linked by none.

Four load-bearing records live in that file and nowhere else: the GIS execution
trace every Stage 3-8 acceptance criterion reads, the layer manifest Stage 3's
scope was derived from, the run notes behind «Ограничения этого запуска», and
the retrieval queries the variance question turns on. They were moved to that
carrier deliberately -- what describes a cell arrives on a patch, what
describes a run does not -- and the carrier was then given no way out.

The sixth instance of the family, after `divergent_claim_keys` with no caller,
the run notes going to a local list, `layer_not_found` as unread prose,
`retrieval_queries`, and `gis_execution_trace`.
"""

from __future__ import annotations

import pytest

from open_webui.services.geotizer.errors import GeotizerOrchestrationError
from open_webui.services.artifacts.geotizer.terminal import (
    _proxy_source_report_paths,
    attachment_files,
    run_log_link,
)

BASE = '/geotizer/files/run-1'


def final(*, with_run_log=True, run_log_path=f'{BASE}/run_log.json'):
    payload = {
        'source_report': {
            'markdown': {'download_path': f'{BASE}/source_report.md'},
            'pdf': {'download_path': f'{BASE}/source_report.pdf'},
            'state': {'download_path': f'{BASE}/state.json'},
            'docx': {'download_path': f'{BASE}/geotizer.docx'},
        }
    }
    if with_run_log:
        payload['run_log'] = {'download_path': run_log_path, 'sha256': 'a' * 64}
    return payload


def test_the_run_log_path_is_proxied_like_every_other_artefact():
    paths = _proxy_source_report_paths(final())

    assert paths['run_log'] == '/api/v1/geotizer/files/run-1/run_log.json'


def test_it_is_read_from_the_run_and_not_from_the_source_report():
    """The placement is correct rather than an inconsistency to tidy. The run
    log describes the *run*; the source report describes the evidence behind
    the cells. Moving the entry inside `source_report` so one loop could reach
    it would be the category error the carrier principle exists to name."""
    payload = final()
    assert 'run_log' not in payload['source_report']

    assert 'run_log' in _proxy_source_report_paths(payload)


def test_a_service_that_emits_no_run_log_loses_one_link_and_not_the_set():
    """Optional, for the reason the docx is: a key missing from the required
    loop abandons the whole set and returns `{}`, so a WebUI deployed ahead of
    its GIS service would lose every report link rather than one."""
    paths = _proxy_source_report_paths(final(with_run_log=False))

    assert 'run_log' not in paths
    assert set(paths) == {'markdown', 'pdf', 'state', 'docx'}


def test_a_malformed_run_log_path_is_refused_rather_than_proxied():
    """Absent is a version skew; malformed is a defect, and the two must not
    produce the same silence."""
    with pytest.raises(GeotizerOrchestrationError):
        _proxy_source_report_paths(final(run_log_path='/somewhere/else.json'))


def test_the_link_says_journal_rather_than_report():
    """A reader who opens something called a report expecting prose finds an
    execution trace, a layer manifest, a note list and a query log."""
    link = run_log_link({'run_log': '/api/v1/geotizer/files/run-1/run_log.json'})

    assert 'журнал запуска' in link.lower()
    assert 'отчёт' not in link.lower()
    assert '/api/v1/geotizer/files/run-1/run_log.json' in link


def test_the_link_has_no_parentheses_in_its_label():
    """`[… (X)](path)` is legal Markdown and a naive `split('(')` returns the
    label tail instead of the URL -- which one of this tree's own tests did."""
    link = run_log_link({'run_log': '/api/v1/x/run_log.json'})

    assert link.count('(') == 1


def test_no_link_when_the_run_log_is_absent():
    assert run_log_link({}) == ''
    assert run_log_link(None) == ''


def test_it_is_attached_last_after_the_evidence():
    """Diagnostic output, not a deliverable: the card first in both formats,
    then the sources behind it, then the state, then this."""
    files = attachment_files(
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        {
            key: f'/api/v1/geotizer/files/run-1/{name}'
            for key, name in (
                ('docx', 'geotizer.docx'),
                ('pdf', 'source_report.pdf'),
                ('markdown', 'source_report.md'),
                ('state', 'state.json'),
                ('run_log', 'run_log.json'),
            )
        },
        object_name='Лекын',
    )

    assert [item['url'].rsplit('/', 1)[-1] for item in files] == [
        'geotizer.xlsx',
        'geotizer.docx',
        'source_report.pdf',
        'source_report.md',
        'state.json',
        'run_log.json',
    ]


def test_the_attachment_carries_the_json_content_type():
    files = attachment_files(
        '/api/v1/geotizer/files/run-1/geotizer.xlsx',
        {'run_log': '/api/v1/geotizer/files/run-1/run_log.json'},
        object_name='',
    )

    run_log = [item for item in files if item['url'].endswith('run_log.json')]
    assert len(run_log) == 1
