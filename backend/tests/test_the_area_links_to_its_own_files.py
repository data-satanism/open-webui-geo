"""The area answer links every area artefact through the proxy, or says why there are none."""

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
            'source_report.md', 'source_report.pdf',
        ),
        'not_rendered': {},
    }
    record.update(overrides)
    return record


def _artifacts_before_the_source_report(**overrides):
    """The artefact record of a service that cannot build an area source report."""
    record = _artifacts(
        files=_files(
            'state.json', 'run_log.json', 'summary.md',
            'geotizer.xlsx', 'geotizer.docx',
        ),
        not_rendered={
            'source_report.md / source_report.pdf': 'the fold carries no locator'
        },
    )
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
    """Every file in the record's own file list is linked through the proxy prefix."""
    record = _artifacts()
    text = '\n'.join(area_artifact_lines(record))

    assert len(record['files']) == 7, sorted(record['files'])
    for name in record['files']:
        assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/{name}' in text, name


def test_the_source_report_is_a_link_and_not_a_sentence_about_its_absence():
    """The source report is linked, and the sentence about its absence is not printed."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    for name in ('source_report.md', 'source_report.pdf'):
        assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/{name}' in text, name
    assert AREA_ARTEFACT_LIMITS[0] not in text


def test_the_link_carries_the_proxy_prefix_a_browser_can_reach():
    """Area links carry the `/api/v1` proxy prefix and never the bare GIS path."""
    text = '\n'.join(area_artifact_lines(_artifacts()))

    assert '(/api/v1/geotizer/files/' in text
    assert '](/geotizer/files/' not in text


def test_a_path_the_service_did_not_build_is_not_linked():
    """A download path that is not a `/geotizer/files/` path is not linked."""
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
    """A missing artefact record yields one line naming the GIS service version."""
    lines = area_artifact_lines(None)

    assert len(lines) == 1
    assert 'GIS-сервиса' in lines[0]


def test_what_the_area_does_not_have_is_said_rather_than_absent():
    """What the service did not render is stated in the answer."""
    text = '\n'.join(area_artifact_lines(_artifacts_before_the_source_report()))

    assert 'source_report' in text
    assert 'not_rendered' in text


def test_the_source_report_limit_is_stated_with_where_to_look_instead():
    """Without an area source report the answer states the limit and points to the members' runs."""
    text = '\n'.join(
        area_artifact_lines(_artifacts_before_the_source_report())
    )

    for line in AREA_ARTEFACT_LIMITS:
        assert line in text
    assert 'run_id' in text


def test_a_service_too_old_to_report_the_gap_does_not_silence_it():
    """A record with no `not_rendered` key still prints the source-report limit."""
    record = _artifacts_before_the_source_report()
    record.pop('not_rendered')

    text = '\n'.join(area_artifact_lines(record))

    assert AREA_ARTEFACT_LIMITS[0] in text


def test_an_empty_record_is_the_service_saying_nothing_is_missing():
    """An empty `not_rendered` record prints no limit and announces nothing missing."""
    text = '\n'.join(area_artifact_lines(_artifacts(not_rendered={})))

    assert AREA_ARTEFACT_LIMITS[0] not in text
    assert 'Чего у площади нет' not in text


def test_a_service_that_closes_the_gap_stops_the_sentence():
    """A `not_rendered` record without the source report omits the source-report limit and prints what it does list."""
    text = '\n'.join(
        area_artifact_lines(
            _artifacts(not_rendered={'geotizer.pptx': 'no slide template'})
        )
    )

    assert AREA_ARTEFACT_LIMITS[0] not in text
    assert 'geotizer.pptx' in text


def test_written_with_no_usable_path_is_not_silence():
    """A written record with no usable download path yields one line saying so."""
    lines = area_artifact_lines(
        _artifacts(files={'geotizer.xlsx': {'download_path': ''}})
    )

    assert len(lines) == 1
    assert 'ни одного пригодного пути' in lines[0]


def test_the_answer_a_reader_sees_carries_the_links():
    """`render_area_answer` includes the artefact links and the summary markdown."""
    markdown = render_area_answer(_answer())

    assert f'{ARTEFACT_PROXY_PREFIX}/geotizer/files/{AREA_ID}/geotizer.xlsx' in markdown
    assert '# Свод' in markdown


