from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Provenance(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "provenance"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    passage: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_inference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # analysis | comparison | gap | report | presentation
    context: Mapped[str] = mapped_column(String(32), nullable=False)
    # The id of the output entity this provenance supports.
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
