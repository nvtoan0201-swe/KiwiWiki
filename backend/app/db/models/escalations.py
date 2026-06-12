from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import EscalationStatus
from app.db.base import Base, JSONColumn, UUIDMixin


class Escalation(UUIDMixin, Base):
    __tablename__ = "escalations"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    # ambiguous_scope | thin_literature | unresolved_contradiction | high_stakes
    trigger: Mapped[str] = mapped_column(String(48), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    options: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EscalationStatus.open.value, index=True
    )
    user_response: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
