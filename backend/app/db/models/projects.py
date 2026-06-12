from __future__ import annotations

from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ProjectStatus
from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_request: Mapped[str] = mapped_column(Text, nullable=False)
    research_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    audience: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outputs_requested: Mapped[list[str] | None] = mapped_column(JSONColumn, nullable=True)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.draft.value, index=True
    )
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
