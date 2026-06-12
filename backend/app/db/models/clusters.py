from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Cluster(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "clusters"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    defining_characteristics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONColumn, nullable=True
    )
