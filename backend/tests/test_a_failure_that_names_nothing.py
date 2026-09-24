"""Tests for `failure_details` and `_error_result`: an exception that escaped
from below carries its traceback frame, while an error this project raised
carries its own details or none."""

from __future__ import annotations

import json

from open_webui.services.artifacts.geotizer.terminal import (
    MAX_TRACEBACK_LINES,
    _error_result,
    failure_details,
)
from open_webui.services.geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
)


def escaped() -> Exception:
    """Return the `ValueError` that passing a bare string to `dict.update`
    raises."""
    try:
        {'a': 1}.update('project_id=lekyn_new_data; layer_id=x')
    except ValueError as exc:
        return exc
    raise AssertionError('the reproduction did not raise')


def raised_by_us() -> Exception:
    try:
        raise GeotizerOrchestrationError('GeoTeaser stopped before all owner batches')
    except GeotizerOrchestrationError as exc:
        return exc


def test_an_escaped_exception_carries_its_frame():
    details = failure_details(escaped())

    assert details['escaped'] is True
    assert details['exception_type'] == 'ValueError'
    assert any('update' in line for line in details['traceback'])


def test_the_frame_names_the_file_and_the_line_that_raised():
    """The traceback names the file that raised."""
    details = failure_details(escaped())

    assert any(__file__.split('/')[-1] in line for line in details['traceback'])


def test_the_message_alone_was_never_enough():
    """The escaped exception's message names no project, licence, layer or
    locator."""
    message = 'dictionary update sequence element #0 has length 1; 2 is required'

    assert 'project' not in message
    assert 'licence' not in message
    assert 'layer' not in message
    assert 'source_locator' not in message


def test_the_innermost_frames_survive_truncation():
    """A truncated traceback keeps its innermost frames."""
    source = '\n'.join(
        [f'def f{index}():\n    return f{index + 1}()' for index in range(60)]
        + ["def f60():\n    return {'a': 1}.update('x=1')"]
    )
    namespace: dict = {}
    exec(compile(source, '<deep>', 'exec'), namespace)  # noqa: S102

    try:
        namespace['f0']()
    except ValueError as exc:
        details = failure_details(exc)

    assert len(details['traceback']) == MAX_TRACEBACK_LINES
    assert details['traceback_lines_dropped'] > 0
    assert any('update' in line for line in details['traceback'][-4:])


def test_an_error_we_raised_on_purpose_gets_no_frame():
    """An error this project raised gets no frame."""
    assert failure_details(raised_by_us()) is None


def test_a_structured_gis_failure_keeps_its_own_details():
    error = GeotizerGisError({'code': 'gis_project_ambiguous', 'candidates': []})

    assert failure_details(error) == {'code': 'gis_project_ambiguous', 'candidates': []}
    assert 'traceback' not in failure_details(error)


def test_deriving_from_valueerror_does_not_make_it_escaped():
    """A `GeotizerOrchestrationError` is a `ValueError` and still gets no
    frame."""
    assert isinstance(raised_by_us(), ValueError)
    assert failure_details(raised_by_us()) is None


def test_the_envelope_carries_the_frame_where_it_carried_null():
    envelope = json.loads(
        _error_result(
            type(escaped()).__name__,
            str(escaped()),
            run_id='475dc4f5-bd07-4bdd-ac2e-6c95ab397db0',
            details=failure_details(escaped()),
        )
    )

    assert envelope['code'] == 'ValueError'
    assert envelope['details']['escaped'] is True
    assert envelope['resumable'] is True
    assert envelope['run_id'] == '475dc4f5-bd07-4bdd-ac2e-6c95ab397db0'


def test_a_deliberate_refusal_still_shows_details_null():
    envelope = json.loads(
        _error_result(
            'GeotizerOrchestrationError',
            'GeoTeaser stopped before all owner batches',
            run_id='r',
            details=failure_details(raised_by_us()),
        )
    )

    assert envelope['details'] is None


def test_the_multi_licence_refusal_reaches_the_caller_as_prose():
    """A GIS refusal carrying `licence_scope` reaches the caller as the
    service's own message and is not resumable."""
    envelope = json.loads(
        _error_result(
            'GeotizerGisError',
            'ignored',
            run_id=None,
            details={
                'code': 'gis_project_multi_licence',
                'message': (
                    'Проект содержит 47 лицензионных полигонов; заполнение '
                    'одного объекта требует проекта с одним. Укажите проект '
                    'объекта или лицензию внутри набора.'
                ),
                'licence_scope': {'status': 'many', 'licence_polygon_count': 47},
            },
        )
    )

    assert '47' in envelope['user_message']
    assert envelope['user_message'].startswith('Проект содержит')
    assert envelope['resumable'] is False


def test_a_failure_with_no_licence_scope_still_falls_back_to_its_message():
    envelope = json.loads(
        _error_result('X', 'plain message', run_id='r', details={'message': 'not used'})
    )

    assert envelope['user_message'] == 'plain message'
