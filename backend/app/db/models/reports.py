from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Report(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audience: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    self_check_result: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    stopping_criterion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
