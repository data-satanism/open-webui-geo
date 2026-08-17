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

What the document needs to be signable, and why each part is here:

`word/styles.xml` carries real `Heading1`/`Heading2`/`Heading3` style ids. The
customer template ships 34 obfuscated style ids (`a`, `1`, `2`, ...) and no
heading among them, so reusing its ids would produce a document Word cannot
build a navigation pane or a table of contents from. At tens of pages that is
the difference between a reviewer reading the report and a reviewer scrolling
it. Both the `[Content_Types].xml` override and the `document.xml.rels` entry
have to be present or Word repairs the file on open and silently drops the
styles.

Section numbers are literal text and no heading carries `w:numPr`. Word
auto-numbering renumbers everything after a deleted subsection, and
`coverage.json` keys on requirement ids that would then no longer match the
document a reviewer is holding.

`word/footer1.xml` carries `стр. N из M` as `PAGE`/`NUMPAGES` fields. A page
count is what tells a signer whether they are holding the whole document.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, unescape

from .audit import Finding, audit_summary
from .catalog import requirements_by_id
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

# The template's own section headings, verbatim. They are rendered as literal
# text -- no `w:numPr` anywhere in a heading -- because Word auto-numbering
# renumbers every following subsection when one is deleted, and `coverage.json`
# would then key on numbers the document no longer carries.
SECTION_TITLE = {
    0: 'Раздел 0. Введение',
    1: 'Раздел 1. Информация о проекте (Общие сведения)',
    2: 'Раздел 2. Геологическая обстановка, месторождение, минерализация',
    3: 'Раздел 3. Разведка и бурение, методы отбора проб, анализы и технологические испытания',
    4: 'Раздел 4. Оценка и отчётность о результатах разведки, минеральных ресурсах',
    5: 'Раздел 5. Технические исследования (горные работы и проектирование)',
    6: 'Раздел 6. Оценка и отчётность о запасах полезных ископаемых',
    7: 'Раздел 7. Аудиты и обзоры',
    8: 'Раздел 8. Другая релевантная информация',
    # Not one of the template's nine. The catalog carries an extra bucket for
    # the 11 mandatory items and 7 global rules, which belong to the report as
    # a whole rather than to a numbered section; dropping it would drop 18
    # requirements out of the document.
    9: 'Раздел 9. Дополнительные пункты и глобальные правила',
}

# Sections 0-8 name a subsection group by the title its questions share. `ADD`
# and `GEN` are the two where they do not share one, so the group is named from
# the halves of section 9's own title rather than from an arbitrary member.
SUBSECTION_GROUP_TITLE = {
    'ADD': 'Дополнительные пункты',
    'GEN': 'Глобальные правила',
}

ESTIMATE_COLUMNS = (
    'Категория',
    'Вид оценки',
    'Объём руды',
    'Содержание',
    'Металл',
    'Дата',
    'Источник',
)

# Fixed widths in twips summing to the 9355 twips (16.5 cm) between the
# margins. Without `tblLayout fixed` Word re-fits the columns to content and
# the locator column swallows the numbers the table exists to compare.
ESTIMATE_COLUMN_WIDTHS = (900, 1500, 1100, 1100, 1100, 1100, 2555)

# `exploration_target` is deliberately absent. JORC forbids reporting an
# exploration target as a resource, and a table whose header row says
# `Категория` alongside a resource and a reserve is exactly the aggregation
# §10 and the template's paragraph 13 forbid.
RESOURCE_AND_RESERVE_KINDS = frozenset({'forecast_resource', 'mineral_resource', 'ore_reserve'})

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels"
 ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/header1.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

