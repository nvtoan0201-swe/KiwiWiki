"""trace_events table (phase 7 part C: per-run tracing)

Revision ID: 0002_trace_events
Revises: 0001_initial
Create Date: 2026-06-12

Created from the model's own table definition so the migration cannot drift
from the ORM (same approach as 0001).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.models.trace_events import TraceEvent

revision: str = "0002_trace_events"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # checkfirst: a fresh database already got the table from 0001's
    # metadata.create_all; this revision exists for databases migrated earlier.
    TraceEvent.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    TraceEvent.__table__.drop(bind=op.get_bind(), checkfirst=True)
