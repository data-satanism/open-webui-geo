"""`object_name` was required here too, and a licence registry cannot fill it.

`Licenses_2024_2025` carries `LUID = МАГ04805БЭ` and `SReg = Магаданская
область`, and no field in any licence layer names a deposit. The GIS specialist
found the record and refused to confirm which object it belongs to -- correctly,
because that link is documentary and not spatial.

Two things live on this side of the boundary. The tool's own guard, which is
what a model meets, and the run key, which decides whether two fills are one
run. The second is the quieter of the two: `object_name` becoming optional
turns `f'object:{object_name.strip()}'` into the constant `'object:'`, and
every licence-first run on the contour would then share one partition and the
second asker would be handed the first licence's card.
"""

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


# -- the guard a model meets --------------------------------------------------


@pytest.mark.asyncio
async def test_the_adapter_refuses_only_when_neither_argument_is_given():
    """Both named. Either satisfies it, so calling one "the" argument would
    send a caller looking for a field that was never the only option."""
    from open_webui.tools.geotizer import fill_geotizer

    result = await fill_geotizer(
        __request__=object(), __user__={'id': 'user-1', 'role': 'user'}
    )

    assert 'object_identity_missing' in result
    assert 'object_name' in result and 'licence_id' in result


def test_object_name_is_optional_on_the_tool_signature():
    """The signature is the tool schema. A required parameter is required in
    the JSON the model is shown, whatever the guard beneath it does."""
    import inspect

    from open_webui.tools.geotizer import fill_geotizer

    signature = inspect.signature(fill_geotizer)

    assert signature.parameters['object_name'].default == ''
    assert signature.parameters['licence_id'].default == ''


# -- the run key ---------------------------------------------------------------


def test_two_licences_with_no_names_are_two_runs():
    """The defect `object_name` becoming optional would otherwise introduce.
    Both partitions would be `object:` and the two cards would be one."""
    first = _identity(licence_id=LICENCE)
    second = _identity(licence_id=OTHER)

    assert first != second


def test_a_licence_first_run_partitions_on_the_licence():
    assert _identity(licence_id=LICENCE).project_id == f'licence:{LICENCE}'


def test_a_named_run_still_partitions_on_the_object():
    """What must not move: every fill that had a name keys exactly as before."""
    assert _identity(object_name='Верхне-Колпинское').project_id == (
        'object:Верхне-Колпинское'
    )


def test_a_project_still_wins_over_both():
    assert _identity(
        object_name='Верхне-Колпинское', licence_id=LICENCE, project_id='lekyn'
    ).project_id == 'lekyn'


def test_an_identity_with_nothing_in_it_is_refused_rather_than_keyed():
    """`''` would be a partition every caller shares. Raised rather than
    defaulted, because the adapter's guard is upstream of this and a call
    reaching here with nothing has already gone wrong."""
    with pytest.raises(GeotizerOrchestrationError, match='object_name'):
        _identity()
