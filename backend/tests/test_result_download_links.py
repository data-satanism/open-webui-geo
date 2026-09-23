"""Tests for the download-link block of the result Markdown: every served
artefact, the Word card included, is linked through the proxy in card-then-
evidence order."""

from __future__ import annotations

import re

import pytest
from open_webui.services.artifacts.geotizer.terminal import (
    _proxy_source_report_paths,
    attachment_files,
    card_docx_link,
)

BASE = '/geotizer/files/run-1'
PROXY = f'/api/v1{BASE}'


def _final(*, docx=True):
    report = {
        'markdown': {'download_path': f'{BASE}/source_report.md'},
        'pdf': {'download_path': f'{BASE}/source_report.pdf'},
        'state': {'download_path': f'{BASE}/state.json'},
    }
    if docx:
        report['docx'] = {'download_path': f'{BASE}/geotizer.docx'}
    return {'source_report': report}


def _paths(*, docx=True):
    return _proxy_source_report_paths(_final(docx=docx))


def test_the_card_is_linked_in_word_when_the_service_renders_one():
    link = card_docx_link(_paths())

    assert f'({PROXY}/geotizer.docx)' in link
    assert link.startswith('\n\n[')


def test_a_service_that_renders_no_card_loses_one_link_and_not_the_block():
    """Without a DOCX the card link is empty and the other three report paths
    remain."""
    assert card_docx_link(_paths(docx=False)) == ''
    assert card_docx_link({}) == ''
    assert card_docx_link(None) == ''
    assert set(_paths(docx=False)) == {'markdown', 'pdf', 'state'}


def test_the_label_says_draft_and_not_only_report():
    """The DOCX link label says CPR and draft, and holds no brackets."""
    link = card_docx_link(_paths())

    assert 'CPR' in link
    assert 'черновик' in link.casefold()
    assert '(' not in link[: link.index('](')]


def test_the_label_does_not_claim_the_readiness_document_s_name():
    """The DOCX link label does not name the readiness document."""
    assert 'готовност' not in card_docx_link(_paths()).casefold()


def test_the_link_the_title_and_the_filename_still_agree():
    """The DOCX link names a draft CPR report in DOCX and not a GeoTeaser card."""
    link = card_docx_link(_paths()).casefold()

    assert 'cpr' in link
    assert 'черновик' in link
    assert 'DOCX' in card_docx_link(_paths())
    assert 'карту geoteaser' not in link


async def _render_result(monkeypatch, *, docx=True):
    """Run `fill_geotizer` with everything outside the result assembly stubbed,
    and return the Markdown a reader sees."""
    import open_webui.tools.geotizer as adapter

    final = {
        'run_id': 'run-1',
        'object_name': 'Лекын',
        'counts': {'filled': 3, 'not_found': 1, 'requires_expert_review': 0, 'conflicted': 0},
        'fill_quality': {'strict_fill_percent': 75.0, 'target_met': False},
        'xlsx': {'download_path': f'{BASE}/geotizer.xlsx', 'sha256': 'abc'},
        'audit': {'summary': {'failed': 0, 'warnings': 0}, 'gates': {'publication': 'blocked'}},
        **_final(docx=docx),
    }

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(adapter, '_user_model', _noop)
    monkeypatch.setattr(adapter, '_resolve_geotizer_callable', _noop)
    monkeypatch.setattr(adapter, '_build_agent_caller', lambda runtime: _pair())
    monkeypatch.setattr(adapter, '_build_rag_dispatcher', lambda request, user: None)
    monkeypatch.setattr(adapter, '_build_vision_evidence_caller', _noop)

    async def _workflow(**kwargs):
        return final

    monkeypatch.setattr(adapter, 'run_geotizer_workflow', _workflow)
    return await adapter.fill_geotizer(
        object_name='Лекын',
        __request__=object(),
        __user__={'id': 'u1'},
        __message_id__='m1',
    )


async def _pair():
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    return (None, StatusSettings(), None)


@pytest.mark.asyncio
async def test_the_word_card_follows_the_workbook_and_precedes_the_evidence(monkeypatch):
    """The result links the XLSX, the DOCX, then the PDF, Markdown and state
    evidence, in that order."""
    result = await _render_result(monkeypatch)

    order = [result.index(f'{PROXY}/{name}') for name in (
        'geotizer.xlsx', 'geotizer.docx', 'source_report.pdf', 'source_report.md', 'state.json',
    )]

    assert all(index >= 0 for index in order)
    assert order == sorted(order)


@pytest.mark.asyncio
async def test_the_real_result_links_all_five_artefacts(monkeypatch):
    """The real result links all five artefacts, the DOCX under its draft CPR
    label."""
    result = await _render_result(monkeypatch)

    assert result.count('](/api/v1/geotizer/files/run-1/') == 5
    assert f'[Скачать черновик CPR-отчёта DOCX]({PROXY}/geotizer.docx)' in result


@pytest.mark.asyncio
async def test_the_real_result_drops_one_link_when_the_service_renders_no_card(monkeypatch):
    result = await _render_result(monkeypatch, docx=False)

    assert result.count('](/api/v1/geotizer/files/run-1/') == 4
    assert 'geotizer.docx' not in result
    for name in ('source_report.pdf', 'source_report.md', 'state.json'):
        assert f'{PROXY}/{name}' in result


def test_the_markdown_and_the_attachments_offer_the_same_five_artefacts():
    """The Markdown links and the chat attachments list the same five artefacts
    in the same order."""
    attached = [item['url'] for item in attachment_files(
        f'{PROXY}/geotizer.xlsx', _paths(), object_name='Лекын',
    )]
    linked = [
        f'{PROXY}/geotizer.xlsx',
        *(re.findall(r'\]\(([^)]+)\)', card_docx_link(_paths()))),
        _paths()['pdf'],
        _paths()['markdown'],
        _paths()['state'],
    ]

    assert attached == linked


@pytest.mark.parametrize('artifact', [
    'geotizer.xlsx', 'geotizer.docx', 'source_report.pdf', 'source_report.md', 'state.json',
])
def test_every_linked_path_goes_through_the_authenticated_proxy(artifact):
    """Every linked artefact path goes through the `/api/v1` proxy, not the raw
    service path."""
    rendered = card_docx_link(_paths()) + ' '.join(_paths().values())

    if artifact != 'geotizer.xlsx':
        assert f'/api/v1/geotizer/files/run-1/{artifact}' in rendered
        assert f']({BASE}/{artifact})' not in rendered
