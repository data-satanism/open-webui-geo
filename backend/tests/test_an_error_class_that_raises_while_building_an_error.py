"""`GeotizerGisError` crashed constructing the message that would have explained the failure.

The first licence-first fill started, reached batch 1, and died in
`errors.py` on `self.details = dict(details)`. What it was carrying — whatever
the GIS side objected to about a licence polygon inside a 49 026-polygon
registry — was destroyed before anyone could read it.

**This is run `475dc4f5`'s `ValueError` from weeks ago.** That was chased
across several rounds; every hypothesis was about a bare string reaching
`dict()` somewhere upstream, and an AST sweep of every `dict(x)` on the
start-to-first-batch path found nothing. Correctly: the call is inside the
error class, on a path only reached when GIS returns a failure, and an
object-first fill against `lekyn_new_data` never produced one.

**The number in the message says which shape arrived.** `dict()` reports the
length of the first element it could not unpack, so a realistic violations list
gives the length of its first sentence and `length 1` means a bare string —
`dict('no layers')` iterating into characters. `475dc4f5` was therefore the
`error` branch as a string, not the `violations` branch as a list. Both
crashed; only one did on that run, and the distinction is what
`test_the_message_says_which_shape_arrived` keeps legible.
"""

from __future__ import annotations

import json

import pytest

from open_webui.services.geotizer.errors import (
    GeotizerGisError,
    GeotizerOrchestrationError,
)


# -- the four shapes a caller actually passes ---------------------------------


def test_a_list_of_violations_is_carried_not_crashed_on():
    """The shape that killed the licence-first fill. `violations` is a list of
    strings and `dict()` reads the first as a key-value pair."""
    error = GeotizerGisError(['licence layer has no CRS', 'road role did not bind'])

    assert error.details == {
        'violations': ['licence layer has no CRS', 'road role did not bind']
    }


def test_a_bare_string_becomes_a_message():
    """`deterministic.get('error')` may be a plain string, and that path had the
    same exposure — it is the one `475dc4f5` took."""
    assert GeotizerGisError('gis_project_not_found').details == {
        'message': 'gis_project_not_found'
    }


def test_none_is_an_empty_detail_rather_than_a_TypeError():
    """`dict(None)` raises `TypeError`, not `ValueError` — a different crash
    from the same assumption, and just as undiagnosable."""
    assert GeotizerGisError(None).details == {}
    assert GeotizerGisError().details == {}


def test_a_mapping_is_unchanged():
    """What must not move: every caller that already passed a mapping keeps
    exactly the details it had."""
    assert GeotizerGisError({'code': 'gis_validation_failed', 'violations': []}).details == {
        'code': 'gis_validation_failed',
        'violations': [],
    }


def test_anything_else_is_stringified_rather_than_raising():
    """The branch no current caller uses. A boundary whose job is to carry a
    failure outward must not have a failure mode of its own, and `int` is the
    cheapest proof that the fallback is a fallback and not a fourth guess."""
    assert GeotizerGisError(42).details == {'message': '42'}


def test_the_message_is_still_json_a_caller_can_read():
    error = GeotizerGisError(['одна претензия'])

    assert json.loads(str(error)) == {'violations': ['одна претензия']}


def test_it_is_still_the_orchestration_error_callers_catch():
    """The hierarchy is load-bearing: `except GeotizerOrchestrationError` is how
    the adapter turns a GIS failure into a terminal envelope."""
    assert isinstance(GeotizerGisError(['x']), GeotizerOrchestrationError)


def test_the_message_says_which_shape_arrived():
    """Not a fix, a reading aid. `dict()` names the length of the first element
    it could not unpack, which is how `length 1` in `475dc4f5` identifies a
    bare string rather than the violations list everyone assumed."""
    def failing_length(argument):
        try:
            dict(argument)
        except ValueError as exc:
            return str(exc).split('length ')[1].split(';')[0]
        return None

    assert failing_length(['licence layer has no CRS']) == '24'
    assert failing_length('no layers') == '1'


# -- the raise site says which of the three it got ----------------------------
#
# `_receives_deterministic_gis` gates the call on a batch that actually asks
# an infrastructure row, so a bare `{'batch_id': 'GIS-DC'}` returns `[]` and
# never reaches the raise. r078 is one of the five prefixes it accepts.

_INFRASTRUCTURE_BATCH = {
    'batch_id': 'GIS-DC',
    'fields': [{'field_key': 'geotizer_object.v1.r078.a01'}],
}


@pytest.mark.asyncio
async def test_the_infrastructure_raise_names_what_gis_returned():
    """§3. The `or` chain passed a mapping, a list or the whole state through
    one positional and the receiver could not tell which. The constructor
    tolerates all three now; that is the boundary being robust, and not a
    reason for the caller to stay vague."""
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
    """The shape `475dc4f5` actually carried."""
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
