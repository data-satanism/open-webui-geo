"""Tests that a licence alone identifies a GeoTeaser fill: the adapter's guard
accepts `object_name` or `licence_id`, and the run key partitions on the
licence when no name is given."""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.workflow import (
    GeotizerOrchestrationError,
    geotizer_run_identity,
)

LICENCE = 'МАГ04805БЭ'
OTHER = 'СЛХ025834ТП'


def _identity(**overrides):
    payload = {
        'requester_id': 'user-1',
        'object_name': '',
        'project_id': None,
        'model_run_id': None,
        'allow_draft': True,
        'vision_collection_url': None,
    }
    payload.update(overrides)
    return geotizer_run_identity(**payload)


@pytest.mark.asyncio
async def test_the_adapter_refuses_only_when_neither_argument_is_given():
    """With neither `object_name` nor `licence_id` the adapter refuses with
    `object_identity_missing`, naming both."""
    from open_webui.tools.geotizer import fill_geotizer

    result = await fill_geotizer(
        __request__=object(), __user__={'id': 'user-1', 'role': 'user'}
    )

    assert 'object_identity_missing' in result
    assert 'object_name' in result and 'licence_id' in result


def test_object_name_is_optional_on_the_tool_signature():
    """`object_name` and `licence_id` default to empty on the tool signature."""
    import inspect

    from open_webui.tools.geotizer import fill_geotizer

    signature = inspect.signature(fill_geotizer)

    assert signature.parameters['object_name'].default == ''
    assert signature.parameters['licence_id'].default == ''


def test_two_licences_with_no_names_are_two_runs():
    """Two nameless licence-first runs have different identities."""
    first = _identity(licence_id=LICENCE)
    second = _identity(licence_id=OTHER)

    assert first != second


def test_a_licence_first_run_partitions_on_the_licence():
    assert _identity(licence_id=LICENCE).project_id == f'licence:{LICENCE}'


def test_a_named_run_still_partitions_on_the_object():
    """A named run partitions on `object:<name>`."""
    assert _identity(object_name='Верхне-Колпинское').project_id == (
        'object:Верхне-Колпинское'
    )


def test_a_project_still_wins_over_both():
    assert _identity(
        object_name='Верхне-Колпинское', licence_id=LICENCE, project_id='lekyn'
    ).project_id == 'lekyn'


def test_an_identity_with_nothing_in_it_is_refused_rather_than_keyed():
    """An identity with no project, name or licence raises
    `GeotizerOrchestrationError`."""
    with pytest.raises(GeotizerOrchestrationError, match='object_name'):
        _identity()
