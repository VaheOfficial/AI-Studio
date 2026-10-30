"""Mirrors api/contracts/agentPlus.ts."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class AcceptanceCase(BaseModel):
    args: dict[str, Any]
    expected: Any = None
    error_contains: str | None = None

    @model_validator(mode="after")
    def has_oracle(self) -> AcceptanceCase:
        if "expected" not in self.model_fields_set and not self.error_contains:
            raise ValueError("Each case needs expected or error_contains")
        if self.expected is not None and self.error_contains:
            raise ValueError("Use expected or error_contains, not both")
        return self


class MissionCriterion(BaseModel):
    id: str
    text: str
    evidence: list[str] = Field(default_factory=list)


class AgentPlusMission(BaseModel):
    session_id: str
    original_request: str
    objective: str
    version: int = 1
    status: Literal["ready", "running", "paused", "blocked", "completed", "cancelled"] = "ready"
    reason: str | None = None
    criteria: list[MissionCriterion]
    max_requests: int = 80
    requests: int = 0
    max_cost: float = 0
    cost: float = 0
    reserved_cost: float = 0
    created_at: str
    updated_at: str


class ChatCapability(BaseModel):
    id: str
    session_id: str
    name: str
    description: str
    version: int
    status: Literal["candidate", "validated", "failed", "retired"]
    code: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    acceptance: list[AcceptanceCase]
    checks: list[AcceptanceCase]
    results: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    limitations: str = ""
    code_hash: str
    created_at: str


class MissionAction(BaseModel):
    id: str
    name: str
    args: dict[str, Any]
    status: Literal["running", "succeeded", "failed", "uncertain", "resolved"]
    output: str | None = None
    created_at: str


class MissionEvent(BaseModel):
    seq: int
    kind: str
    text: str
    data: dict[str, Any]
    created_at: str


class MissionWork(BaseModel):
    id: str
    kind: Literal["delivery", "learning", "alternative", "validation"]
    objective: str = Field(min_length=1, max_length=8000)
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["pending", "running", "done", "blocked", "superseded"] = "pending"
    evidence: list[str] = Field(default_factory=list)
    superseded_reason: str | None = None


class AgentPlusDetail(BaseModel):
    mission: AgentPlusMission
    tools: list[ChatCapability]
    actions: list[MissionAction]
    events: list[MissionEvent]
    work: list[MissionWork] = Field(default_factory=list)


class AgentPlusCreate(BaseModel):
    model: str
    objective: str = Field(min_length=1, max_length=16000)
    criteria: list[str] = Field(min_length=1, max_length=30)
    max_requests: int = Field(default=80, ge=5, le=500)
    max_cost: float = Field(default=0, ge=0, le=100)


class AgentPlusAmend(BaseModel):
    version: int
    objective: str = Field(min_length=1, max_length=16000)
    criteria: list[str] = Field(min_length=1, max_length=30)
    max_requests: int | None = Field(default=None, ge=5, le=500)
    max_cost: float | None = Field(default=None, ge=0, le=100)


class EvAgentPlusUpdate(BaseModel):
    type: Literal["agentplus.update"] = "agentplus.update"
    session_id: str
