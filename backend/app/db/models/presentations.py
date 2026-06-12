from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Presentation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "presentations"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    through_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_messages: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    slides: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    speaker_notes: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
