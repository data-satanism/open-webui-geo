"""The upstream symbols `tools/geotizer_retrieval.py` borrows still exist."""

from __future__ import annotations

import inspect

import pytest

PUBLIC_SYMBOLS = [
    ('open_webui.retrieval.utils', 'query_collection'),
    ('open_webui.retrieval.utils', 'query_collection_with_hybrid_search'),
    ('open_webui.retrieval.vector.async_client', 'ASYNC_VECTOR_DB_CLIENT'),
    ('open_webui.routers.retrieval', 'get_retrieval_config'),
]

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
    """The private upstream `_validate_collection_access` is a coroutine
    function whose first two parameters are `collection_names` and `user`."""
    function = resolve(*PRIVATE_SYMBOL)

    assert inspect.iscoroutinefunction(function)
    parameters = list(inspect.signature(function).parameters)
    assert parameters[:2] == ['collection_names', 'user'], parameters


def test_the_wrapper_raises_something_readable_when_the_private_symbol_goes():
    """Without the private upstream symbol the wrapper raises a `RuntimeError`
    naming the symbol and saying access cannot be checked."""
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
    """The retrieval plan handler and its form are importable from `tools/geotizer_retrieval.py`."""
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
    """The handler takes `request`, `form_data` and a required `user`, with no default."""
    from open_webui.tools.geotizer_retrieval import (
        query_geomas_retrieval_plan_handler,
    )

    parameters = inspect.signature(query_geomas_retrieval_plan_handler).parameters
    assert list(parameters) == ['request', 'form_data', 'user']
    assert parameters['user'].default is inspect.Parameter.empty


def test_the_route_is_gone_and_the_upstream_router_imports_no_fork_code():
    """`routers/retrieval.py` has no `geomas-plan` route and references no fork code."""
    from pathlib import Path

    source = Path('backend/open_webui/routers/retrieval.py').read_text(encoding='utf-8')

    assert 'geomas-plan' not in source
    assert 'GeoMASRetrievalPlanForm' not in source
    assert 'open_webui.services' not in source
