"""Run + escalation request/response schemas — the Phase 1 API contract."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None
    stopping_criterion: str | None
    budget_consumed: dict[str, Any] | None


class RunStartResponse(BaseModel):
    run_id: str


class StopRunBody(BaseModel):
    reason: str | None = None


class BudgetAdjustBody(BaseModel):
    """Per-category ceiling overrides applied to the project mid-run. Only the
    categories provided are changed."""

    llm_tokens: float | None = None
    search_calls: float | None = None
    papers_read: float | None = None
    time: float | None = None


class EscalationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_id: str | None
    trigger: str
    question: str
    context: dict[str, Any] | None
    options: list[Any] | None
    status: str
    user_response: dict[str, Any] | None
    created_at: datetime.datetime
    resolved_at: datetime.datetime | None


class ResolveEscalationBody(BaseModel):
    user_response: dict[str, Any] = Field(..., min_length=1)


# --- per-run trace (phase 7 part C, internal debugging endpoint) ---------------------


class TraceStageSpan(BaseModel):
    stage: str
    status: str
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None
    duration_seconds: float | None
    loop_back_from: str | None
    llm_calls: int
    llm_tokens: int
    source_calls: int


class TraceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime.datetime
    stage: str | None
    kind: str
    duration_ms: float | None
    payload: dict[str, Any] | None


class TraceMetrics(BaseModel):
    duration_seconds: float | None
    llm_calls: int
    llm_tokens_total: int
    llm_tokens_by_stage: dict[str, int]
    llm_calls_by_prompt_version: dict[str, int]
    source_calls: int
    source_calls_by_adapter: dict[str, int]
    papers_read: float
    search_calls: float
    escalations: int
    loop_backs: int
    errors: int
    budget_consumed: dict[str, Any] | None


class RunTraceRead(BaseModel):
    trace_id: str  # the run id — one trace per run
    run: RunRead
    stages: list[TraceStageSpan]
    events: list[TraceEventRead]
    metrics: TraceMetrics
