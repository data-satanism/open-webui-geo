"""CPR-SLICE-01 step 3: the artefacts.

`cpr_readiness.docx`, the PDF, `coverage.json`, the source report, the audit
report and the run manifest, all from one projection.

Two things are asserted harder than the rest, because they are what the
assignment turns into checkable controls: the document carries
`DRAFT — NOT A JORC/NAEN CERTIFICATION` where deleting it is not one keystroke,
and re-rendering the same projection produces the same bytes.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from open_webui.services.artifacts.cpr import audit, coverage, narrative, project, render
from open_webui.services.artifacts.cpr.errors import CprContractError

DATA = Path(__file__).resolve().parent / 'data'
FONT = Path(__file__).resolve().parents[1] / 'open_webui/static/fonts/NotoSans-Regular.ttf'


@pytest.fixture(scope='module')
def dossier():
    return json.loads((DATA / 'lekyn-dossier.example.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def projection(dossier):
    return project.build_projection(dossier)


@pytest.fixture(scope='module')
def blocks(projection, dossier):
    return narrative.plan_narrative(projection, dossier)


@pytest.fixture(scope='module')
def titles():
    return coverage.requirement_titles()


@pytest.fixture(scope='module')
def docx(projection, dossier, blocks, titles):
    return render.render_docx(projection, dossier, blocks, titles)


def docx_part(payload: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.read(name).decode('utf-8')


# -- the watermark ---------------------------------------------------------


def test_the_document_is_marked_a_draft_and_not_a_certification(docx):
    assert render.DRAFT_WATERMARK == 'DRAFT — NOT A JORC/NAEN CERTIFICATION'
    assert render.docx_watermark_is_present(docx) is True


def test_the_marking_lives_in_the_page_header(docx):
    """§10 makes it a checkable control. A banner in the body can be deleted
    with one keystroke; a header repeats on every printed page."""
    assert render.DRAFT_WATERMARK in docx_part(docx, 'word/header1.xml')
    assert 'headerReference' in docx_part(docx, 'word/document.xml')


def test_a_document_without_the_header_fails_the_check(docx):
    """The check reads the bytes rather than trusting the renderer, so strip
    the header and it must notice."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx)) as source:
        with zipfile.ZipFile(buffer, 'w') as target:
            for item in source.namelist():
                if item != 'word/header1.xml':
                    target.writestr(item, source.read(item))

    assert render.docx_watermark_is_present(buffer.getvalue()) is False


def test_the_body_also_says_it_is_not_a_certification(docx):
    body = docx_part(docx, 'word/document.xml')

    assert render.DRAFT_WATERMARK in body
    assert 'не подписан Компетентным лицом' in body


# -- the .docx -------------------------------------------------------------


def test_the_docx_is_a_valid_package(docx):
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            '[Content_Types].xml',
            '_rels/.rels',
            'word/_rels/document.xml.rels',
            'word/header1.xml',
            'word/document.xml',
        }


def test_rendering_twice_gives_the_same_bytes(projection, dossier, blocks, titles, docx):
    """§9 requires a re-render to reach the same artefact hashes. A ZIP that
    stamped the current time would fail that on the second run."""
    assert render.render_docx(projection, dossier, blocks, titles) == docx


def test_cyrillic_survives_the_round_trip(docx):
    body = docx_part(docx, 'word/document.xml')

    assert 'Лекын-Тальбейская площадь' in body
    assert 'Отчёт о готовности к CPR' in body


def test_the_document_cites_ids_and_never_restates_a_value(docx, dossier):
    """The dossier owns values. If the document carried them too, the two
    could disagree and nobody would know which was the fact."""
    body = docx_part(docx, 'word/document.xml')

    assert 'clm-licence-number' in body
    for value in ('СЫК 00000 БР', '12', '20', '47.3'):
        assert f'<w:t xml:space="preserve">{value}</w:t>' not in body


def test_the_conflict_is_reported_as_a_conflict(docx):
    body = docx_part(docx, 'word/document.xml')

    assert 'Расхождение источников сохранено' in body
    assert 'cft-au-p1' in body


def test_an_absence_carries_its_reason_and_the_expert_action(docx):
    body = docx_part(docx, 'word/document.xml')

    assert 'Если нет, то почему нет' in body
    assert 'act-drilling-programme' in body


