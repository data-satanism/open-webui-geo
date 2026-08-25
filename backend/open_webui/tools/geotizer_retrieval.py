"""GeoMAS retrieval-plan execution, owned by the fork.

This used to be a route in `routers/retrieval.py` -- an upstream file -- and
that is how it came to be deleted. The `Current_Geomas` version-bump merge
rewrote that module and dropped the whole GeoMAS block: the form, the route and
the handler, leaving `validate_retrieval_plan` and `build_grounded_retrieval_trace`
imported at the top with nothing using them, which is the fingerprint of an
accident rather than a decision.

Nothing caught it. `tools/geotizer.py` imports the handler *inside* the
function that calls it, so the app booted, every test passed, and the failure
waited for a GeoTeaser run to execute a retrieval plan -- where an `ImportError`
arrives as a specialist failure with no obvious cause.

It lives here now because nothing calls it over HTTP. `geomas-plan` appeared
exactly twice in the tree: the route definition and a sentence in the fork's
own `prompts.py`. The route registered an endpoint with no client, and the one
caller awaits the handler directly. Moving it removes an upstream file from the
fork's footprint without changing a line of what it does.

`services/` cannot host it: the purity boundary forbids importing the router
surface, and this needs `_validate_collection_access` and `get_retrieval_config`
from `routers.retrieval`. `tools/` already holds fork files.

**The signature keeps its parameter names and order and drops one dead
default.** It was `user=Depends(get_verified_user)`, which FastAPI resolved
when this was a route. Nothing resolves it now, so leaving it would hand a
`Depends` object to any caller that omitted the argument -- a worse failure
than a missing one. The single caller passes all three positionally.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from open_webui.retrieval.utils import (
    query_collection,
    query_collection_with_hybrid_search,
)
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.routers.retrieval import get_retrieval_config
from open_webui.services.project_evidence.retrieval import (
    build_grounded_retrieval_trace,
    validate_retrieval_plan,
)


async def _validate_collection_access(collection_names: list[str], user) -> None:
    """`routers.retrieval._validate_collection_access`, behind a name we own.

    The only private upstream symbol this module needs. Importing upstream is
    merge-safe; depending on a *private* name is not, because upstream may
    rename `_validate_collection_access` in a patch release without that
    counting as a breaking change -- the leading underscore is the statement
    that it may.

    Imported here rather than at module scope so the failure names itself. A
    top-level import would make this module unimportable and the traceback
    would point at an import line; this raises where the access check would
    have run, saying which symbol went and that access was therefore not
    checked. `test_upstream_retrieval_symbols.py` turns the same disappearance
    into a failing test at merge time instead.
    """
    try:
        from open_webui.routers.retrieval import (
            _validate_collection_access as _upstream_validate,
        )
    except ImportError as error:  # pragma: no cover - exercised by the symbol test
        raise RuntimeError(
            'open_webui.routers.retrieval._validate_collection_access is gone; '
            'collection access for GeoMAS retrieval plans cannot be checked. '
            'This is a private upstream symbol -- see '
            'backend/tests/test_upstream_retrieval_symbols.py'
        ) from error
    await _upstream_validate(collection_names, user)


class GeoMASRetrievalPlanForm(BaseModel):
    plan: dict
    collection_names: list[str]
    hybrid: bool | None = None


async def query_geomas_retrieval_plan_handler(
    request: Request,
    form_data: GeoMASRetrievalPlanForm,
    user,
):
    """Execute only the exact query serialized by a validated GeoMAS plan."""

    violations = validate_retrieval_plan(form_data.plan)
    if violations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={'code': 'invalid_retrieval_plan', 'violations': list(violations)},
        )
    if form_data.plan.get('status') != 'planned':
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={'code': 'retrieval_plan_not_executable'},
        )
    if not form_data.collection_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={'code': 'collections_required'},
        )
    planned_collections = set((form_data.plan.get('trace_context') or {}).get('collections') or [])
    if planned_collections and planned_collections != set(form_data.collection_names):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={'code': 'collections_do_not_match_plan'},
        )
    await _validate_collection_access(form_data.collection_names, user)
    config = await get_retrieval_config()
    exact_query = str(form_data.plan['exact_query'])
    top_k = int(form_data.plan['top_k'])
    fetch_k = min(50, max(top_k * 5, top_k))
    backend_path: list[str] = []
    backend_failures: list[dict[str, object]] = []
    result = None
    use_hybrid = config.ENABLE_RAG_HYBRID_SEARCH and form_data.hybrid is not False
    if use_hybrid:
        native_hybrid = (
            ASYNC_VECTOR_DB_CLIENT.supports_hybrid_search and not config.ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS
        )
        backend_name = 'native_hybrid' if native_hybrid else 'legacy_hybrid_cached_enriched'
        try:
            result = await query_collection_with_hybrid_search(
                collection_names=form_data.collection_names,
                queries=[exact_query],
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=fetch_k,
                reranking_function=(
                    (lambda query, documents: request.app.state.RERANKING_FUNCTION(query, documents, user=user))
                    if request.app.state.RERANKING_FUNCTION
                    else None
                ),
                k_reranker=max(fetch_k, config.TOP_K_RERANKER),
                r=config.RELEVANCE_THRESHOLD,
                hybrid_bm25_weight=config.HYBRID_BM25_WEIGHT,
                enable_enriched_texts=config.ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS,
            )
            backend_path.append(backend_name)
        except Exception as error:
            backend_failures.append(
                {
                    'backend': backend_name,
                    'error_type': type(error).__name__,
                    'terminal': False,
                }
            )
    if result is None:
        backend_name = 'vector_fallback' if use_hybrid else 'vector'
        try:
            result = await query_collection(
                None,
                collection_names=form_data.collection_names,
                queries=[exact_query],
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=fetch_k,
            )
            backend_path.append(backend_name)
        except Exception as error:
            backend_failures.append(
                {
                    'backend': backend_name,
                    'error_type': type(error).__name__,
                    'terminal': True,
                }
            )
    return build_grounded_retrieval_trace(
        form_data.plan,
        result,
        collections=form_data.collection_names,
        backend_path=backend_path,
        backend_failures=backend_failures,
    )
