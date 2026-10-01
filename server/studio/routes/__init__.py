"""HTTP routers. All JSON responses omit ``None`` fields so optional TS fields are absent, not null."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


class StudioRouter(APIRouter):
    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        # FastAPI's decorators always pass this keyword explicitly, so override rather than setdefault.
        kwargs["response_model_exclude_none"] = True
        super().add_api_route(path, endpoint, **kwargs)
