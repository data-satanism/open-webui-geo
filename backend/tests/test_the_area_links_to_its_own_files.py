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
    AREA_ARTEFACT_LABELS,
    AREA_ARTEFACT_LIMITS,
    ARTEFACT_PROXY_PREFIX,
    RESOLVED,
    area_artifact_lines,
    area_progress_line,
    area_progress_reporter,
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
        'files': _files(
            'state.json', 'run_log.json', 'summary.md',
            'geotizer.xlsx', 'geotizer.docx',
        ),
        'not_rendered': {
            'source_report.md / source_report.pdf': 'the fold carries no locator'
        },
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

    for name in (
        'summary.md', 'geotizer.xlsx', 'geotizer.docx', 'state.json', 'run_log.json'
    ):
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
    """A reader who knows the member fill has a source report will look for
    the area's."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    assert 'source_report' in text
    assert 'not_rendered' in text


def test_the_source_report_limit_is_stated_with_where_to_look_instead():
    """«Worth recording as the thing that would make an area source report
    possible, and worth saying in the answer that the member reports exist.»

    The evidence behind a folded value is not missing — it is one hop away,
    in the member's own run, and an answer that says only «no source report»
    sends a reader looking for something that is there."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    for line in AREA_ARTEFACT_LIMITS:
        assert line in text
    assert 'run_id' in text


def test_a_service_too_old_to_report_the_gap_does_not_silence_it():
    """The gap is real for every version that has ever run, so a service
    that says nothing about it has not closed it.

    The key ABSENT, not the key empty. Those are the two versions being
    told apart: an old service sends no record, and a current one sends an
    empty record to say nothing is missing."""
    record = _artifacts()
    record.pop('not_rendered')

    text = '\n'.join(area_artifact_lines(record))

    assert AREA_ARTEFACT_LIMITS[0] in text


def test_an_empty_record_is_the_service_saying_nothing_is_missing():
    """`{}` is a statement, which is why the service keeps the key rather
    than dropping it once the list emptied. Read as emptiness instead of as
    presence, this printed «the source report is not collected» beside a
    link to the source report."""
    text = '\n'.join(area_artifact_lines(_artifacts(not_rendered={})))

    assert AREA_ARTEFACT_LIMITS[0] not in text
    # And nothing is announced as missing either.
    assert 'Чего у площади нет' not in text


def test_a_service_that_closes_the_gap_stops_the_sentence():
    """A sentence that outlives its cause tells every reader the report «is
    not collected» about a report that is. This repository cannot see
    whether the service still has the gap, so it reads the service's own
    record rather than asserting it."""
    text = '\n'.join(
        area_artifact_lines(
            _artifacts(not_rendered={'geotizer.pptx': 'no slide template'})
        )
    )

    assert AREA_ARTEFACT_LIMITS[0] not in text
    # And what the service DID decline is still printed.
    assert 'geotizer.pptx' in text


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


# -- The area's own status line ----------------------------------------------
#
# The emitter was designed for one fill, where «Обращаюсь к специалисту по
# ГИС» is a step. With three members in flight it is three specialists
# emitting their own, interleaved, none carrying a member identity — and a
# reader cannot tell which licence any line belongs to. An area's progress is
# how many members are done.

def test_the_line_is_the_members_not_the_rounds():
    line = area_progress_line(
        {'members': 7, 'running': 3, 'filled': 2, 'failed': 0, 'not_attempted': 0}
    )

    assert line == 'Площадь: 7 участников · заполняется 3 · готово 2 · ожидают 2'


def test_waiting_is_derived_and_the_terms_sum_to_the_members():
    """«Waiting» is exactly «in no other state». A sixth counter could
    disagree with the five that already sum."""
    for running, filled, failed, missed in ((0, 0, 0, 0), (1, 2, 1, 1), (0, 7, 0, 0)):
        counts = {
            'members': 7, 'running': running, 'filled': filled,
            'failed': failed, 'not_attempted': missed,
        }
        line = area_progress_line(counts)
        numbers = [int(part.split()[-1]) for part in line.split(' · ')[1:]]

        assert sum(numbers) == 7, line


def test_a_failure_is_never_folded_into_the_done_count():
    """A member that failed and a member that finished must not share a
    number: the line's whole job is to say how many are done."""
    line = area_progress_line(
        {'members': 7, 'running': 1, 'filled': 4, 'failed': 2, 'not_attempted': 0}
    )

    assert 'готово 4' in line
    assert 'не удалось 2' in line


