"""Pydantic mirror of ``apps/studio/src/api/contracts/hub.ts`` — model hub and local text backends."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .schemas import Fit, LocalBackendId, ModelKind, RuntimeId, WeightFormat

HubCatalog = Literal["hf", "ollama", "lmstudio"]
HubSource = Literal["hf", "ollama"]
HubSort = Literal["downloads", "trending", "likes", "updated"]


class HubSearchResult(BaseModel):
    id: str
    source: HubSource
    name: str
    author: str | None = None
    kind: ModelKind | None = None
    task: str | None = None
    downloads: int | None = None
    likes: int | None = None
    updated_at: str | None = None
    license: str | None = None
    gated: bool
    formats: list[WeightFormat]
    tags: list[str]
    description: str | None = None


class HubFile(BaseModel):
    path: str
    size: int


class HubCompanions(BaseModel):
    repo: str
    files: list[str]
    size_bytes: int
    gated: bool


class HubVariant(BaseModel):
    id: str
    ref: str
    label: str
    format: WeightFormat
    quant: str | None = None
    kind: ModelKind
    files: list[str]
    size_bytes: int
    companions: HubCompanions | None = None
    vram_gb: float
    fit: Fit
    runtimes: list[RuntimeId]
    note: str | None = None
    recommended: bool | None = None
    installed_id: str | None = None


class HubRepo(BaseModel):
    id: str
    source: HubSource
    name: str
    author: str | None = None
    kind: ModelKind | None = None
    task: str | None = None
    license: str | None = None
    gated: bool
    base_models: list[str]
    downloads: int | None = None
    likes: int | None = None
    updated_at: str | None = None
    tags: list[str]
    summary: str | None = None
    url: str
    files: list[HubFile]
    variants: list[HubVariant]
    related: list[HubSearchResult]


class HubInstallRequest(BaseModel):
    source: HubSource
    repo: str
    variant: str
    runtime: RuntimeId | None = None


class LocalBackend(BaseModel):
    id: LocalBackendId
    name: str
    installed: bool
    running: bool
    version: str | None = None
    endpoint: str | None = None
    models_dir: str | None = None
    detail: str | None = None
    install_url: str | None = None
