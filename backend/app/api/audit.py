"""Audit log read endpoint (paginated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLogEntry
from app.db.session import get_session
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page

router = APIRouter(prefix="/projects", tags=["audit"])


@router.get("/{project_id}/audit", response_model=Page[AuditLogRead])
async def list_audit(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Page[AuditLogRead]:
    total = (
        await session.scalar(
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.project_id == project_id)
        )
        or 0
    )
    result = await session.execute(
        select(AuditLogEntry)
        .where(AuditLogEntry.project_id == project_id)
        .order_by(AuditLogEntry.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(e) for e in result.scalars().all()],
        total=int(total),
        limit=limit,
        offset=offset,
    )
