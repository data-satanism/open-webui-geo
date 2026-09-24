"""Tests that `run_log.json` is proxied, linked and attached like the other
artefacts, and read from the run rather than from the source report."""

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
    """The run log path is read from the run's `run_log`, not from
    `source_report`."""
    payload = final()
    assert 'run_log' not in payload['source_report']

    assert 'run_log' in _proxy_source_report_paths(payload)


def test_a_service_that_emits_no_run_log_loses_one_link_and_not_the_set():
    """A missing run log drops only its own path."""
    paths = _proxy_source_report_paths(final(with_run_log=False))

    assert 'run_log' not in paths
    assert set(paths) == {'markdown', 'pdf', 'state', 'docx'}


def test_a_malformed_run_log_path_is_refused_rather_than_proxied():
    """A malformed run log path raises `GeotizerOrchestrationError`."""
    with pytest.raises(GeotizerOrchestrationError):
        _proxy_source_report_paths(final(run_log_path='/somewhere/else.json'))


def test_the_link_says_journal_rather_than_report():
    """The run log link is labelled a run journal, not a report."""
    link = run_log_link({'run_log': '/api/v1/geotizer/files/run-1/run_log.json'})

    assert 'журнал запуска' in link.lower()
    assert 'отчёт' not in link.lower()
    assert '/api/v1/geotizer/files/run-1/run_log.json' in link


def test_the_link_has_no_parentheses_in_its_label():
    """The run log link label holds no parentheses."""
    link = run_log_link({'run_log': '/api/v1/x/run_log.json'})

    assert link.count('(') == 1


def test_no_link_when_the_run_log_is_absent():
    assert run_log_link({}) == ''
    assert run_log_link(None) == ''


def test_it_is_attached_last_after_the_evidence():
    """The run log is attached last, after the card and the evidence."""
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