def test_the_document_says_what_the_denominator_was(docx):
    body = docx_part(docx, 'word/document.xml')

    assert 'Отвечено 3 из 88' in body
    assert 'срез каталога, а не измерение полноты' in body


# -- the PDF ---------------------------------------------------------------


def test_the_pdf_renders_the_same_document(projection, dossier, blocks, titles):
    payload = render.render_pdf(projection, dossier, blocks, titles, font_path=FONT)

    assert payload.startswith(b'%PDF-')
    assert b'%%EOF' in payload[-1024:]
    assert b'FontFile2' in payload, 'the Unicode font must be embedded'


def test_the_pdf_is_deterministic(projection, dossier, blocks, titles):
    """fpdf2 stamps the current time into /CreationDate by default. Pinned to
    the freeze instead: the document's date is a property of the evidence, not
    of when someone pressed the button."""
    first = render.render_pdf(projection, dossier, blocks, titles, font_path=FONT)
    second = render.render_pdf(projection, dossier, blocks, titles, font_path=FONT)

    assert first == second
    assert re.search(rb'/CreationDate\s*\(D:20260812090000', first)


def test_the_pdf_refuses_to_render_without_a_unicode_font(projection, dossier, blocks, titles):
    """The built-in fonts are Latin-1 and the document is Russian, so a
    fallback would render mojibake and look like it had worked."""
    with pytest.raises(CprContractError, match='Unicode font'):
        render.render_pdf(projection, dossier, blocks, titles, font_path=Path('/no/such/font.ttf'))


# -- coverage.json ---------------------------------------------------------


def test_coverage_json_has_one_row_per_requirement(projection, dossier):
    payload = json.loads(render.render_coverage_json(projection, dossier))

    assert len(payload['requirements']) == 74
    assert {row['requirement_id'] for row in payload['requirements']} == set(project.slice_requirement_ids())
    assert all(row['state'] for row in payload['requirements'])


def test_coverage_json_reports_the_denominator_and_refuses_to_call_it_a_score(projection, dossier):
    payload = json.loads(render.render_coverage_json(projection, dossier))

    assert payload['completeness']['denominator'] == 88
    assert payload['completeness']['measurable'] is False
    assert payload['projection_scope'] == 'reference_slice'


def test_coverage_json_keeps_every_reason(projection, dossier):
    payload = json.loads(render.render_coverage_json(projection, dossier))

    for row in payload['requirements']:
        if row['state'] in {'missing', 'not_applicable', 'blocked_expert'}:
            assert row['if_not_why_not']['reason'], row['requirement_id']


# -- the source report -----------------------------------------------------


def test_the_source_report_lists_every_source(dossier):
    report = render.render_source_report(dossier).decode('utf-8')

    for source in dossier['sources']:
        assert source['title'] in report
        assert source['source_version'] in report


def test_the_source_report_says_access_was_partial(dossier):
    """`acl_decision: partial` with two sources excluded. Absence of a fact and
    absence of permission are different things, and the report distinguishes
    them."""
    report = render.render_source_report(dossier).decode('utf-8')

    assert 'Исключено по правам доступа: 2' in report
    assert render.DRAFT_WATERMARK in report


# -- the audit report ------------------------------------------------------


def test_the_audit_report_states_it_is_not_a_conformance_check(projection, dossier):
    report = render.render_audit_report(audit.audit_projection(projection, dossier)).decode('utf-8')

    assert 'не** означает соответствия JORC' in report or 'не означает соответствия JORC' in report
    assert 'блокирующих: 0' in report


def test_the_audit_report_lists_the_unaddressed_requirements(projection, dossier):
    report = render.render_audit_report(audit.audit_projection(projection, dossier)).decode('utf-8')

    assert 'unaddressed' in report
    assert 'CPR-0.1' in report


# -- the manifest ----------------------------------------------------------


@pytest.fixture
def manifest(projection, dossier, blocks, titles):
    artifacts = {
        'cpr_readiness.docx': render.render_docx(projection, dossier, blocks, titles),
        'coverage.json': render.render_coverage_json(projection, dossier),
        'source_report.md': render.render_source_report(dossier),
        'audit.md': render.render_audit_report(audit.audit_projection(projection, dossier)),
    }
    return json.loads(
        render.render_manifest(
            projection,
            dossier,
            artifacts,
            component_commits={'open-webui-geo': 'a' * 40},
            contract_versions={
                'dossier_schema': 1,
                'cpr_requirements': 'cpr_requirements.v1',
                'geotizer_template': 'geotizer_object.v1',
                'projection': 'cpr_slice_projection.v1',
            },
            snapshots={
                'sources': {'snapshot_id': 'src-1', 'taken_at': '2026-08-12T09:00:00Z'},
                'gis': {'snapshot_id': 'gis-2026-08-10', 'taken_at': '2026-08-10T00:00:00Z'},
                'index': {'snapshot_id': 'idx-7', 'taken_at': '2026-08-11T00:00:00Z'},
            },
        )
    )


