"""Project request/response schemas — the stable API contract for projects."""

from __future__ import annotations

import datetime
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import ProjectStatus, Stage

# Strip C0/C1 control characters (except \n and \t) from user text inputs.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class ProjectCreate(BaseModel):
    """Body for `POST /projects` — creates a draft. Only the original request is
    required; everything else is filled in by the scoping stage later. Text
    inputs are length-capped and control-character-stripped (phase 7 input
    safety): they flow into prompts and exports."""

    title: str | None = Field(
        default=None,
        max_length=200,
        description="Optional title; derived from the request if omitted.",
    )
    original_request: str = Field(..., min_length=3, max_length=10_000)
    audience: str | None = Field(default=None, max_length=64)
    outputs_requested: list[str] | None = Field(default=None, max_length=8)
    budget: dict[str, Any] | None = Field(
        default=None, description="Per-category ceilings; defaults applied if omitted."
    )

    @field_validator("title", "original_request", "audience")
    @classmethod
    def _sanitize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _CONTROL_CHARS.sub("", value).strip()


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
