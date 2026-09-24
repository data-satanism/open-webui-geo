"""`GeotizerGisError` accepts any `details` shape without raising, and the
infrastructure raise site says which shape GIS returned."""

from __future__ import annotations

import json

import pytest

from open_webui.services.geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
)


def test_a_list_of_violations_is_carried_not_crashed_on():
    """A list of violations is carried as `details['violations']`."""
    error = GeotizerGisError(['licence layer has no CRS', 'road role did not bind'])

    assert error.details == {
        'violations': ['licence layer has no CRS', 'road role did not bind']
    }


def test_a_bare_string_becomes_a_message():
    """A bare string is carried as `details['message']`."""
    assert GeotizerGisError('gis_project_not_found').details == {
        'message': 'gis_project_not_found'
    }


def test_none_is_an_empty_detail_rather_than_a_TypeError():
    """None or no argument gives empty details."""
    assert GeotizerGisError(None).details == {}
    assert GeotizerGisError().details == {}


def test_a_mapping_is_unchanged():
    """A mapping is carried unchanged."""
    assert GeotizerGisError({'code': 'gis_validation_failed', 'violations': []}).details == {
        'code': 'gis_validation_failed',
        'violations': [],
    }


def test_anything_else_is_stringified_rather_than_raising():
    """Any other value is carried as its string in `details['message']`."""
    assert GeotizerGisError(42).details == {'message': '42'}


def test_the_message_is_still_json_a_caller_can_read():
    error = GeotizerGisError(['одна претензия'])

    assert json.loads(str(error)) == {'violations': ['одна претензия']}


def test_it_is_still_the_orchestration_error_callers_catch():
    """`GeotizerGisError` is a `GeotizerOrchestrationError`."""
    assert isinstance(GeotizerGisError(['x']), GeotizerOrchestrationError)


def test_the_message_says_which_shape_arrived():
    """The length `dict()` reports on failure is 1 for a bare string and the first
    element's length for a list of strings."""
    def failing_length(argument):
        try:
            dict(argument)
        except ValueError as exc:
            return str(exc).split('length ')[1].split(';')[0]
        return None

    assert failing_length(['licence layer has no CRS']) == '24'
    assert failing_length('no layers') == '1'


_INFRASTRUCTURE_BATCH = {
    'batch_id': 'GIS-DC',
    'fields': [{'field_key': 'geotizer_object.v1.r078.a01'}],
}


@pytest.mark.asyncio
async def test_the_infrastructure_raise_names_what_gis_returned():
    """The infrastructure raise names the code, the returned field, the violations and
    the workflow status."""
    from open_webui.services.artifacts.geotizer import workflow

    async def _gis(payload):
        assert payload['action'] == 'infrastructure_proposals'
        return {
            'workflow_status': 'validation_failed',
            'violations': ['no infrastructure layer intersects the licence'],
        }

    with pytest.raises(GeotizerGisError) as raised:
        await workflow._deterministic_infrastructure_evidence(
            next_batch=_INFRASTRUCTURE_BATCH,
            run_id='run-1',
            allowed_field_keys=[],
            gis_call=_gis,
            cache={},
        )

    details = raised.value.details
    assert details['code'] == 'gis_infrastructure_unavailable'
    assert details['returned'] == 'violations'
    assert details['violations'] == ['no infrastructure layer intersects the licence']
    assert details['workflow_status'] == 'validation_failed'


@pytest.mark.asyncio
async def test_a_string_error_is_labelled_as_one():
    """A string `error` is labelled `returned: error` and carries an empty `violations`
    list."""
    from open_webui.services.artifacts.geotizer import workflow

    async def _gis(payload):  # noqa: ARG001
        return {'workflow_status': 'failed', 'error': 'run volume is gone'}

    with pytest.raises(GeotizerGisError) as raised:
        await workflow._deterministic_infrastructure_evidence(
            next_batch=_INFRASTRUCTURE_BATCH,
            run_id='run-1',
            allowed_field_keys=[],
            gis_call=_gis,
            cache={},
        )

    assert raised.value.details['returned'] == 'error'
    assert raised.value.details['error'] == 'run volume is gone'
    assert raised.value.details['violations'] == [], 'empty, and present, because absent and none differ'