# A part Word cannot reach through a relationship is a part Word does not read.
# `styles.xml` present in the ZIP but unreferenced here is the failure that
# looks like nothing happened: the file opens, and every heading is body text.
_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdStyles" Target="styles.xml"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"/>
<Relationship Id="rIdHdr" Target="header1.xml"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"/>
<Relationship Id="rIdFtr" Target="footer1.xml"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"/>
</Relationships>"""

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_V = 'urn:schemas-microsoft-com:vml'
_O = 'urn:schemas-microsoft-com:office:office'
_W10 = 'urn:schemas-microsoft-com:office:word'

_SERIF = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'

# The typography, in the units a human uses. The three OOXML conversions
# happen in exactly one place, `_style_xml`, because each of them is silent
# when wrong: `w:sz` is half-points, so 14 renders smaller than the body text
# rather than larger; `w:spacing` is twentieths of a point, so 18 is a hair
# instead of a line; `w:ind` is twips.
_BODY_POINTS = 12
_BODY_INDENT_CM = 1.25
_TWIPS_PER_CM = 1440 / 2.54

# styleId -> Word's built-in style name, outline level, size in points,
# italic, and the space before and after in points. All three headings are
# bold and all three carry `keepNext`, so those are not per-style.
_HEADING_STYLES = {
    'Heading1': {'name': 'heading 1', 'outline': 0, 'points': 14, 'italic': False, 'before': 18, 'after': 12},
    'Heading2': {'name': 'heading 2', 'outline': 1, 'points': 12, 'italic': False, 'before': 12, 'after': 6},
    'Heading3': {'name': 'heading 3', 'outline': 2, 'points': 12, 'italic': True, 'before': 6, 'after': 0},
}

# The WordArt shape type Word itself writes for a watermark. Reproduced rather
# than approximated: a `v:shape` whose `type` points at a shapetype the package
# does not define renders as an empty box, which is a watermark that is not
# there on a document whose whole point is that the marking cannot be lost.
_WATERMARK_SHAPETYPE = (
    '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800"'
    ' path="m@7,l@8,m@5,21600l@11,21600e">'
    '<v:formulas><v:f eqn="sum #0 0 10800"/><v:f eqn="prod #0 2 1"/>'
    '<v:f eqn="sum 21600 0 @1"/><v:f eqn="sum 0 0 @2"/><v:f eqn="sum 21600 0 @3"/>'
    '<v:f eqn="if @0 @3 0"/><v:f eqn="if @0 21600 @1"/><v:f eqn="if @0 0 @2"/>'
    '<v:f eqn="if @0 @4 21600"/><v:f eqn="mid @5 @6"/><v:f eqn="mid @8 @5"/>'
    '<v:f eqn="mid @7 @8"/><v:f eqn="mid @6 @7"/><v:f eqn="sum @6 0 @5"/></v:formulas>'
    '<v:path textpathok="t" o:connecttype="custom"'
    ' o:connectlocs="@9,0;@10,10800;@11,21600;@12,10800" o:connectangles="270,180,90,0"/>'
    '<v:textpath on="t" fitshape="t"/>'
    '<v:handles><v:h position="#0,bottomRight" xrange="6629,14971"/></v:handles>'
    '</v:shapetype>'
)


def _attr(value: str) -> str:
    """Escape for an XML attribute, `"` included.

    The watermark travels in `v:textpath/@string`, not in element text, and
    `escape()` alone leaves a quote in place -- which would close the attribute
    and produce a header part that does not parse.
    """
    return escape(value, {'"': '&quot;'})


def _run_properties(*, bold: bool = False, italic: bool = False, size: int | None = None) -> str:
    return ('<w:b/>' if bold else '') + ('<w:i/>' if italic else '') + (f'<w:sz w:val="{size * 2}"/>' if size else '')


def _paragraph(
    text: str,
    *,
    style: str | None = None,
    bold: bool = False,
    italic: bool = False,
    size: int | None = None,
    first_line: int | None = None,
    align: str | None = None,
) -> str:
    run_props = _run_properties(bold=bold, italic=italic, size=size)
    runs = f'<w:rPr>{run_props}</w:rPr>' if run_props else ''
    paragraph_props = (
        (f'<w:pStyle w:val="{style}"/>' if style else '')
        + (f'<w:ind w:firstLine="{first_line}"/>' if first_line is not None else '')
        + (f'<w:jc w:val="{align}"/>' if align else '')
        + (f'<w:rPr>{run_props}</w:rPr>' if run_props else '')
    )
    properties = f'<w:pPr>{paragraph_props}</w:pPr>' if paragraph_props else ''
    return f'<w:p>{properties}<w:r>{runs}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _style_xml(style_id: str, spec: Mapping[str, Any]) -> str:
    """One heading style, converted from points into OOXML's own units.

    `w:ind w:firstLine="0"` is not decoration: `Heading1` is based on `Normal`
    and would otherwise inherit the body's 1.25 cm first-line indent, so every
    heading in the document would start one indent level deeper than the text
    it heads. `w:outlineLvl` is what puts the heading in Word's navigation
    pane and in a generated table of contents.
    """
    italic = '<w:i/>' if spec['italic'] else ''
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}">'
        f'<w:name w:val="{spec["name"]}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
        f'<w:uiPriority w:val="9"/><w:qFormat/>'
        f'<w:pPr><w:keepNext/>'
        f'<w:spacing w:before="{spec["before"] * 20}" w:after="{spec["after"] * 20}"'
        f' w:line="240" w:lineRule="auto"/>'
        f'<w:ind w:firstLine="0"/><w:jc w:val="left"/>'
        f'<w:outlineLvl w:val="{spec["outline"]}"/></w:pPr>'
        f'<w:rPr>{_SERIF}<w:b/>{italic}<w:sz w:val="{spec["points"] * 2}"/></w:rPr></w:style>'
    )


def _styles_xml() -> str:
    """`word/styles.xml`: a Normal body style and three real heading styleIds.

    The customer template ships 34 obfuscated style ids (`a`, `1`, `2`, ...)
    and not one heading among them. Reusing those ids would produce a document
    with no outline, and a reviewer working through tens of pages would have no
    navigation pane and no table of contents to reach a section by.
    """
    indent = round(_BODY_INDENT_CM * _TWIPS_PER_CM)
    normal = (
        f'<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        f'<w:name w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        f'<w:ind w:firstLine="{indent}"/><w:jc w:val="both"/></w:pPr>'
        f'<w:rPr>{_SERIF}<w:sz w:val="{_BODY_POINTS * 2}"/></w:rPr></w:style>'
    )
    defaults = (
        f'<w:docDefaults>'
        f'<w:rPrDefault><w:rPr>{_SERIF}<w:sz w:val="{_BODY_POINTS * 2}"/>'
        f'<w:szCs w:val="{_BODY_POINTS * 2}"/></w:rPr></w:rPrDefault>'
        f'<w:pPrDefault><w:pPr>'
        f'<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        f'</w:pPr></w:pPrDefault></w:docDefaults>'
    )
    headings = ''.join(_style_xml(style_id, spec) for style_id, spec in _HEADING_STYLES.items())
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{_W}">{defaults}{normal}{headings}</w:styles>'
    )


def _cell(text: str, width: int, *, bold: bool) -> str:
    body = _paragraph(text, bold=bold, size=10, first_line=0, align='left')
    return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>{body}</w:tc>'


def _row(values: Sequence[str], *, header: bool) -> str:
    # `w:tblHeader` is what repeats the header row after a page break. Without
    # it a table that runs over a page turns into a block of unlabelled numbers
    # -- which for a resource table is worse than no table.
    properties = '<w:trPr><w:tblHeader/></w:trPr>' if header else ''
    cells = ''.join(
        _cell(value, width, bold=header) for value, width in zip(values, ESTIMATE_COLUMN_WIDTHS, strict=True)
    )
    return f'<w:tr>{properties}{cells}</w:tr>'


def _table_xml(rows: Sequence[Sequence[str]]) -> str:
    """A seven-column estimate table, 0.5 pt single black borders, no shading.

    Prose defeats the comparison the template's own rules require: paragraph 12
    asks for separate figures per resource/reserve category and forbids
    aggregating without splitting them, and paragraph 13 forbids adding
    resources to reserves. A reader can only check either by putting the
    categories side by side.

    Seven columns is what fits the 16.5 cm between the margins at 10 pt, so
    cut-off grade, method and spatial domain go in a note line beneath the
    table rather than in an eighth, ninth and tenth column that would squeeze
    the numbers out of legibility.
    """
    edges = ''.join(
        f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')
    )
    grid = ''.join(f'<w:gridCol w:w="{width}"/>' for width in ESTIMATE_COLUMN_WIDTHS)
    body = _row(ESTIMATE_COLUMNS, header=True) + ''.join(_row(row, header=False) for row in rows)
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{sum(ESTIMATE_COLUMN_WIDTHS)}" w:type="dxa"/>'
        # `tblBorders` before `tblLayout`: CT_TblPrBase is an xsd:sequence and the
        # schema puts borders at position 11 and layout at 13. Written the other way
        # round, zipfile reads the package back happily and Word shows a repair
        # dialog -- and what it repairs away is the 0.5 pt grid on the one table the
        # document exists to make comparable.
        f'<w:tblBorders>{edges}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
        f'<w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>'
    )


def _header_xml() -> str:
    """The marking as a real watermark: grey, diagonal, behind the text.

    It was bold black text in the header, which reads as a title and prints
    like one. A reviewer who forwards a page of that has forwarded something
    that looks like a heading someone forgot to delete. `rotation:315` and a
    negative `z-index` put it across the page and under the body, where a
    watermark is recognised as a watermark rather than as content.
    """
    shape = (
        '<v:shape id="CprDraftWatermark" o:spid="_x0000_s2049" type="#_x0000_t136"'
        ' style="position:absolute;margin-left:0;margin-top:0;width:480pt;height:96pt;'
        'rotation:315;z-index:-251658752;mso-position-horizontal:center;'
        'mso-position-horizontal-relative:margin;mso-position-vertical:center;'
        'mso-position-vertical-relative:margin" o:allowincell="f" fillcolor="#c0c0c0" stroked="f">'
        '<v:fill opacity=".5"/>'
        '<v:textpath style="font-family:&quot;Times New Roman&quot;;font-size:1pt"'
        f' string="{_attr(DRAFT_WATERMARK)}"/>'
        '<w10:wrap anchorx="margin" anchory="margin"/>'
        '</v:shape>'
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{_W}" xmlns:r="{_R}" xmlns:v="{_V}" xmlns:o="{_O}" xmlns:w10="{_W10}">'
        f'<w:p><w:pPr><w:ind w:firstLine="0"/></w:pPr>'
        f'<w:r><w:rPr><w:noProof/></w:rPr><w:pict>{_WATERMARK_SHAPETYPE}{shape}</w:pict></w:r>'
        f'</w:p></w:hdr>'
    )


def _field(instruction: str, placeholder: str) -> str:
    """One Word field, with the cached result Word shows before it recalculates.

    A `PAGE` field written as begin/instrText/end with no `separate` and no
    cached run renders blank in every reader that does not recompute fields on
    open, which is most of them outside Word.
    """
    style = '<w:rPr><w:sz w:val="20"/></w:rPr>'
    return (
        f'<w:r>{style}<w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r>{style}<w:instrText xml:space="preserve"> {instruction} </w:instrText></w:r>'
        f'<w:r>{style}<w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r>{style}<w:t>{escape(placeholder)}</w:t></w:r>'
        f'<w:r>{style}<w:fldChar w:fldCharType="end"/></w:r>'
    )


def _footer_xml() -> str:
    """`стр. N из M`, centred, 10 pt.

    `NUMPAGES` and not a literal: a page count is how a signer knows they are
    holding the whole document, and a literal would be wrong the moment the
    evidence changes by one paragraph.
    """
    style = '<w:rPr><w:sz w:val="20"/></w:rPr>'
    text = f'<w:r>{style}<w:t xml:space="preserve">стр. </w:t></w:r>'
    joiner = f'<w:r>{style}<w:t xml:space="preserve"> из </w:t></w:r>'
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{_W}" xmlns:r="{_R}">'
        f'<w:p><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="center"/>{style}</w:pPr>'
        f'{text}{_field("PAGE", "1")}{joiner}{_field("NUMPAGES", "1")}'
        f'</w:p></w:ftr>'
    )


def _document_xml(parts: Sequence[str]) -> str:
    body = ''.join(parts)
    # The header and footer references live in the section properties, so the
    # marking and the page count repeat on every page rather than appearing
    # once at the top. A4, margins 2 / 1.5 / 2 / 3 cm in twips.
    section = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rIdHdr"/>'
        '<w:footerReference w:type="default" r:id="rIdFtr"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" '
        'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>'
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}" xmlns:r="{_R}">'
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


@dataclass(frozen=True)
class _Para:
    """One paragraph of the document.

    `style` is a styleId and it wins over `bold`/`size` in the DOCX: a heading
    that is only bold text gives Word no outline, so no navigation pane and no
    table of contents in a document running to tens of pages. `bold` stays for
    the PDF, which has no styles and sizes its lines from it.
    """

    text: str
    style: str | None = None
    bold: bool = False
    size: int | None = None


@dataclass(frozen=True)
class _Table:
    """The rows of one estimate table. Columns are `ESTIMATE_COLUMNS`."""

    rows: tuple[tuple[str, ...], ...]


def _value_or_absence(value: Any, what: str, unit: Any = None) -> str:
    """A dossier value with its unit, or `Нет данных: X`.

    Two rules at once. A blank cell is indistinguishable from a cell nobody
    filled in, so an absence says what is absent. And the value itself is
    passed through untouched -- rounding it or swapping the decimal separator
    here would put a figure in the document that the dossier does not hold,
    which is the one thing this artefact is built to make impossible.
    """
    if value is None or value == '':
        return f'Нет данных: {what}'
    return f'{value} {unit}'.strip() if unit else str(value)


def _locator_text(locator: Mapping[str, Any]) -> str:
    parts = [
        f'вер. {locator["document_version"]}' if locator.get('document_version') else '',
        f'с. {locator["page"]}' if locator.get('page') else '',
        f'разд. {locator["section_path"]}' if locator.get('section_path') else '',
        f'слой {locator["layer_id"]}' if locator.get('layer_id') else '',
        f'объект {locator["feature_id"]}' if locator.get('feature_id') else '',
    ]
    return ', '.join(part for part in parts if part)


def _estimate_source(dossier: Mapping[str, Any], estimate_id: str) -> str:
    """Source and locator of the claim that cites this estimate.

    §2 requires every substantive claim to carry both, and a table row is the
    number a reader will quote out of the report. A provenance column holding
    only the estimate's author would make the table the one place in the
    document where a figure travels without a locator.
    """
    names = {source['source_id']: source.get('title') or source['source_id'] for source in dossier.get('sources') or ()}
    citing = sorted(
        (claim for claim in dossier.get('claims') or () if claim.get('estimate_id') == estimate_id),
        key=lambda claim: claim['claim_id'],
    )
    if not citing:
        return f'Нет данных: источник оценки {estimate_id}'
    claim = citing[0]
    refs = claim.get('source_refs') or ()
    name = names.get(refs[0], refs[0]) if refs else 'Нет данных: источник'
    locator = _locator_text(claim.get('source_locator') or {})
    return f'{name}, {locator} ({claim["claim_id"]})' if locator else f'{name} ({claim["claim_id"]})'


def _estimate_table(
    dossier: Mapping[str, Any],
    estimate_ids: Sequence[str],
) -> tuple[_Table | None, list[str]]:
    """One row per cited resource or reserve estimate, plus its note lines.

    Anything that is not a resource or a reserve stays in flat paragraphs. An
    `exploration_target` in a table headed `Категория` next to a resource is
    the aggregation the template's paragraph 13 forbids, dressed as layout.
    """
    records = {estimate['estimate_id']: estimate for estimate in dossier.get('estimates') or ()}
    chosen = [
        records[estimate_id]
        for estimate_id in estimate_ids
        if estimate_id in records and records[estimate_id].get('estimate_kind') in RESOURCE_AND_RESERVE_KINDS
    ]
    if not chosen:
        return None, []

    rows = tuple(
        (
            _value_or_absence(estimate.get('category'), 'категория'),
            _value_or_absence(estimate.get('estimate_kind'), 'вид оценки'),
            _value_or_absence(estimate.get('quantity'), 'объём руды', estimate.get('quantity_unit')),
            _value_or_absence(estimate.get('grade'), 'содержание', estimate.get('grade_unit')),
            _value_or_absence(estimate.get('contained_metal'), 'металл', estimate.get('contained_metal_unit')),
            _value_or_absence(estimate.get('effective_date'), 'дата'),
            _estimate_source(dossier, estimate['estimate_id']),
        )
        for estimate in chosen
    )
    notes = [
        'Примечание к {estimate_id}: бортовое содержание — {cut_off}; метод — {method}; '
        'пространственный домен — {domain}.'.format(
            estimate_id=estimate['estimate_id'],
            cut_off=_value_or_absence(
                estimate.get('cut_off_grade'), 'бортовое содержание', estimate.get('cut_off_unit')
            ),
            method=_value_or_absence(estimate.get('method'), 'метод'),
            domain=_value_or_absence(estimate.get('spatial_domain'), 'пространственный домен'),
        )
        for estimate in chosen
    ]
    return _Table(rows), notes


def _subsection_labels(catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """`1.5. Юридические и разрешительные аспекты`, as literal text.

    Built from the whole catalog rather than from the rendered requirements, so
    a subsection reads the same whether one of its questions is answered or all
    five are. No `w:numPr` anywhere near it: Word auto-numbering would rewrite
    every following number when a subsection is deleted, and `coverage.json`
    keys on ids that would then point at rows the reader cannot find.
    """
    grouped: dict[str, list[str]] = {}
    for entry in catalog.values():
        grouped.setdefault(entry['subsection'], []).append(entry['title'])

    labels: dict[str, str] = {}
    for subsection, group in grouped.items():
        shared = dict.fromkeys(group)
        title = SUBSECTION_GROUP_TITLE.get(subsection) or (next(iter(shared)) if len(shared) == 1 else '')
        labels[subsection] = f'{subsection}. {title}' if title else f'{subsection}.'
    return labels


def _sentence_items(
    sentence: Any,
    row: Mapping[str, Any],
    dossier: Mapping[str, Any],
    title: str,
) -> list[_Para | _Table]:
    """One requirement, under its own `Heading3`.

    An unmet requirement keeps its structured `if_not_why_not` and the expert
    action it needs, as labelled paragraphs under the heading they belong to,
    so a reader who jumps to a section by the outline lands on the reason as
    well as on the gap.
    """
    items: list[_Para | _Table] = [
        _Para(f'{sentence.requirement_id} — {title}', style='Heading3', bold=True),
        _Para(f'Состояние: {STATE_LABEL[row["state"]]}.'),
    ]
    if sentence.claim_ids:
        # Ids, not values. The document points at the dossier; it does not
        # restate it, so the two can never disagree.
        items.append(_Para('Основание: ' + ', '.join(sentence.claim_ids)))
    if sentence.estimate_ids:
        items.append(_Para('Оценки: ' + ', '.join(sentence.estimate_ids)))
        table, notes = _estimate_table(dossier, sentence.estimate_ids)
        if table is not None:
            items.append(table)
            items.extend(_Para(note) for note in notes)
    if sentence.figure_ids:
        items.append(_Para('Рисунки: ' + ', '.join(sentence.figure_ids)))
    if sentence.conflict_ids:
        items.append(
            _Para('Расхождение источников сохранено, обе стороны приведены: ' + ', '.join(sentence.conflict_ids))
        )
    reason = row.get('if_not_why_not')
    if reason:
        items.append(_Para(f'Если нет, то почему нет: {reason["reason"]}'))
    if row.get('expert_action_ids'):
        items.append(_Para('Требуется действие эксперта: ' + ', '.join(row['expert_action_ids'])))
    return items


def _front_matter(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
) -> list[_Para | _Table]:
    scope = dossier['project_scope']
    completeness = semantic_completeness(projection, dossier)
    return [
        _Para('Отчёт о готовности к CPR', bold=True, size=18),
        _Para(DRAFT_WATERMARK, bold=True, size=14),
        _Para(f'Объект: {scope.get("object_name") or scope["project_id"]}'),
        _Para(f'Стадия: {scope["lifecycle_stage"]}'),
        _Para(f'Запуск досье: {projection["dossier_run_id"]}'),
        _Para(f'Заморожено: {dossier["frozen_at"]}'),
        # The ACL disclosure. The DOCX has always carried it; leaving it out of
        # the PDF let the same run produce one document that discloses withheld
        # sources and one that does not.
        _Para(
            f'Доступ к источникам: {scope["acl_decision"]}'
            + (f', исключено источников: {scope["acl_excluded_sources"]}' if scope.get('acl_excluded_sources') else '')
        ),
        _Para(
            f'Отвечено {completeness["answered"]} из {completeness["denominator"]} '
            f'применимых требований. Это срез каталога, а не измерение полноты.'
        ),
        _Para('Документ не является подтверждением соответствия JORC или НАЭН и не подписан Компетентным лицом.'),
    ]


def _content(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
) -> list[_Para | _Table]:
    """The document, built once. The DOCX and the PDF both walk this list.

    It used to be built twice from the same inputs, and the two copies drifted:
    the PDF lost the estimate ids, the figure ids and the ACL disclosure while
    still being described as the same document. One list means a line the PDF
    does not print is a line the DOCX does not have either.
    """
    rows = {row['requirement_id']: row for row in projection['coverage']}
    catalog = requirements_by_id()
    subsections = _subsection_labels(catalog)

    items = _front_matter(projection, dossier)
    planned = {block.section: block for block in blocks}

    for section, heading in sorted(SECTION_TITLE.items()):
        items.append(_Para(heading, style='Heading1', bold=True))
        block = planned.get(section)
        if block is None:
            # A section the projection never reached. Printing the heading and
            # saying so beats omitting it: a reader who cannot see that section
            # 6 was out of scope reads its absence as "nothing to report".
            items.append(
                _Para(
                    f'Нет данных: требования раздела не входят в срез проекции '
                    f'{projection["projection_version"]}. Раздел не проецировался; это не '
                    f'утверждение о том, что фактов по разделу нет.'
                )
            )
            continue

        subsection = None
        for sentence in block.sentences:
            entry = catalog.get(sentence.requirement_id)
            if entry is None:
                # The alternative is a `Heading2` that reads `None` and a
                # requirement filed under it -- a document that looks finished
                # and is filed against a subsection that does not exist.
                raise CprContractError(
                    f'{sentence.requirement_id} is planned for rendering and is not in the catalog, '
                    f'so it has no subsection to file it under'
                )
            if entry['subsection'] != subsection:
                subsection = entry['subsection']
                items.append(_Para(subsections[subsection], style='Heading2', bold=True))
            items.extend(
                _sentence_items(
                    sentence,
                    rows[sentence.requirement_id],
                    dossier,
                    titles.get(sentence.requirement_id, ''),
                )
            )
        if block.skipped:
            items.append(_Para('Неприменимо на текущей стадии: ' + ', '.join(block.skipped)))
    return items


def _body_parts(items: Sequence[_Para | _Table]) -> list[str]:
    parts: list[str] = []
    for item in items:
        if isinstance(item, _Table):
            parts.append(_table_xml(item.rows))
        elif item.style:
            parts.append(_paragraph(item.text, style=item.style))
        else:
            parts.append(_paragraph(item.text, bold=item.bold, size=item.size))
    return parts


def render_docx(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
) -> bytes:
    """`cpr_readiness.docx`, watermarked, deterministic."""
    return _zip(
        {
            '[Content_Types].xml': _CONTENT_TYPES,
            '_rels/.rels': _ROOT_RELS,
            'word/_rels/document.xml.rels': _DOCUMENT_RELS,
            'word/styles.xml': _styles_xml(),
            'word/header1.xml': _header_xml(),
            'word/footer1.xml': _footer_xml(),
            'word/document.xml': _document_xml(_body_parts(_content(projection, dossier, blocks, titles))),
        }
    )


_WATERMARK_STRING = re.compile(r'<v:textpath\b[^>]*\bstring="([^"]*)"')


def docx_watermark_is_present(payload: bytes) -> bool:
    """Read the marking back out of the rendered bytes.

    §10 makes the watermark a checkable control, so it is checked rather than
    assumed -- and checked in the header part, which is what survives someone
    deleting the first line of the body.

    The marking moved out of a header paragraph and into the `string`
    attribute of the VML shape's `v:textpath`, so this reads the attribute
    rather than the part. A substring search over the raw XML would still pass
    on a header where the phrase survives only in a comment or a stale run --
    that is, on a document with no watermark on the page.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if 'word/header1.xml' not in archive.namelist():
            return False
        header = archive.read('word/header1.xml').decode('utf-8')
    return any(unescape(found) == DRAFT_WATERMARK for found in _WATERMARK_STRING.findall(header))


def _plain_lines(
    projection: Mapping[str, Any],
    dossier: Mapping[str, Any],
    blocks: Sequence[NarrativeBlock],
    titles: Mapping[str, str],
) -> list[tuple[str, bool]]:
    """The document as (text, bold) lines, for the PDF.

    A table has no equivalent in `fpdf2`'s `multi_cell` here, so each row
    becomes one pipe-separated line. That keeps the two renderers comparable
    line for line -- the property the DOCX/PDF equality test rests on -- rather
    than letting the PDF quietly drop the numbers the table exists to show.
    """
    lines: list[tuple[str, bool]] = []
    for item in _content(projection, dossier, blocks, titles):
        if isinstance(item, _Table):
            lines.append((' | '.join(ESTIMATE_COLUMNS), True))
            lines.extend((' | '.join(row), False) for row in item.rows)
        else:
            lines.append((item.text, item.bold))
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
