"""CPR-SLICE-01 step 3: the artefacts.

`cpr_readiness.docx`, the PDF, `coverage.json`, the source report, the audit
report and the run manifest, all from one projection.

Two things are asserted harder than the rest, because they are what the
assignment turns into checkable controls: the document carries
`DRAFT — NOT A JORC/NAEN CERTIFICATION` where deleting it is not one keystroke,
and re-rendering the same projection produces the same bytes.
"""

from __future__ import annotations

import hashlib
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


def test_the_marking_is_a_watermark_and_not_a_heading(docx):
    """Grey, diagonal and behind the text.

    Bold black text at the top of the page reads as a title. A reader who
    forwards one page of that has forwarded something that looks like a
    heading, not something that looks unsigned -- which is the whole of what
    §10 asks the marking to communicate.
    """
    header = docx_part(docx, 'word/header1.xml')

    assert '<v:shapetype id="_x0000_t136"' in header, 'the WordArt shapetype must be defined in the part'
    assert f'string="{render.DRAFT_WATERMARK}"' in header
    assert 'fillcolor="#c0c0c0"' in header
    assert 'rotation:315' in header
    assert 'z-index:-251658752' in header


def test_the_watermark_check_reads_the_shape_and_not_the_part(docx):
    """The reader moved with the text. A substring search over the header
    would still pass on a part where the phrase survives only in a leftover
    run -- that is, on a document with nothing on the page."""
    with zipfile.ZipFile(io.BytesIO(docx)) as source:
        parts = {name: source.read(name) for name in source.namelist()}

    parts['word/header1.xml'] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{render._W}"><!-- {render.DRAFT_WATERMARK} --></w:hdr>'
    ).encode()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as target:
        for name, payload in parts.items():
            target.writestr(name, payload)

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
            'word/styles.xml',
            'word/header1.xml',
            'word/footer1.xml',
            'word/document.xml',
        }


def test_every_part_is_well_formed_xml(docx):
    """The failure the styles, footer and VML work can produce is not a crash.

    Word does not report a malformed part -- it offers to repair the file and
    then opens it with the broken part discarded, so a stray `&` in a locator
    or an unescaped quote in the watermark attribute would show up as a
    document that has simply lost its headings.
    """
    from xml.dom.minidom import parseString

    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        for name in archive.namelist():
            parseString(archive.read(name).decode('utf-8'))


def test_every_added_part_is_declared_and_reachable(docx):
    """A part in the ZIP that no override types and no relationship points at
    is a part Word repairs the file to remove -- silently, on open, with the
    styles and the footer gone and no error anywhere."""
    types = docx_part(docx, '[Content_Types].xml')
    rels = docx_part(docx, 'word/_rels/document.xml.rels')

    for part, kind in (('styles', 'styles'), ('header1', 'header'), ('footer1', 'footer')):
        assert f'/word/{part}.xml' in types, part
        assert f'wordprocessingml.{kind}+xml' in types, part
    for target, kind in (('styles.xml', 'styles'), ('header1.xml', 'header'), ('footer1.xml', 'footer')):
        assert f'Target="{target}"' in rels, target
        assert f'relationships/{kind}"' in rels, target


def test_rendering_twice_gives_the_same_bytes(projection, dossier, blocks, titles, docx):
    """§9 requires a re-render to reach the same artefact hashes. A ZIP that
    stamped the current time would fail that on the second run.

    Rendered twice and compared, not asserted against the pinned `ZipInfo`
    date: the date is one of several ways this can drift, and a dict iterated
    in a different order or a `set` of style ids would sail past a test that
    only checked the timestamp.
    """
    assert render.render_docx(projection, dossier, blocks, titles) == docx


_RENDER_IN_A_FRESH_PROCESS = """
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, {backend!r})
from open_webui.services.artifacts.cpr import coverage, narrative, project, render

dossier = json.loads(Path({dossier!r}).read_text(encoding='utf-8'))
projection = project.build_projection(dossier)
blocks = narrative.plan_narrative(projection, dossier)
payload = render.render_docx(projection, dossier, blocks, coverage.requirement_titles())
print(hashlib.sha256(payload).hexdigest())
"""


