"""OpenRouter: cloud catalog, pinned models and the account / spend summary."""

from __future__ import annotations

from fastapi import HTTPException, Query, Response

from .. import openrouter_catalog, openrouter_usage
from ..openrouter import OpenRouterError
from ..openrouter_catalog import CatalogError
from ..schemas_openrouter import CloudCatalogPage, CloudModel, CloudOutputFilter, CloudSort, OpenRouterAccount
from . import StudioRouter

router = StudioRouter(prefix="/api/openrouter")


def _upstream(exc: OpenRouterError) -> HTTPException:
    return HTTPException(502 if exc.status < 400 or exc.status >= 500 else exc.status, str(exc))


@router.get("/models", response_model=CloudCatalogPage)
async def cloud_models(output: CloudOutputFilter = "all", q: str = "", tools: bool = False, free: bool = False,
                       pinned: bool = False, max_input_price: float | None = Query(None, ge=0),
                       min_context: int | None = Query(None, ge=0), sort: CloudSort = "newest", limit: int = Query(60, ge=1, le=1000),
                       offset: int = Query(0, ge=0), refresh: bool = False) -> CloudCatalogPage:
    try:
        return await openrouter_catalog.search(output, q, tools, free, pinned, max_input_price, min_context, sort,
                                               limit, offset, refresh)
    except OpenRouterError as exc:
        raise _upstream(exc) from exc


@router.put("/pins/{model_id:path}", response_model=CloudModel)
async def pin_model(model_id: str) -> CloudModel:
    try:
        return await openrouter_catalog.pin(model_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except OpenRouterError as exc:
        raise _upstream(exc) from exc


@router.delete("/pins/{model_id:path}", status_code=204)
async def unpin_model(model_id: str) -> Response:
    try:
        openrouter_catalog.unpin(model_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return Response(status_code=204)


@router.get("/account", response_model=OpenRouterAccount)
async def account(refresh: bool = False) -> OpenRouterAccount:
    return await openrouter_usage.account(force=refresh)
