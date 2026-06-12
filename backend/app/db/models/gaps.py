from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Gap(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "gaps"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    importance: Mapped[str | None] = mapped_column(String(16), nullable=True)  # high|medium|low
    confidence_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