def test_the_tail_terms_are_absent_when_they_are_zero():
    """«не удалось 0» on a healthy area is noise."""
    line = area_progress_line(
        {'members': 7, 'running': 0, 'filled': 7, 'failed': 0, 'not_attempted': 0}
    )

    assert 'не удалось' not in line
    assert 'не начинались' not in line


def test_the_plural_is_the_russian_one():
    for total, word in ((1, 'участник'), (3, 'участника'), (7, 'участников'),
                        (11, 'участников'), (21, 'участник')):
        line = area_progress_line({'members': total})

        assert line.startswith(f'Площадь: {total} {word} ·'), line


def test_nobody_watching_means_no_reporter_rather_than_a_silent_one():
    """The loop already skips the call when there is none; a no-op awaited on
    every transition is work done to produce silence."""
    assert area_progress_reporter(None) is None


def test_the_reporter_emits_a_status_event_that_is_never_done():
    """`done=True` before the answer exists tells the UI the work finished
    while seven members are still filling."""
    import asyncio

    seen = []

    async def emitter(event):
        seen.append(event)

    report = area_progress_reporter(emitter)
    asyncio.run(report({'members': 7, 'running': 3, 'filled': 2}))

    assert seen == [
        {
            'type': 'status',
            'data': {
                'description': (
                    'Площадь: 7 участников · заполняется 3 · готово 2 · ожидают 2'
                ),
                'done': False,
            },
        }
    ]


def test_the_line_follows_the_same_language_switch_as_the_rest():
    """One run answering to one switch. The table's own header says a second
    scheme means «one run answering to two switches and drifting apart at
    the seam», and a Russian-only area line on a contour set to `en` would
    have been the first line in this tree to do it."""
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    counts = {'members': 7, 'running': 3, 'filled': 2}

    assert area_progress_line(counts, StatusSettings(language='en')) == (
        'Area: 7 members · filling 3 · done 2 · waiting 2'
    )
    assert area_progress_line(counts, StatusSettings(language='ru')) == (
        'Площадь: 7 участников · заполняется 3 · готово 2 · ожидают 2'
    )


def test_an_unknown_language_falls_back_the_way_every_other_line_does():
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    line = area_progress_line({'members': 1}, StatusSettings(language='de'))

    assert line.startswith('Площадь: 1 участник ·')


def test_the_tail_terms_switch_language_too():
    """A line whose head is English and whose tail is Russian is the
    half-translated message the switch exists to prevent."""
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    counts = {'members': 7, 'running': 0, 'filled': 4, 'failed': 2,
              'not_attempted': 1}

    english = area_progress_line(counts, StatusSettings(language='en'))

    assert 'failed 2' in english
    assert 'not started 1' in english
    assert 'не' not in english


def test_the_plural_rule_has_one_implementation():
    """`_members_word` and the status line both need it, and two copies of
    «участник/участника/участников» is the shape this tree keeps removing."""
    from open_webui.services.artifacts.geotizer.area_request import _members_word
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    russian = StatusSettings(language='ru')
    for count in (1, 2, 4, 5, 11, 14, 21, 22, 25, 101, 111):
        assert _members_word(count) == russian.members_word(count), count


def test_english_pluralises_on_one_and_nothing_else():
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    english = StatusSettings(language='en')

    assert english.members_word(1) == 'member'
    assert [english.members_word(n) for n in (0, 2, 11, 21)] == ['members'] * 4


def test_counts_that_do_not_add_up_never_print_a_negative():
    """«Ожидают» is a subtraction, and a subtraction of numbers this
    function did not count. The loop keeps them consistent; the renderer is
    a separate module reached by a separate caller, and «ожидают -1» would
    be the line reporting a member that un-exists."""
    line = area_progress_line(
        {'members': 2, 'running': 1, 'filled': 2, 'failed': 0, 'not_attempted': 0}
    )

    assert '-' not in line, line
    assert 'ожидают 0' in line


# -- The link is only as good as the route behind it --------------------------
#
# The first seven-member area printed «Скачать CPR-отчёт» over a dead link and
# that was fixed here, in the rendering. The second printed a `summary.md`
# link that resolved to «no geotizer artifact at /files/area_6c2d1043…
# /summary.md» — and this time the rendering was right. The GIS service wrote
# the file and published the route; the fork's proxy, the only one of the
# three a browser can reach, did not know the name.
#
# Read with `ast` rather than imported: `open_webui.routers.geotizer` pulls
# `aiohttp` and `open_webui.config`, and importing the latter deletes tracked
# files from `backend/open_webui/static`. A guard that damages the tree it
# guards is not one.

PROXY_SOURCE = REPO_ROOT / 'backend' / 'open_webui' / 'routers' / 'geotizer.py'