def test_an_area_that_did_not_fold_offers_no_downloads():
    """An area whose aggregation was not performed offers no download links."""
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
    """The answer prints the area's name and links by its digest identifier."""
    markdown = render_area_answer(_answer())

    assert 'Тенгкели-Березовская площадь' in markdown
    assert AREA_ID in markdown


def test_the_line_is_the_members_not_the_rounds():
    line = area_progress_line(
        {'members': 7, 'running': 3, 'filled': 2, 'failed': 0, 'not_attempted': 0}
    )

    assert line == 'Площадь: 7 участников · заполняется 3 · готово 2 · ожидают 2'


def test_waiting_is_derived_and_the_terms_sum_to_the_members():
    """The progress line's terms, with waiting derived, sum to the member count."""
    for running, filled, failed, missed in ((0, 0, 0, 0), (1, 2, 1, 1), (0, 7, 0, 0)):
        counts = {
            'members': 7, 'running': running, 'filled': filled,
            'failed': failed, 'not_attempted': missed,
        }
        line = area_progress_line(counts)
        numbers = [int(part.split()[-1]) for part in line.split(' · ')[1:]]

        assert sum(numbers) == 7, line


def test_a_failure_is_never_folded_into_the_done_count():
    """Failed members are counted separately from done members."""
    line = area_progress_line(
        {'members': 7, 'running': 1, 'filled': 4, 'failed': 2, 'not_attempted': 0}
    )

    assert 'готово 4' in line
    assert 'не удалось 2' in line


def test_the_tail_terms_are_absent_when_they_are_zero():
    """The failed and not-started terms are omitted when zero."""
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
    """`area_progress_reporter` returns None when there is no emitter."""
    assert area_progress_reporter(None) is None


def test_the_reporter_emits_a_status_event_that_is_never_done():
    """The reporter emits a status event with `done: False`."""
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
    """The progress line follows the `StatusSettings` language."""
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
    """The failed and not-started terms are translated along with the rest of the line."""
    from open_webui.services.artifacts.geotizer.terminal import StatusSettings

    counts = {'members': 7, 'running': 0, 'filled': 4, 'failed': 2,
              'not_attempted': 1}

    english = area_progress_line(counts, StatusSettings(language='en'))

    assert 'failed 2' in english
    assert 'not started 1' in english
    assert 'не' not in english


def test_the_plural_rule_has_one_implementation():
    """`_members_word` agrees with `StatusSettings.members_word` for Russian."""
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
    """Counts exceeding the member total print a waiting count of zero, never a negative."""
    line = area_progress_line(
        {'members': 2, 'running': 1, 'filled': 2, 'failed': 0, 'not_attempted': 0}
    )

    assert '-' not in line, line
    assert 'ожидают 0' in line


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
    """Every linked area artefact has an `ARTIFACTS` entry and a download route in the proxy."""
    names, routed = _proxy_artifacts()

    linked = {name for name, _label in AREA_ARTEFACT_LABELS}

    assert linked <= names, sorted(linked - names)
    assert linked <= routed, sorted(linked - routed)


def test_the_wrapper_serves_nothing_it_has_no_mapping_for():
    """Every artefact the proxy routes has an `ARTIFACTS` entry."""
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
    """The proxy's `ARTIFACTS` names equal the keys of `ATTACHMENT_CONTENT_TYPES`, read from source."""
    served, _routed = _proxy_artifacts()
    attachable = _attachment_content_types()

    assert served == set(attachable), {
        'served only': sorted(served - set(attachable)),
        'attachable only': sorted(set(attachable) - served),
    }


def test_a_partial_write_links_the_files_that_did_land():
    """A partial write reports its error and links the files written before the failure."""
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
    assert 'идентификатор' not in text


def test_a_fold_that_could_not_be_stored_at_all_still_says_which_field():
    """A fold that stored nothing and is not partial names the missing input field."""
    lines = area_artifact_lines(
        {'written': False, 'missing_inputs': ['project_id'], 'files': {}}
    )

    assert len(lines) == 1
    assert 'project_id' in lines[0]
