from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin, embedding_column


class Source(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    credibility_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    triage_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    triage_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    embedding: Mapped[list[float] | None] = embedding_column()
