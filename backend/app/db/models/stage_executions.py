from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, UUIDMixin


class StageExecution(UUIDMixin, Base):
    __tablename__ = "stage_executions"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    # If this execution was entered via a loop-back, the stage it came from.
    loop_back_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
