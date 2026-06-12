"""Project request/response schemas — the stable API contract for projects."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import ProjectStatus, Stage


class ProjectCreate(BaseModel):
    """Body for `POST /projects` — creates a draft. Only the original request is
    required; everything else is filled in by the scoping stage later."""

    title: str | None = Field(
        default=None, description="Optional title; derived from the request if omitted."
    )
    original_request: str = Field(..., min_length=3)
    audience: str | None = None
    outputs_requested: list[str] | None = None
    budget: dict[str, Any] | None = Field(
        default=None, description="Per-category ceilings; defaults applied if omitted."
    )


class ProjectUpdate(BaseModel):
    """Body for `PATCH /projects/{id}` — all fields optional."""

    title: str | None = None
    research_question: str | None = None
    scope: dict[str, Any] | None = None
    audience: str | None = None
    outputs_requested: list[str] | None = None
    budget: dict[str, Any] | None = None
    status: ProjectStatus | None = None
    current_stage: Stage | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    original_request: str
    research_question: str | None
    scope: dict[str, Any] | None
    audience: str | None
    outputs_requested: list[str] | None
    budget: dict[str, Any] | None
    status: str
    current_stage: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