def test_the_manifest_pins_every_replay_counter_to_zero(manifest):
    """§9: re-rendering must reach the same hashes without retrieval, a model,
    GIS or the web. A non-zero count is a contract violation, not a metric."""
    assert manifest['reproduction'] == {
        'retrieval_calls': 0,
        'model_calls': 0,
        'gis_calls': 0,
        'web_calls': 0,
    }


def test_the_manifest_hashes_every_artifact(manifest):
    names = {artifact['name'] for artifact in manifest['artifacts']}

    assert names == {'cpr_readiness.docx', 'coverage.json', 'source_report.md', 'audit.md'}
    for artifact in manifest['artifacts']:
        assert re.fullmatch(r'[0-9a-f]{64}', artifact['content_sha256']), artifact['name']
        assert artifact['bytes'] > 0


def test_the_manifest_records_the_watermark_on_the_document(manifest):
    document = next(a for a in manifest['artifacts'] if a['name'].endswith('.docx'))

    assert document['watermark'] == render.DRAFT_WATERMARK


def test_the_manifest_carries_the_idempotency_key_parts(manifest, dossier):
    """project_id + artifact_set + frozen_inputs_hash. Repeating the command
    with the same key must return this run."""
    assert manifest['project_id'] == dossier['project_scope']['project_id']
    assert manifest['frozen_inputs_hash'] == dossier['frozen_inputs_hash']
    assert manifest['artifact_set'] == ['cpr_readiness', 'source_report', 'audit']


def test_the_manifest_offers_a_durable_download_path(manifest):
    for artifact in manifest['artifacts']:
        assert artifact['download_path'].startswith('/geotizer/files/')


def test_every_artifact_set_entry_is_a_known_artifact_kind(manifest):
    from open_webui.services.core.idempotency import ARTIFACT_KINDS

    for name in manifest['artifact_set']:
        assert name in ARTIFACT_KINDS, name


def test_the_pdf_and_the_docx_say_the_same_thing(projection, dossier, blocks, titles, docx):
    """"One content model, two renderers" -- checked rather than asserted.

    It was not true. `_plain_lines`, the model behind the PDF, omitted three
    line kinds the DOCX emits: the supporting estimate ids, the supporting
    figure ids, and the ACL disclosure naming how many sources were withheld.
    The PDF was a strict subset, so the same run produced one document that
    cited its evidence and disclosed withheld sources and one that quietly did
    neither -- and a reader comparing them would have no way to tell which was
    complete.
    """
    import io
    import re
    import zipfile

    from open_webui.services.artifacts.cpr import render

    xml = zipfile.ZipFile(io.BytesIO(docx)).read('word/document.xml').decode('utf-8')
    in_docx = {text for text in re.findall(r'<w:t[^>]*>([^<]*)</w:t>', xml) if text.strip()}
    in_pdf = {text for text, _ in render._plain_lines(projection, dossier, blocks, titles) if text.strip()}

    assert sorted(in_docx - in_pdf) == [], 'lines the DOCX carries and the PDF drops'
    assert sorted(in_pdf - in_docx) == [], 'lines the PDF carries and the DOCX drops'


def test_both_documents_disclose_withheld_sources(projection, dossier, blocks, titles):
    """The ACL line is a disclosure, not decoration: it says how much of the
    evidence the reader is not being shown."""
    from open_webui.services.artifacts.cpr import render

    lines = [text for text, _ in render._plain_lines(projection, dossier, blocks, titles)]
    disclosure = [line for line in lines if line.startswith('Доступ к источникам:')]

    assert len(disclosure) == 1
    assert dossier['project_scope']['acl_decision'] in disclosure[0]
    if dossier['project_scope'].get('acl_excluded_sources'):
        assert str(dossier['project_scope']['acl_excluded_sources']) in disclosure[0]
