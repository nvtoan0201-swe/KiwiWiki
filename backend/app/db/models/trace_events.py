from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, UUIDMixin


class TraceEvent(UUIDMixin, Base):
    """One span in a run's trace: an LLM call (tokens, model, prompt version)
    or a source call (adapter, operation). Stage executions are the coarse
    spans; these are the fine-grained ones threaded under them. The trace id
    is the run id."""

    __tablename__ = "trace_events"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # llm_call | source_call
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
