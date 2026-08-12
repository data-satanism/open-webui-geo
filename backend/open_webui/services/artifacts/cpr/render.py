"""Render the CPR Readiness artefacts.

CPR-SLICE-01 action 5. Produces bytes, never files: writing is an effect and
belongs to the shell, so this module stays inside the pure core and can be
tested without a filesystem.

Five artefacts come out of one projection:

    cpr_readiness.docx   the readiness document
    coverage.json        state per requirement, machine-readable
    source_report.md     every source the run stood on
    audit.md             the findings, including what nobody answered
    manifest.json        what the run was built from, and the artefact hashes

Action 6 requires the document to carry `DRAFT — NOT A JORC/NAEN CERTIFICATION`
until an expert has reviewed and signed it. It is written into the page header,
not only the body: §10 makes the marking a checkable control, and a banner in
the body can be scrolled past or deleted with one keystroke while a header
repeats on every printed page. `docx_watermark_is_present` reads it back out of
the rendered bytes, so the control is verified rather than assumed.

The `.docx` is written with the standard library. A `.docx` is a ZIP of XML
parts, `zipfile` writes one, and the alternative was a dependency for something
this file does in ninety lines.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .audit import Finding, audit_summary
from .coverage import section_coverage, semantic_completeness
from .errors import CprContractError
from .narrative import NarrativeBlock

# §2 forbids the automatic document claiming conformance or signing as a
# Competent Person. This is the marking that says so, and it is verbatim.
DRAFT_WATERMARK = 'DRAFT — NOT A JORC/NAEN CERTIFICATION'

STATE_LABEL = {
    'supported': 'подтверждено',
    'corroborated': 'подтверждено двумя источниками',
    'conflicted': 'расхождение источников',
    'missing': 'нет данных',
    'not_applicable': 'неприменимо',
    'blocked_expert': 'требуется эксперт',
}

SECTION_TITLE = {
    0: 'Введение',
    1: 'Проект',
    2: 'Геология',
    3: 'Разведка, бурение, QA/QC',
    4: 'Ресурсы',
    5: 'Технические исследования',
    6: 'Запасы',
    7: 'Аудиты',
    8: 'Прочее',
    9: 'Дополнительные пункты и глобальные правила',
}

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdHdr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>"""

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _paragraph(text: str, *, bold: bool = False, size: int | None = None) -> str:
    properties = ''
    runs = ''
    if bold or size:
        run_props = ('<w:b/>' if bold else '') + (f'<w:sz w:val="{size * 2}"/>' if size else '')
        runs = f'<w:rPr>{run_props}</w:rPr>'
        properties = f'<w:pPr><w:rPr>{run_props}</w:rPr></w:pPr>'
    return f'<w:p>{properties}<w:r>{runs}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _header_xml() -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{_W}">{_paragraph(DRAFT_WATERMARK, bold=True)}</w:hdr>'
    )


def _document_xml(paragraphs: Sequence[str]) -> str:
    body = ''.join(paragraphs)
    # The header reference lives in the section properties, so the marking
    # repeats on every page rather than appearing once at the top.
    section = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rIdHdr"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701"/></w:sectPr>'
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<w:body>{body}{section}</w:body></w:document>'
    )


def _zip(parts: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    # A fixed date and no compression timestamp: the same projection must
    # produce the same bytes, or §9's re-render check cannot compare hashes.
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode('utf-8'))
    return buffer.getvalue()


def _requirement_paragraphs(
    blocks: Sequence[NarrativeBlock],
    rows: Mapping[str, Mapping[str, Any]],
    titles: Mapping[str, str],
) -> list[str]:
    paragraphs: list[str] = []
    for block in blocks:
        paragraphs.append(
            _paragraph(
                f'{block.section}. {SECTION_TITLE.get(block.section, "")}'.strip(),
                bold=True,
                size=14,
            )
        )
        for sentence in block.sentences:
            row = rows[sentence.requirement_id]
            title = titles.get(sentence.requirement_id, '')
            paragraphs.append(_paragraph(f'{sentence.requirement_id} — {title}', bold=True))
            paragraphs.append(_paragraph(f'Состояние: {STATE_LABEL[row["state"]]}.'))
            if sentence.claim_ids:
                # Ids, not values. The document points at the dossier; it does
                # not restate it, so the two can never disagree.
                paragraphs.append(_paragraph('Основание: ' + ', '.join(sentence.claim_ids)))
            if sentence.estimate_ids:
                paragraphs.append(_paragraph('Оценки: ' + ', '.join(sentence.estimate_ids)))
            if sentence.figure_ids:
                paragraphs.append(_paragraph('Рисунки: ' + ', '.join(sentence.figure_ids)))
            if sentence.conflict_ids:
                paragraphs.append(
                    _paragraph(
                        'Расхождение источников сохранено, обе стороны приведены: ' + ', '.join(sentence.conflict_ids)
                    )
                )
            reason = row.get('if_not_why_not')
            if reason:
                paragraphs.append(_paragraph(f'Если нет, то почему нет: {reason["reason"]}'))
            if row.get('expert_action_ids'):
                paragraphs.append(_paragraph('Требуется действие эксперта: ' + ', '.join(row['expert_action_ids'])))
        if block.skipped:
            paragraphs.append(_paragraph('Неприменимо на текущей стадии: ' + ', '.join(block.skipped)))
    return paragraphs


