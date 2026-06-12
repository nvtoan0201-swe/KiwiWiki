from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class PaperAnalysis(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "paper_analyses"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    core_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    datasets: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    author_limitations: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    agent_critique: Mapped[str | None] = mapped_column(Text, nullable=True)
    credibility_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
