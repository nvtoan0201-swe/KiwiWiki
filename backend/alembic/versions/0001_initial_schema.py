"""initial shared schema + pgvector extension

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11

The schema is built from the models' metadata so the migration can never drift
from the ORM definitions. On PostgreSQL the `vector` extension is enabled first
(the `sources.embedding` column needs it); on other dialects (SQLite, used in
tests) that step is skipped and the portable column variants apply.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.base import Base

# Import models so every table is registered on Base.metadata.
import app.db.models  # noqa: F401

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