def render_docx(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
) -> bytes:
    """`cpr_readiness.docx`, watermarked, deterministic."""
    scope = dossier['project_scope']
    rows = {row['requirement_id']: row for row in projection['coverage']}
    completeness = semantic_completeness(projection, dossier)

    paragraphs = [
        _paragraph('Отчёт о готовности к CPR', bold=True, size=18),
        _paragraph(DRAFT_WATERMARK, bold=True, size=14),
        _paragraph(f'Объект: {scope.get("object_name") or scope["project_id"]}'),
        _paragraph(f'Стадия: {scope["lifecycle_stage"]}'),
        _paragraph(f'Запуск досье: {projection["dossier_run_id"]}'),
        _paragraph(f'Заморожено: {dossier["frozen_at"]}'),
        _paragraph(
            f'Доступ к источникам: {scope["acl_decision"]}'
            + (f', исключено источников: {scope["acl_excluded_sources"]}' if scope.get('acl_excluded_sources') else '')
        ),
        _paragraph(
            f'Отвечено {completeness["answered"]} из {completeness["denominator"]} '
            f'применимых требований. Это срез каталога, а не измерение полноты.'
        ),
        _paragraph('Документ не является подтверждением соответствия JORC или НАЭН и не подписан Компетентным лицом.'),
    ]
    paragraphs.extend(_requirement_paragraphs(blocks, rows, titles))

    return _zip(
        {
            '[Content_Types].xml': _CONTENT_TYPES,
            '_rels/.rels': _ROOT_RELS,
            'word/_rels/document.xml.rels': _DOCUMENT_RELS,
            'word/header1.xml': _header_xml(),
            'word/document.xml': _document_xml(paragraphs),
        }
    )


