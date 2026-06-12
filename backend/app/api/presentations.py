"""Presentation REST endpoints (Phase 5): read + export. Editing controls land
with the Phase 6 viewer; the deck rows are versioned and immutable here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db.models import Presentation, Project
from app.db.session import get_session
from app.schemas.presentation import PresentationRead
from app.services import exports

router = APIRouter(tags=["presentations"])


async def _get_presentation(session: AsyncSession, presentation_id: str) -> Presentation:
    presentation = await session.get(Presentation, presentation_id)
    if presentation is None:
        raise NotFound(f"Presentation {presentation_id} not found")
    return presentation


@router.get("/projects/{project_id}/presentations", response_model=list[PresentationRead])
async def list_presentations(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> list[PresentationRead]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"Project {project_id} not found")
    rows = await session.execute(
        select(Presentation)
        .where(Presentation.project_id == project_id)
        .order_by(Presentation.version.desc())
    )
    return [PresentationRead.model_validate(p) for p in rows.scalars().all()]


@router.get("/presentations/{presentation_id}", response_model=PresentationRead)
async def get_presentation(
    presentation_id: str, session: AsyncSession = Depends(get_session)
) -> PresentationRead:
    return PresentationRead.model_validate(await _get_presentation(session, presentation_id))


@router.get("/presentations/{presentation_id}/export")
async def export_presentation(
    presentation_id: str,
    format: str = Query("pptx", description="pptx | md"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    presentation = await _get_presentation(session, presentation_id)
    exporter = exports.presentation_exporter(format)
    content = await exports.presentation_content(session, presentation)
    data = exporter.render(content)
    filename = f"presentation-v{presentation.version}.{exporter.extension}"
    return Response(
        content=data,
        media_type=exporter.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
