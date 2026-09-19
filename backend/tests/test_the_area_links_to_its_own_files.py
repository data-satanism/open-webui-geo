"""The answer says where the area's files are, or why there are none.

The first seven-member area ended with «Скачать CPR-отчёт» and «Скачать
Excel-таблицу» over links that did not resolve. Two things were wrong and
only one of them was the link: the area had no id that survives a URL, and
the answer printed a name where a path belongs.

An answer that prints nothing at all is the same failure with the evidence
removed — a reader cannot tell «this area has no files» from «this answer
forgot to mention them» — so there is a line in every case.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.services.artifacts.geotizer.area_request import (  # noqa: E402
    ARTEFACT_PROXY_PREFIX,
    RESOLVED,
    area_artifact_lines,
    render_area_answer,
)
from open_webui.services.artifacts.geotizer.area_workflow import PERFORMED  # noqa: E402

AREA_ID = 'area_' + 'a' * 64


def _files(*names):
    return {
        name: {'download_path': f'/geotizer/files/{AREA_ID}/{name}', 'sha256': 'x'}
        for name in names
    }


def _artifacts(**overrides):
    record = {
        'written': True,
        'run_id': AREA_ID,
        'missing_inputs': [],
        'files': _files('state.json', 'run_log.json', 'summary.md', 'geotizer.xlsx'),
        'not_rendered': {'geotizer.docx': 'the CPR template is a card for one object'},
    }
    record.update(overrides)
    return record


def _answer(**overrides):
    result = {
        'area_id': 'area:Тенгкели-Березовская площадь',
        'counts': {'members': 7, 'filled': 7, 'failed': 0, 'not_attempted': 0},
        'members': [],
        'aggregation': {'state': PERFORMED},
        'summary_markdown': '# Свод',
        'artifacts': _artifacts(),
    }
    result.update(overrides)
    return {'status': RESOLVED, 'result': result}


def test_every_artefact_the_area_wrote_is_linked():
    lines = area_artifact_lines(_artifacts())
    text = '\n'.join(lines)

    for name in ('summary.md', 'geotizer.xlsx', 'state.json', 'run_log.json'):
        assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/{name}' in text, name


def test_the_link_carries_the_proxy_prefix_a_browser_can_reach():
    """`/geotizer/files/…` is the GIS service's own path and is not reachable
    from a browser session. `terminal._proxy_download_path` puts the same
    prefix on a member's link."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    assert '(/api/v1/geotizer/files/' in text
    assert '](/geotizer/files/' not in text


def test_a_path_the_service_did_not_build_is_not_linked():
    """Prefixing an arbitrary string produces a link that 404s while looking
    exactly like one that works, which is the defect being fixed."""
    record = _artifacts(
        files={
            'geotizer.xlsx': {'download_path': 'https://elsewhere.example/x.xlsx'},
            'summary.md': {'download_path': f'/geotizer/files/{AREA_ID}/summary.md'},
        }
    )

    text = '\n'.join(area_artifact_lines(record))

    assert 'elsewhere.example' not in text
    assert 'summary.md' in text


def test_a_fold_that_could_not_store_names_the_field_it_lacked():
    lines = area_artifact_lines(
        {'written': False, 'missing_inputs': ['project_id'], 'files': {}}
    )

    assert len(lines) == 1
    assert 'project_id' in lines[0]


def test_a_service_that_said_nothing_is_a_version_skew_and_says_so():
    """«This area has no files» and «this service is older than the feature»
    need different fixes, and reporting them alike sends whoever reads it to
    the wrong one."""
    lines = area_artifact_lines(None)

    assert len(lines) == 1
    assert 'GIS-сервиса' in lines[0]


def test_what_the_area_does_not_have_is_said_rather_than_absent():
    """A reader who knows the member card has a DOCX will look for the
    area's."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    assert 'geotizer.docx' in text
    assert 'not_rendered' in text


def test_written_with_no_usable_path_is_not_silence():
    """The one case that would otherwise print a heading and no links."""
    lines = area_artifact_lines(
        _artifacts(files={'geotizer.xlsx': {'download_path': ''}})
    )

    assert len(lines) == 1
    assert 'ни одного пригодного пути' in lines[0]


def test_the_answer_a_reader_sees_carries_the_links():
    """Assembled and rendered, not assembled and dropped: a note that reaches
    no reader is the silence it exists to break, and this module has paid for
    that once already with the concurrency note."""
    markdown = render_area_answer(_answer())

    assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/geotizer.xlsx' in markdown
    assert '# Свод' in markdown


def test_an_area_that_did_not_fold_offers_no_downloads():
    """An area with no roll-up has no area artefacts, and offering a download
    for one would be the dead link this whole file is about."""
    markdown = render_area_answer(
        _answer(
            aggregation={
                'state': 'not_performed',
                'reason': 'nothing_filled',
                'members_total': 7,
            }
        )
    )

    assert '/geotizer/files/' not in markdown
    assert 'Свод не построен' in markdown


def test_the_name_is_printed_and_the_digest_is_linked():
    """The split `object_display_name` already makes one level up: what a
    person reads and what a path carries are different values."""
    markdown = render_area_answer(_answer())

    assert 'Тенгкели-Березовская площадь' in markdown
    assert AREA_ID in markdown
