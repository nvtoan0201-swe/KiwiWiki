from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDMixin


class Comparison(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "comparisons"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimensions: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    matrix: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    consensus_points: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
    contested_points: Mapped[list[Any] | None] = mapped_column(JSONColumn, nullable=True)
