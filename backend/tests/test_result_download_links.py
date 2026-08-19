"""The download-link block of the result markdown, which nothing tested.

The card renders five artefacts and linked four of them: the DOCX was served,
routed, attached to the chat and given a mime type, and never appeared in the
Markdown a reader actually clicks.

Nothing caught it, and the reason is worth stating because it is the same
shape as the defect. Deleting *every* link from the result -- the XLSX
included -- left the suite at `1052 passed`. The `if report_paths:` block is
unreachable in every existing card-building test, because they all pass
`report_paths={}`. So there was no test asserting the order, no test asserting
the presence of any link, and no test to change: the ordering question had no
test settling it, only the appearance of one.

These are that missing coverage, written around the artefact that was lost.
"""

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
    """The whole reason `_proxy_source_report_paths` keeps `docx` optional. A
    subscript here would turn a version skew into a `KeyError` and lose the
    finished run's result after the card was built."""
    assert card_docx_link(_paths(docx=False)) == ''
    assert card_docx_link({}) == ''
    assert card_docx_link(None) == ''
    # and the other three survive
    assert set(_paths(docx=False)) == {'markdown', 'pdf', 'state'}


def test_the_label_says_draft_and_not_only_report():
    """«Скачать отчёт CPR» without a qualifier is the one label that could be
    forwarded as a certification, and a link is what gets forwarded.

    This used to assert the opposite -- that the link must not say CPR at all
    -- on the grounds that the document's own second paragraph denied being
    one. That denial is gone, because it was the one sentence in the document
    that was false, and it had a cost: the orchestration agent read the file as
    a card and told a user no CPR report had been produced when one had.
    """
    link = card_docx_link(_paths())

    assert 'CPR' in link
    assert 'черновик' in link.casefold()
    # And no brackets in the label: `[… (CPR) …](url)` is legal Markdown that a
    # naive `split('(')` mis-parses, which is what this file used to do.
    assert '(' not in link[: link.index('](')]


def test_the_label_does_not_claim_the_readiness_document_s_name():
    """A-44 is still open and still not settled by a link. `CPR Readiness` vs
    `Draft CPR` is the *readiness* document's title, and this is not that
    document."""
    assert 'готовност' not in card_docx_link(_paths()).casefold()


def test_the_link_the_title_and_the_filename_still_agree():
    """Three names for one file is how a reader stops trusting any of them.
    They agreed on «card» before and they agree on «draft CPR report» now --
    what mattered was never which name, only that it is one name.

    The filename is asserted here as a literal because it is minted in
    `gis_service` and reaches this repository only as a string; a mismatch is
    exactly the version skew this file exists to catch.
    """
    link = card_docx_link(_paths()).casefold()

    assert 'cpr' in link
    assert 'черновик' in link
    assert 'DOCX' in card_docx_link(_paths())
    assert 'карту geoteaser' not in link


async def _render_result(monkeypatch, *, docx=True):
    """Drive the real `fill_geotizer` and return the Markdown a reader sees.

    Everything outside the adapter is stubbed -- the GIS call, the specialist
    caller, the RAG dispatcher, the vision caller and the workflow itself --
    so what is exercised is exactly the result assembly and nothing else.

    Building the expected string in the test instead is what let the missing
    link survive: an assertion that reconstructs the rendering agrees with
    itself no matter what the adapter does. Deleting `card_docx_link` from the
    adapter leaves a reconstructing test green.
    """
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

    return (None, StatusSettings())


@pytest.mark.asyncio
async def test_the_word_card_follows_the_workbook_and_precedes_the_evidence(monkeypatch):
    """The ordering decision, pinned against the real result.

    `attachment_files` already places these five artefacts as card-then-
    evidence, and the Markdown now agrees. This is not a claim that the Word
    file outranks the workbook; it is a claim that the two renderings of the
    card belong together, above the evidence that supports them.

    If that is the wrong product call, this is the test to argue with -- which
    is the point. Before this file there was no test asserting the order, so
    the ordering was settled by nobody and looked settled by CI.
    """
    result = await _render_result(monkeypatch)

    order = [result.index(f'{PROXY}/{name}') for name in (
        'geotizer.xlsx', 'geotizer.docx', 'source_report.pdf', 'source_report.md', 'state.json',
    )]

    assert all(index >= 0 for index in order)
    assert order == sorted(order)


@pytest.mark.asyncio
async def test_the_real_result_links_all_five_artefacts(monkeypatch):
    """The defect itself: five artefacts served, four linked.

    The label moved -- «карту GeoTeaser» became «черновик CPR-отчёта» when the
    document stopped denying it was the CPR report -- and the count is what
    this test was always about. Both are asserted so a renamed label cannot
    quietly drop a link on its way past.
    """
    result = await _render_result(monkeypatch)

    assert result.count('](/api/v1/geotizer/files/run-1/') == 5
    assert f'[Скачать черновик CPR-отчёта DOCX]({PROXY}/geotizer.docx)' in result


@pytest.mark.asyncio
async def test_the_real_result_drops_one_link_when_the_service_renders_no_card(monkeypatch):
    result = await _render_result(monkeypatch, docx=False)

    assert result.count('](/api/v1/geotizer/files/run-1/') == 4
    assert 'geotizer.docx' not in result
    # and the three that do exist are still there
    for name in ('source_report.pdf', 'source_report.md', 'state.json'):
        assert f'{PROXY}/{name}' in result


def test_the_markdown_and_the_attachments_offer_the_same_five_artefacts():
    """Two lists of the same files, built in different modules, and a reader
    who sees four links beside five attachments has to work out which is
    lying. That is exactly the state this fixes."""
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
    """A raw `/geotizer/files/...` is the GIS service's own path and is not
    reachable from a browser session."""
    rendered = card_docx_link(_paths()) + ' '.join(_paths().values())

    if artifact != 'geotizer.xlsx':
        assert f'/api/v1/geotizer/files/run-1/{artifact}' in rendered
        assert f']({BASE}/{artifact})' not in rendered