def docx_watermark_is_present(payload: bytes) -> bool:
    """Read the marking back out of the rendered bytes.

    §10 makes the watermark a checkable control, so it is checked rather than
    assumed -- and checked in the header part, which is what survives someone
    deleting the first line of the body.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if 'word/header1.xml' not in archive.namelist():
            return False
        header = archive.read('word/header1.xml').decode('utf-8')
    return DRAFT_WATERMARK in header


def _plain_lines(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
) -> list[tuple[str, bool]]:
    """The document as (text, bold) lines. One content model, two renderers."""
    scope = dossier['project_scope']
    rows = {row['requirement_id']: row for row in projection['coverage']}
    completeness = semantic_completeness(projection, dossier)

    lines: list[tuple[str, bool]] = [
        ('Отчёт о готовности к CPR', True),
        (DRAFT_WATERMARK, True),
        (f'Объект: {scope.get("object_name") or scope["project_id"]}', False),
        (f'Стадия: {scope["lifecycle_stage"]}', False),
        (f'Запуск досье: {projection["dossier_run_id"]}', False),
        (f'Заморожено: {dossier["frozen_at"]}', False),
        (
            f'Отвечено {completeness["answered"]} из {completeness["denominator"]} '
            f'применимых требований. Это срез каталога, а не измерение полноты.',
            False,
        ),
        (
            'Документ не является подтверждением соответствия JORC или НАЭН и не подписан Компетентным лицом.',
            False,
        ),
    ]
    for block in blocks:
        lines.append((f'{block.section}. {SECTION_TITLE.get(block.section, "")}'.strip(), True))
        for sentence in block.sentences:
            row = rows[sentence.requirement_id]
            lines.append((f'{sentence.requirement_id} — {titles.get(sentence.requirement_id, "")}', True))
            lines.append((f'Состояние: {STATE_LABEL[row["state"]]}.', False))
            if sentence.claim_ids:
                lines.append(('Основание: ' + ', '.join(sentence.claim_ids), False))
            if sentence.conflict_ids:
                lines.append(
                    (
                        'Расхождение источников сохранено, обе стороны приведены: ' + ', '.join(sentence.conflict_ids),
                        False,
                    )
                )
            reason = row.get('if_not_why_not')
            if reason:
                lines.append((f'Если нет, то почему нет: {reason["reason"]}', False))
            if row.get('expert_action_ids'):
                lines.append(('Требуется действие эксперта: ' + ', '.join(row['expert_action_ids']), False))
        if block.skipped:
            lines.append(('Неприменимо на текущей стадии: ' + ', '.join(block.skipped), False))
    return lines


def _frozen_at(dossier: Mapping[str, Any]) -> Any:
    from datetime import datetime, timezone

    stamp = str(dossier['frozen_at']).replace('Z', '+00:00')
    parsed = datetime.fromisoformat(stamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def render_pdf(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
    *,
    font_path: Path,
) -> bytes:
    """The same document as a PDF.

    `font_path` is required, not optional. The built-in PDF fonts are Latin-1
    and this document is Russian, so a fallback would render mojibake and look
    like it had worked. Which font, and where it lives, is the shell's decision
    -- this only refuses to proceed without one.
    """
    from fpdf import FPDF  # imported here so the module loads without it

    if not font_path or not Path(font_path).is_file():
        raise CprContractError(
            f'render_pdf needs a Unicode font file; {font_path!r} is not one. '
            f'The document is Russian and the built-in fonts are Latin-1.'
        )

    pdf = FPDF(format='A4')
    # fpdf2 stamps the current time into /CreationDate, which would make two
    # renders of the same projection differ byte for byte and break §9's
    # re-render check. Pin it to the freeze instead: the document's date is a
    # property of the evidence, not of when someone pressed the button.
    pdf.set_creation_date(_frozen_at(dossier))
    pdf.add_font('body', '', str(font_path))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(20, 18, 12)
    pdf.add_page()

    # Same reasoning as the .docx header: §10 makes the marking a checkable
    # control, so it repeats on every page rather than sitting once at the top.
    def _stamp() -> None:
        pdf.set_y(8)
        pdf.set_font('body', size=8)
        pdf.cell(0, 5, DRAFT_WATERMARK, align='C')
        pdf.set_y(20)

    _stamp()
    page = pdf.page_no()
    for text, bold in _plain_lines(projection, dossier, blocks, titles):
        pdf.set_font('body', size=11 if bold else 9)
        pdf.multi_cell(0, 5, text)
        pdf.ln(1 if bold else 0)
        if pdf.page_no() != page:
            page = pdf.page_no()
            _stamp()

    return bytes(pdf.output())


def render_coverage_json(projection: Mapping[str, Any], dossier: Mapping[str, Any]) -> bytes:
    """`coverage.json`: one row per requirement, with why."""
    sections = section_coverage(projection, dossier)
    payload = {
        'schema_version': 1,
        'dossier_run_id': projection['dossier_run_id'],
        'projection_version': projection['projection_version'],
        'projection_scope': projection['projection_scope'],
        'completeness': semantic_completeness(projection, dossier),
        'sections': [
            {
                'section': section.section,
                'planned': section.planned,
                'applicable': section.applicable,
                'answered': section.answered,
                'conflicted': section.conflicted,
                'missing': section.missing,
                'not_applicable': section.not_applicable,
                'blocked_expert': section.blocked_expert,
                'unaddressed': list(section.unaddressed),
            }
            for section in sections
        ],
        'requirements': [
            {
                'requirement_id': row['requirement_id'],
                'state': row['state'],
                'applicability': row['applicability'],
                'render_state': row['render_state'],
                'supporting_claim_ids': row['supporting_claim_ids'],
                'supporting_estimate_ids': row['supporting_estimate_ids'],
                'supporting_figure_ids': row['supporting_figure_ids'],
                'conflict_ids': row['conflict_ids'],
                'gap_ids': row['gap_ids'],
                'expert_action_ids': row['expert_action_ids'],
                'if_not_why_not': row.get('if_not_why_not'),
            }
            for row in projection['coverage']
        ],
    }
    return _canonical_bytes(payload)


def render_source_report(dossier: Mapping[str, Any]) -> bytes:
    """`source_report.md`: every source, and what it was allowed to be."""
    scope = dossier['project_scope']
    lines = [
        '# Отчёт об источниках',
        '',
        f'Объект: {scope.get("object_name") or scope["project_id"]}  ',
        f'Запуск досье: {dossier["dossier_run_id"]}  ',
        f'Заморожено: {dossier["frozen_at"]}  ',
        f'Решение по доступу: {scope["acl_decision"]}',
        '',
    ]
    if scope.get('acl_excluded_sources'):
        lines += [
            f'**Исключено по правам доступа: {scope["acl_excluded_sources"]}.** '
            'Отсутствие факта и отсутствие разрешения — разные вещи, и здесь '
            'они различимы.',
            '',
        ]
    lines += [
        '| Источник | Вид | Версия | Авторитет | Доступ | Состояние |',
        '|---|---|---|---|---|---|',
    ]
    for source in dossier.get('sources') or ():
        lines.append(
            '| {title} | {kind} | {version} | {authority} | {acl} | {state} |'.format(
                title=source.get('title') or source['source_id'],
                kind=source.get('source_type') or '—',
                version=source['source_version'],
                authority=source['authority_kind'],
                acl=source['acl_decision'],
                state=source['state'],
            )
        )
    lines += ['', f'_{DRAFT_WATERMARK}_', '']
    return '\n'.join(lines).encode('utf-8')


def render_audit_report(findings: Sequence[Finding]) -> bytes:
    """`audit.md`: what the run got wrong, and what nobody answered."""
    summary = audit_summary(findings)
    lines = [
        '# Аудит проекции',
        '',
        f'Замечаний: {summary["findings"]}, из них блокирующих: {summary["blocking"]}.',
        '',
        'Чистый аудит означает, что ни одно правило не нарушено. Он **не** '
        'означает соответствия JORC или НАЭН: автоматический артефакт такого '
        'заявления не делает.',
        '',
    ]
    if findings:
        lines += ['| Код | Важность | Требование | Подробности |', '|---|---|---|---|']
        for finding in findings:
            lines.append(
                f'| {finding.code} | {finding.severity} | {finding.requirement_id or "—"} | {finding.detail} |'
            )
    else:
        lines.append('Замечаний нет.')
    lines.append('')
    return '\n'.join(lines).encode('utf-8')


def _canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + '\n').encode('utf-8')


def render_manifest(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    artifacts: Mapping[str, bytes],
    *,
    component_commits: Mapping[str, str],
    contract_versions: Mapping[str, Any],
    snapshots: Mapping[str, Any],
) -> bytes:
    """`manifest.json`: what the run was built from, and what came out.

    The four replay counters are pinned to zero because §9 requires
    re-rendering from this manifest to reach the same artefact hashes without
    retrieval, a model, GIS or the web. A non-zero count is a contract
    violation, not a metric.
    """
    kinds = {
        'cpr_readiness.docx': 'docx',
        'coverage.json': 'json',
        'source_report.md': 'markdown',
        'audit.md': 'markdown',
    }
    payload = {
        'schema_version': 1,
        'dossier_run_id': projection['dossier_run_id'],
        'project_id': dossier['project_scope']['project_id'],
        'artifact_set': ['cpr_readiness', 'source_report', 'audit'],
        'frozen_inputs_hash': dossier['frozen_inputs_hash'],
        'created_at': dossier['frozen_at'],
        'component_commits': dict(component_commits),
        'contract_versions': dict(contract_versions),
        'snapshots': dict(snapshots),
        'artifacts': [
            {
                'name': name,
                'kind': kinds.get(name, 'json'),
                'content_sha256': hashlib.sha256(payload_bytes).hexdigest(),
                'bytes': len(payload_bytes),
                'download_path': f'/geotizer/files/{projection["dossier_run_id"]}/{name}',
                'watermark': DRAFT_WATERMARK if name.endswith('.docx') else None,
            }
            for name, payload_bytes in sorted(artifacts.items())
        ],
        'reproduction': {
            'retrieval_calls': 0,
            'model_calls': 0,
            'gis_calls': 0,
            'web_calls': 0,
        },
    }
    return _canonical_bytes(payload)


__all__ = [
    'DRAFT_WATERMARK',
    'docx_watermark_is_present',
    'render_audit_report',
    'render_coverage_json',
    'render_docx',
    'render_manifest',
    'render_source_report',
]