def _proxy_artifacts() -> tuple[set[str], set[str]]:
    """`(names in the ARTIFACTS mapping, names a GET route serves)`."""
    import ast

    tree = ast.parse(PROXY_SOURCE.read_text(encoding='utf-8'))

    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != 'ARTIFACTS':
            continue
        assert isinstance(node.value, ast.Dict), 'ARTIFACTS is no longer a literal'
        for key in node.value.keys:
            assert isinstance(key, ast.Constant), key
            names.add(str(key.value))

    routed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            first = decorator.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            path = first.value
            prefix = '/files/{run_id}/'
            if path.startswith(prefix):
                routed.add(path[len(prefix):])

    return names, routed


def test_every_artefact_the_area_links_is_one_the_wrapper_can_serve():
    """The two halves are separate and each alone is a dead link.

    A name absent from `ARTIFACTS` reaches `_download_artifact` and raises
    `KeyError` after the upstream fetch has already succeeded; a name present
    there with no route falls through to the catch-all under
    `/api/v1/geotizer` and answers 404 with a body that reads like the file
    does not exist. Both look, to whoever clicked, exactly like the artefact
    was never written.
    """
    names, routed = _proxy_artifacts()

    linked = {name for name, _label in AREA_ARTEFACT_LABELS}

    assert linked <= names, sorted(linked - names)
    assert linked <= routed, sorted(linked - routed)


def test_the_wrapper_serves_nothing_it_has_no_mapping_for():
    """The other direction. A route without an entry gets as far as reading
    `ARTIFACTS[artifact]` for its media type — after the upstream download —
    and turns a working file into a 500."""
    names, routed = _proxy_artifacts()

    assert routed <= names, sorted(routed - names)


TERMINAL_SOURCE = (
    REPO_ROOT / 'backend' / 'open_webui' / 'services' / 'artifacts'
    / 'geotizer' / 'terminal.py'
)


def _attachment_content_types() -> dict[str, str]:
    """`ATTACHMENT_CONTENT_TYPES`, read rather than imported."""
    import ast

    tree = ast.parse(TERMINAL_SOURCE.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != 'ATTACHMENT_CONTENT_TYPES':
            continue
        assert isinstance(node.value, ast.Dict), 'no longer a literal'
        return {
            str(key.value): str(value.value)
            for key, value in zip(node.value.keys, node.value.values)
        }
    raise AssertionError('ATTACHMENT_CONTENT_TYPES not found')


def test_every_served_artifact_can_also_be_attached_read_without_importing():
    """The same contract `test_every_served_artifact_can_be_attached` holds,
    reachable in a checkout that cannot import the application.

    That test is the one that caught `summary.md` missing its content type —
    and it imports `open_webui.routers.geotizer`, which pulls
    `open_webui.storage.provider` and therefore `azure`. In a container
    without it the test does not collect, so the defect was invisible until
    CI. A guard that only runs in CI is a guard whoever made the mistake
    cannot use.

    Read with `ast`, so it runs anywhere. It does not replace the importing
    test: that one checks the objects the application actually builds, and
    this one checks what the source says they are.
    """
    served, _routed = _proxy_artifacts()
    attachable = _attachment_content_types()

    assert served == set(attachable), {
        'served only': sorted(served - set(attachable)),
        'attachable only': sorted(set(attachable) - served),
    }


def test_a_partial_write_links_the_files_that_did_land():
    """«Written: false» is two different things and the answer said one.

    A fold whose identifier could not be built stored nothing. A fold that
    stored four files and failed on the fifth stored four — and both were
    answered «у свёртки не было того, из чего строится её идентификатор»,
    which is false for the second and sends the reader after a request
    field while the workbook sits on disk, served by its route, linked by
    nothing.
    """
    lines = area_artifact_lines(
        {
            'written': False,
            'partial': True,
            'run_id': AREA_ID,
            'missing_inputs': [],
            'error': 'IllegalCharacterError: control character',
            'written_before_failure': ['run_log.json', 'state.json'],
            'files': _files('run_log.json', 'state.json'),
        }
    )
    text = '\n'.join(lines)

    assert 'IllegalCharacterError' in text
    assert 'state.json' in text
    assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/state.json' in text
    # And it does NOT claim the fold had nothing to build an identifier from.
    assert 'идентификатор' not in text


def test_a_fold_that_could_not_be_stored_at_all_still_says_which_field():
    """The other half, unchanged: no `partial`, so the message that names
    the missing input is the right one."""
    lines = area_artifact_lines(
        {'written': False, 'missing_inputs': ['project_id'], 'files': {}}
    )

    assert len(lines) == 1
    assert 'project_id' in lines[0]
