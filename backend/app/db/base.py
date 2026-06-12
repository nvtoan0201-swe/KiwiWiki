"""Declarative base, common mixins, and portable column types.

`JSONColumn` and the embedding column use SQLAlchemy variants so the same models
run on PostgreSQL (JSONB + pgvector) in production and on SQLite in tests, where
pgvector/JSONB are unavailable. Production behavior is unchanged; SQLite just
sees plain JSON / a JSON-encoded vector.
"""

from __future__ import annotations

import datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON as SA_JSON
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

# JSONB on Postgres, plain JSON on SQLite (tests).
JSONColumn = JSONB().with_variant(SA_JSON(), "sqlite")


def _new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def embedding_column() -> Mapped[list[float] | None]:
    """pgvector column on Postgres, JSON-encoded list on SQLite. Nullable until
    embeddings are populated in Phase 2/3."""
    dim = get_settings().embedding_dim
    return mapped_column(Vector(dim).with_variant(SA_JSON(), "sqlite"), nullable=True)
