"""Pydantic mirror of ``apps/studio/src/api/contracts/openrouter.ts`` (OpenRouter cloud catalog, pins, spend)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CloudUse = Literal["chat", "image", "voice", "stt"]
PriceUnit = Literal["input_mtok", "output_mtok", "image", "megapixel", "mchar", "minute", "request"]
CloudSort = Literal["newest", "price", "context", "name"]
CloudOutputFilter = Literal["all", "text", "image", "speech", "transcription", "video", "embeddings"]


class CloudPrice(BaseModel):
    usd: float
    unit: PriceUnit


class CloudModel(BaseModel):
    id: str
    name: str
    vendor: str
    description: str
    created: int
    context_length: int | None = None
    input_modalities: list[str]
    output_modalities: list[str]
    use: CloudUse | None = None
    tools: bool
    reasoning: bool
    free: bool
    prices: list[CloudPrice]
    price_dynamic: bool | None = None
    voices: list[str] | None = None
    pinned: bool


class CloudCatalogPage(BaseModel):
    models: list[CloudModel]
    total: int
    fetched_at: str


ChargeKind = Literal["chat", "title", "image", "speech", "transcription"]


class OpenRouterCharge(BaseModel):
    id: str
    ts: str
    kind: ChargeKind
    model: str
    cost: float | None = None
    session_id: str | None = None
    ref: str | None = None


class OpenRouterAccount(BaseModel):
    configured: bool
    management_key: bool
    ok: bool
    error: str | None = None
    label: str | None = None
    balance: float | None = None
    total_credits: float | None = None
    limit: float | None = None
    limit_remaining: float | None = None
    limit_reset: str | None = None
    usage_total: float | None = None
    usage_daily: float | None = None
    usage_weekly: float | None = None
    usage_monthly: float | None = None
    is_free_tier: bool | None = None
    studio_today: float
    recent: list[OpenRouterCharge]
    updated_at: str


class EvOpenRouterAccount(BaseModel):
    type: Literal["openrouter.account"] = "openrouter.account"
    account: OpenRouterAccount
