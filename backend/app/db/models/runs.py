from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ProjectStatus
from app.db.base import Base, JSONColumn, UUIDMixin


class Run(UUIDMixin, Base):
    __tablename__ = "runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.running.value
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # saturation | coverage | stable_map | budget | user_stopped | error
    stopping_criterion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    budget_consumed: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
