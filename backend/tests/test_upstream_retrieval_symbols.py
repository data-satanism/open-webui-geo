"""The upstream symbols `tools/geotizer_retrieval.py` borrows still exist.

The GeoMAS retrieval handler used to live in `routers/retrieval.py`, and the
`Current_Geomas` version-bump merge deleted it along with the rest of that
block. Nothing noticed: the app booted, the suite passed, and the failure
waited for a run to execute a retrieval plan, where the `ImportError` surfaced
as a specialist failure with no obvious cause.

The handler is fork-owned now, which removes the file from the fork's
footprint but not the dependency: it still calls six things it does not own.
This is the test that converts their disappearance into a red build at merge
time rather than a red run weeks later.

One of the six is private. `_validate_collection_access` carries a leading
underscore, which is upstream saying it may be renamed in a patch release
without that counting as a breaking change -- so it is the one most likely to
go, and the only one wrapped behind a name the fork owns.
"""

from __future__ import annotations

import inspect

import pytest

PUBLIC_SYMBOLS = [
    ('open_webui.retrieval.utils', 'query_collection'),
    ('open_webui.retrieval.utils', 'query_collection_with_hybrid_search'),
    ('open_webui.retrieval.vector.async_client', 'ASYNC_VECTOR_DB_CLIENT'),
    ('open_webui.routers.retrieval', 'get_retrieval_config'),
]

#: Fork-owned, listed so the set the handler depends on is countable in one
#: place rather than split across two tests by who happens to own each module.
FORK_SYMBOLS = [
    ('open_webui.services.project_evidence.retrieval', 'validate_retrieval_plan'),
    ('open_webui.services.project_evidence.retrieval', 'build_grounded_retrieval_trace'),
]

PRIVATE_SYMBOL = ('open_webui.routers.retrieval', '_validate_collection_access')


def resolve(module_name: str, symbol: str):
    import importlib

    module = importlib.import_module(module_name)
    assert hasattr(module, symbol), f'{module_name}.{symbol} is gone'
    return getattr(module, symbol)


@pytest.mark.parametrize(('module_name', 'symbol'), PUBLIC_SYMBOLS + FORK_SYMBOLS)
def test_the_symbol_the_handler_imports_still_exists(module_name, symbol):
    assert resolve(module_name, symbol) is not None


def test_the_private_symbol_exists_with_the_signature_the_wrapper_expects():
    """The wrapper calls it as `(collection_names, user)` and awaits it. A
    rename is caught by the attribute check; a signature change that kept the
    name would otherwise fail at call time inside a run."""
    function = resolve(*PRIVATE_SYMBOL)

    assert inspect.iscoroutinefunction(function)
    parameters = list(inspect.signature(function).parameters)
    assert parameters[:2] == ['collection_names', 'user'], parameters


def test_the_wrapper_raises_something_readable_when_the_private_symbol_goes():
    """Not an ImportError from a module-scope import, which points at an import
    line and says nothing about access control. The message has to say which
    symbol went and that access was therefore not checked."""
    import open_webui.routers.retrieval as upstream
    from open_webui.tools import geotizer_retrieval

    saved = upstream._validate_collection_access
    del upstream._validate_collection_access
    try:
        with pytest.raises(RuntimeError) as caught:
            import asyncio

            asyncio.run(geotizer_retrieval._validate_collection_access(['c'], object()))
    finally:
        upstream._validate_collection_access = saved

    message = str(caught.value)
    assert '_validate_collection_access' in message
    assert 'cannot be checked' in message


def test_the_handler_and_its_form_are_importable_from_the_fork_module():
    """The move itself. `tools/geotizer.py` imports these two by name inside
    the function that calls them, so a broken move is invisible until a run."""
    from open_webui.tools.geotizer_retrieval import (
        GeoMASRetrievalPlanForm,
        query_geomas_retrieval_plan_handler,
    )

    assert inspect.iscoroutinefunction(query_geomas_retrieval_plan_handler)
    assert set(GeoMASRetrievalPlanForm.model_fields) == {
        'plan',
        'collection_names',
        'hybrid',
    }


def test_the_handler_takes_a_user_rather_than_a_fastapi_default():
    """It was a route and carried `user=Depends(get_verified_user)`. Nothing
    resolves that now, so a caller omitting the argument would have received a
    `Depends` object and checked access against it."""
    from open_webui.tools.geotizer_retrieval import (
        query_geomas_retrieval_plan_handler,
    )

    parameters = inspect.signature(query_geomas_retrieval_plan_handler).parameters
    assert list(parameters) == ['request', 'form_data', 'user']
    assert parameters['user'].default is inspect.Parameter.empty


def test_the_route_is_gone_and_the_upstream_router_imports_no_fork_code():
    """`geomas-plan` registered an endpoint with no HTTP client. What made it
    cost something was living in an upstream file."""
    from pathlib import Path

    source = Path('backend/open_webui/routers/retrieval.py').read_text(encoding='utf-8')

    assert 'geomas-plan' not in source
    assert 'GeoMASRetrievalPlanForm' not in source
    assert 'open_webui.services' not in source