def test_the_bytes_are_the_same_in_a_fresh_process(docx):
    """Determinism across runs, which is the determinism §9 actually needs.

    Rendering twice inside one interpreter cannot see the failure that matters.
    `PYTHONHASHSEED` is randomised per process, so a renderer that iterated a
    `set` of part names, style ids or requirement ids would be perfectly stable
    within a run and produce a different file on the next one -- and the
    manifest's re-render check compares hashes taken from two separate runs.
    Verified by mutation: iterating `_zip`'s parts as a set leaves the
    same-process comparison green and fails this.
    """
    import os
    import subprocess
    import sys

    backend = str(Path(__file__).resolve().parents[1])
    script = _RENDER_IN_A_FRESH_PROCESS.format(backend=backend, dossier=str(DATA / 'lekyn-dossier.example.json'))

    digests = set()
    for seed in ('0', '1', '524287'):
        environment = {**os.environ, 'PYTHONHASHSEED': seed}
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True,
            check=True,
            cwd=backend,
            env=environment,
            text=True,
        )
        digests.add(result.stdout.strip())

    assert len(digests) == 1, digests
    assert digests == {hashlib.sha256(docx).hexdigest()}


# -- headings, styles and the outline -------------------------------------


def _styles(docx: bytes) -> dict[str, str]:
    xml = docx_part(docx, 'word/styles.xml')
    return {
        match.group(1): match.group(0)
        for match in re.finditer(r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>.*?</w:style>', xml, re.S)
    }


def test_three_heading_levels_resolve(docx):
    """Deliverable (a): the styleIds exist and the document actually uses them.

    Either half alone is a document with no outline. Styles nobody references
    give Word nothing to build a navigation pane from; `w:pStyle` pointing at
    an id `styles.xml` does not define is silently ignored, and every heading
    renders as body text.
    """
    defined = _styles(docx)
    body = docx_part(docx, 'word/document.xml')

    for style_id in ('Normal', 'Heading1', 'Heading2', 'Heading3'):
        assert style_id in defined, style_id
    for style_id in ('Heading1', 'Heading2', 'Heading3'):
        assert f'<w:pStyle w:val="{style_id}"/>' in body, style_id

    # None of the template's 34 obfuscated ids. A single-character styleId here
    # would mean the customer's styles had been reused and the headings are
    # decoration again.
    assert not [style_id for style_id in defined if len(style_id) < 3]


def test_the_outline_levels_are_what_word_reads(docx):
    """`w:outlineLvl` is what puts a heading in the navigation pane and in a
    generated table of contents. The built-in `w:name` alone is not enough in
    every reader, and a wrong level nests section 3 under section 2."""
    defined = _styles(docx)

    for style_id, level in (('Heading1', 0), ('Heading2', 1), ('Heading3', 2)):
        assert f'<w:outlineLvl w:val="{level}"/>' in defined[style_id], style_id
        assert '<w:keepNext/>' in defined[style_id], style_id
        assert '<w:name w:val="heading ' in defined[style_id], style_id


def test_the_style_measurements_are_in_ooxml_units(docx):
    """Half-points, twentieths of a point, twips -- all three, all silent when
    wrong. 14 pt written as `w:sz="14"` renders a heading smaller than the body
    text, and 18 pt of spacing written as `w:spacing="18"` is a hair."""
    defined = _styles(docx)

    # body: Times New Roman 12 pt, justified, first line 1.25 cm = 709 twips
    assert '<w:sz w:val="24"/>' in defined['Normal']
    assert '<w:ind w:firstLine="709"/>' in defined['Normal']
    assert '<w:jc w:val="both"/>' in defined['Normal']
    assert '<w:line="240"' in defined['Normal'].replace('w:line="240"', '<w:line="240"')
    assert 'Times New Roman' in defined['Normal']

    # Heading 1: 14 pt bold, before 18 pt = 360, after 12 pt = 240
    assert '<w:sz w:val="28"/>' in defined['Heading1']
    assert '<w:b/>' in defined['Heading1']
    assert 'w:before="360" w:after="240"' in defined['Heading1']

    # Heading 2: 12 pt bold, before 12 pt = 240, after 6 pt = 120
    assert '<w:sz w:val="24"/>' in defined['Heading2']
    assert '<w:b/>' in defined['Heading2']
    assert '<w:i/>' not in defined['Heading2']
    assert 'w:before="240" w:after="120"' in defined['Heading2']

    # Heading 3: 12 pt bold italic, before 6 pt = 120
    assert '<w:sz w:val="24"/>' in defined['Heading3']
    assert '<w:b/><w:i/>' in defined['Heading3']
    assert 'w:before="120" w:after="0"' in defined['Heading3']

    # Every heading cancels the body's first-line indent, or the outline reads
    # as if it were one level deeper than it is.
    for style_id in ('Heading1', 'Heading2', 'Heading3'):
        assert '<w:ind w:firstLine="0"/>' in defined[style_id], style_id


def test_the_page_is_a4_with_the_template_margins(docx):
    """2 cm top, 1.5 cm right, 2 cm bottom, 3 cm left, in twips. Asserted so
    the next change to `sectPr` cannot move them by accident."""
    body = docx_part(docx, 'word/document.xml')

    assert '<w:pgSz w:w="11906" w:h="16838"/>' in body
    assert 'w:top="1134" w:right="850" w:bottom="1134" w:left="1701"' in body


def test_section_numbers_are_literal_text_and_nothing_is_auto_numbered(docx):
    """Deliverable (d).

    Word auto-numbering renumbers every following subsection when one is
    deleted. `coverage.json` keys on requirement ids and the reader keys on the
    printed number, so the two would part company on the first edit and neither
    would look wrong.
    """
    body = docx_part(docx, 'word/document.xml')

    assert 'w:numPr' not in body
    assert 'numbering.xml' not in docx_part(docx, '[Content_Types].xml')

    headings = re.findall(r'<w:p><w:pPr><w:pStyle w:val="Heading\d"/></w:pPr>.*?</w:p>', body, re.S)
    assert headings
    for heading in headings:
        assert 'w:numPr' not in heading

    for title in (
        'Раздел 0. Введение',
        'Раздел 1. Информация о проекте (Общие сведения)',
        'Раздел 2. Геологическая обстановка, месторождение, минерализация',
        'Раздел 3. Разведка и бурение, методы отбора проб, анализы и технологические испытания',
        'Раздел 4. Оценка и отчётность о результатах разведки, минеральных ресурсах',
        'Раздел 5. Технические исследования (горные работы и проектирование)',
        'Раздел 6. Оценка и отчётность о запасах полезных ископаемых',
        'Раздел 7. Аудиты и обзоры',
        'Раздел 8. Другая релевантная информация',
    ):
        assert f'<w:t xml:space="preserve">{title}</w:t>' in body, title


def test_a_requirement_the_catalog_does_not_hold_refuses_to_render(projection, dossier, blocks, titles):
    """The subsection heading comes from the catalog. A requirement the catalog
    has never heard of would otherwise be filed under a `Heading2` reading
    `None` -- a document that looks finished, in a subsection that does not
    exist."""
    from open_webui.services.artifacts.cpr import narrative as narrative_module

    first = blocks[0]
    stranger = narrative_module.NarrativeBlock(
        section=first.section,
        sentences=(first.sentences[0].__class__(**{**vars(first.sentences[0]), 'requirement_id': 'CPR-NOPE'}),),
        skipped=(),
    )
    rows = list(projection['coverage']) + [{**projection['coverage'][0], 'requirement_id': 'CPR-NOPE'}]

    with pytest.raises(CprContractError, match='not in the catalog'):
        render.render_docx({**projection, 'coverage': rows}, dossier, (stranger,), titles)


def test_every_section_of_the_template_is_present_even_when_it_is_empty(docx):
    """A missing section reads as "nothing to report". Sections 6 and 8 are not
    in the projection slice at all, so they carry the heading and say so --
    absence of a projection is not absence of facts, and the document has to be
    able to tell a signer which one it means."""
    lines = _docx_lines(docx)

    assert 'Раздел 6. Оценка и отчётность о запасах полезных ископаемых' in lines
    assert 'Раздел 8. Другая релевантная информация' in lines
    assert [line for line in lines if line.startswith('Нет данных: требования раздела не входят')]


# -- the estimate tables ---------------------------------------------------


def _tables(docx: bytes) -> list[str]:
    return re.findall(r'<w:tbl>.*?</w:tbl>', docx_part(docx, 'word/document.xml'), re.S)


def test_estimate_tables_repeat_their_header_row(docx):
    """Deliverable (c). `w:tblHeader` is what repeats the header after a page
    break; without it a table that runs over a page becomes a block of
    unlabelled numbers, which for a resource table is worse than no table."""
    tables = _tables(docx)

    assert tables, 'the reference dossier cites two forecast-resource estimates'
    for table in tables:
        rows = re.findall(r'<w:tr>.*?</w:tr>', table, re.S)
        assert '<w:tblHeader/>' in rows[0]
        assert all('<w:tblHeader/>' not in row for row in rows[1:])


def test_the_estimate_table_has_the_seven_columns_that_fit_the_page(docx):
    """Seven at 10 pt is what fits the 16.5 cm between the margins. Cut-off
    grade, method and spatial domain go in a note beneath the table rather than
    in three more columns that would squeeze out the numbers."""
    table = _tables(docx)[0]
    header = re.findall(r'<w:tr>.*?</w:tr>', table, re.S)[0]
    cells = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', header)

    assert cells == ['Категория', 'Вид оценки', 'Объём руды', 'Содержание', 'Металл', 'Дата', 'Источник']
    assert sum(render.ESTIMATE_COLUMN_WIDTHS) == 11906 - 1701 - 850
    assert '<w:tblLayout w:type="fixed"/>' in table
    for run in re.findall(r'<w:rPr>.*?</w:rPr>', header, re.S):
        assert '<w:b/>' in run and '<w:sz w:val="20"/>' in run


def test_the_estimate_table_is_hairline_ruled_and_unshaded(docx):
    """0.5 pt is `w:sz="4"` -- eighths of a point, a fourth unit. Shading in a
    printed CPR reads as emphasis on one category over another."""
    table = _tables(docx)[0]

    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        assert f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="000000"/>' in table, edge
    assert 'w:shd' not in table


def test_each_estimate_is_one_row_carrying_its_own_source_and_locator(docx, dossier):
    """The template's paragraph 12 asks for separate figures per category and
    paragraph 13 forbids adding resources to reserves. Both are checks a reader
    can only run with the estimates side by side -- and each row has to say
    where its numbers came from, or the table is the one place in the document
    where a figure travels without a locator."""
    rows = [line for line in _docx_lines(docx) if line.count(' | ') == 6]
    body_rows = [row for row in rows if not row.startswith('Категория | ')]

    assert body_rows
    for estimate in dossier['estimates']:
        matching = [row for row in body_rows if row.startswith(f'{estimate["category"]} | ')]
        assert matching, estimate['estimate_id']
    # `clm-au-project` is the claim that cites `est-project-au`; the locator is
    # the page and section it was read from.
    assert any('Проект ГРР, вер. 2024-11-v2, с. 42, разд. 4.5 (clm-au-project)' in row for row in body_rows)


def test_the_table_is_the_one_place_values_are_printed_and_they_are_not_edited(docx, dossier):
    """The narrow exception to "cite ids, never restate a value".

    `test_the_document_cites_ids_and_never_restates_a_value` is the rule; a
    resource table cannot obey it, because a table of ids compares nothing. So
    the cells are read out of the dossier at render time and printed exactly as
    the dossier holds them -- no rounding, no swapped decimal separator, no
    recomputed tonnage. A renderer that reformatted `1.8` to `1,8` would put a
    figure in the signed document that the evidence does not contain, and the
    two could then disagree with nobody able to say which was the fact.
    """
    body_rows = [line for line in _docx_lines(docx) if line.count(' | ') == 6]
    printed = ' '.join(body_rows)

    for estimate in dossier['estimates']:
        assert f'{estimate["quantity"]} {estimate["quantity_unit"]}' in printed, estimate['estimate_id']
        assert f'{estimate["grade"]} {estimate["grade_unit"]}' in printed, estimate['estimate_id']
        assert estimate['effective_date'] in printed, estimate['estimate_id']

    # Only inside a table. Everywhere else the document still points at the
    # dossier rather than repeating it.
    outside = [line for line in _docx_lines(docx) if line.count(' | ') != 6]
    assert not [line for line in outside if '20.0 т' in line or '12.0 т' in line]


def test_a_missing_estimate_value_says_what_is_missing(docx):
    """`contained_metal` is null on both reference estimates. A blank cell is
    indistinguishable from a cell nobody filled in."""
    body_rows = [line for line in _docx_lines(docx) if line.count(' | ') == 6]

    assert any('Нет данных: металл' in row for row in body_rows)


def test_the_note_under_the_table_carries_cut_off_method_and_domain(docx):
    lines = _docx_lines(docx)
    notes = [line for line in lines if line.startswith('Примечание к ')]

    # Two requirements cite the same two estimates -- CPR-ADD-11 compares them
    # and CPR-GEN-04 forbids merging them -- so the pair is tabled twice, under
    # the requirement each answers, with its notes each time.
    assert len(notes) == 2 * len(_tables(docx))
    assert len(_tables(docx)) == 2
    for note in notes:
        assert 'бортовое содержание —' in note
        assert 'метод —' in note
        assert 'пространственный домен —' in note
    assert any('метод — аналогия по параметрам' in note for note in notes)


def test_only_resource_and_reserve_estimates_become_a_table(dossier, titles):
    """An exploration target in a table headed `Категория` next to a resource
    is the aggregation the template's paragraph 13 forbids, dressed as layout.

    Reaching the renderer's filter takes a deliberate seed, and saying why is
    the point of the length. The reference dossier is at lifecycle stage
    `exploration_results` and carries only `forecast_resource` estimates, so an
    assertion about the frozenset's literal contents passes with the filter
    deleted -- which is what the first version of this test did. The only slice
    map entry naming `exploration_target` is CPR-4.2.1, applicable at
    `mineral_resources`, so the seed moves the stage, plants the estimate and
    cites it on CPR-4.2.1's own predicate. That gets it as far as
    `supporting_estimate_ids`; what keeps it out of a table row is the filter,
    and nothing else.
    """
    assert render.RESOURCE_AND_RESERVE_KINDS == {'forecast_resource', 'mineral_resource', 'ore_reserve'}

    target_id = 'est-exploration-target'
    seeded = json.loads(json.dumps(dossier))
    seeded['project_scope']['lifecycle_stage'] = 'mineral_resources'
    estimate = dict(seeded['estimates'][0])
    estimate.update({'estimate_id': target_id, 'estimate_kind': 'exploration_target'})
    seeded['estimates'].append(estimate)
    cited = dict(next(claim for claim in seeded['claims'] if claim.get('estimate_id')))
    cited.update({
        'claim_id': 'clm-exploration-target',
        'predicate': 'exploration_target_range',
        'estimate_id': target_id,
    })
    seeded['claims'].append(cited)

    seeded_projection = project.build_projection(seeded)
    row = next(
        entry for entry in seeded_projection['coverage']
        if entry['requirement_id'] == 'CPR-4.2.1'
    )
    assert row['supporting_estimate_ids'] == [target_id], (
        'the seed never reached the renderer, so the rest of this proves nothing'
    )
    assert row['render_state'] == 'rendered'

    payload = render.render_docx(
        seeded_projection, seeded,
        narrative.plan_narrative(seeded_projection, seeded), titles,
    )
    document = docx_part(payload, 'word/document.xml')

    # The estimate id is not written into a row -- the columns are category,
    # tonnage, grade and source -- so the row-bearing probe is the note, which
    # `_estimate_table` emits once per estimate it accepted.
    assert len(_tables(payload)) == 2, 'the exploration target was given a table of its own'
    assert f'Примечание к {target_id}' not in document
    # Still named in the evidence line, which is the point: excluded from the
    # comparable table, not dropped from the document.
    assert target_id in document


# -- the footer ------------------------------------------------------------


def test_the_footer_numbers_every_page_out_of_the_total(docx):
    """`стр. N из M`. The total is what tells a signer they are holding the
    whole document, and it has to be a `NUMPAGES` field: a literal would be
    wrong the moment the evidence changes by one paragraph."""
    footer = docx_part(docx, 'word/footer1.xml')

    assert 'стр. ' in footer and ' из ' in footer
    assert '<w:instrText xml:space="preserve"> PAGE </w:instrText>' in footer
    assert '<w:instrText xml:space="preserve"> NUMPAGES </w:instrText>' in footer
    assert footer.count('<w:fldChar w:fldCharType="begin"/>') == 2
    assert footer.count('<w:fldChar w:fldCharType="separate"/>') == 2
    assert footer.count('<w:fldChar w:fldCharType="end"/>') == 2
    assert '<w:jc w:val="center"/>' in footer
    assert '<w:sz w:val="20"/>' in footer
    assert '<w:footerReference w:type="default" r:id="rIdFtr"/>' in docx_part(docx, 'word/document.xml')


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


def _docx_lines(docx: bytes) -> list[str]:
    """The body as one line per paragraph and one line per table row.

    Table rows are joined with ' | ', which is what `_plain_lines` gives the
    PDF. Reading every `<w:t>` in the file as its own line, as this used to,
    would make a seven-cell row seven lines and the DOCX/PDF comparison below
    would fail on formatting rather than on content.
    """
    xml = zipfile.ZipFile(io.BytesIO(docx)).read('word/document.xml').decode('utf-8')
    lines: list[str] = []
    # `<w:tbl>` first in the alternation: at a table's opening tag the whole
    # table matches, so its inner paragraphs are consumed here instead of being
    # counted a second time as loose paragraphs.
    for block in re.finditer(r'<w:tbl>.*?</w:tbl>|<w:p>.*?</w:p>', xml, re.S):
        chunk = block.group(0)
        if chunk.startswith('<w:tbl>'):
            for row in re.findall(r'<w:tr>.*?</w:tr>', chunk, re.S):
                lines.append(' | '.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', row)))
        else:
            lines.append(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', chunk)))
    return [line for line in lines if line.strip()]


def test_the_pdf_and_the_docx_say_the_same_thing(projection, dossier, blocks, titles, docx):
    """"One content model, two renderers" -- as a sequence, not a vocabulary.

    `_plain_lines`, the model behind the PDF, used to omit three line kinds the
    DOCX emits: supporting estimate ids, supporting figure ids, and the ACL
    disclosure naming how many sources were withheld.

    The first version of this test compared `set(docx) == set(pdf)`, which is a
    weaker claim than its name. The document is 172 lines and only 116 of them
    are distinct -- state labels and reason lines repeat across requirements --
    so a renderer that emitted each distinct line once would drop 56 lines and
    still pass. Verified by mutation: deduplicating `_plain_lines` left this
    file green. Compared in order now, so a dropped or reordered line fails.
    """
    from open_webui.services.artifacts.cpr import render

    in_docx = _docx_lines(docx)
    in_pdf = [text for text, _ in render._plain_lines(projection, dossier, blocks, titles) if text.strip()]

    assert in_pdf == in_docx
    # Guard the guard: if the document ever became duplicate-free, the sequence
    # comparison would silently weaken back into a set comparison.
    assert len(in_docx) > len(set(in_docx)), 'this document repeats lines; that is what makes order load-bearing'


def test_both_documents_disclose_withheld_sources(projection, dossier, blocks, titles, docx):
    """The ACL line is a disclosure, not decoration: it says how much of the
    evidence the reader is not being shown. Checked in the rendered DOCX and in
    the PDF's model -- an earlier version inspected `_plain_lines` twice and
    called that "both documents".
    """
    from open_webui.services.artifacts.cpr import render

    scope = dossier['project_scope']
    in_pdf = [text for text, _ in render._plain_lines(projection, dossier, blocks, titles)]

    for lines, where in ((in_pdf, 'pdf'), (_docx_lines(docx), 'docx')):
        disclosure = [line for line in lines if line.startswith('Доступ к источникам:')]
        assert len(disclosure) == 1, where
        assert scope['acl_decision'] in disclosure[0], where
        if scope.get('acl_excluded_sources'):
            assert str(scope['acl_excluded_sources']) in disclosure[0], where
