"""Source library request/response schemas — the read/override API contract
that the Source Library and Paper Analysis Detail screens bind to."""

from __future__ import annotations

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    authors: list[Any] | None
    venue: str | None
    year: int | None
    doi: str | None
    url: str | None
    abstract: str | None
    discovery_channel: str | None
    relevance_score: float | None
    credibility_score: float | None
    triage_status: str | None
    triage_reason: str | None
    cluster_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SourceCreateManual(BaseModel):
    """Body for `POST /projects/{id}/sources` — a user-supplied source.

    Size/type-checked at the boundary (phase 7 input safety): these fields
    flow into prompts, exports, and dedup keys."""

    title: str = Field(..., min_length=3, max_length=500)
    authors: list[str] | None = Field(default=None, max_length=50)
    venue: str | None = Field(default=None, max_length=300)
    year: int | None = Field(default=None, ge=1000, le=2100)
    doi: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    abstract: str | None = Field(default=None, max_length=20_000)


class SourceOverrideBody(BaseModel):
    """Body for `POST /sources/{id}/override` — a user triage override.

    `promote` marks the source for deep reading; `exclude` removes it from
    consideration. Both are audited with the user's reason.
    """

    action: Literal["promote", "exclude"]
    reason: str | None = None


class PaperAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    core_claim: str | None
    method: str | None
    results: list[Any] | dict[str, Any] | None
    datasets: list[Any] | None
    author_limitations: list[Any] | None
    agent_critique: str | None
    credibility_breakdown: dict[str, Any] | None
    confidence_label: str | None
    created_at: datetime.datetime


class ContradictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_a_id: str
    source_b_id: str
    description: str
    investigation: str | None
    resolution: str | None
    resolved: bool


class AnalysisDetail(BaseModel):
    """`GET /sources/{id}/analysis` — the structured record plus the
    contradiction flags that involve this source."""

    source: SourceRead
    analysis: PaperAnalysisRead | None
    contradictions: list[ContradictionRead] = Field(default_factory=list)
