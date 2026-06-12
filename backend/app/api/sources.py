"""Source library REST endpoints.

Read access to the sources a run discovered, plus the two user overrides the
Source Library screen offers (promote / exclude) and manual source addition.
Overrides are state-changing, so they write audit entries.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditActionType, DiscoveryChannel, TriageStatus
from app.core.errors import NotFound
from app.db.models import Contradiction, PaperAnalysis, Project, Source
from app.db.session import get_session
from app.schemas.common import Page
from app.schemas.sources import (
    AnalysisDetail,
    ContradictionRead,
    PaperAnalysisRead,
    SourceCreateManual,
    SourceOverrideBody,
    SourceRead,
)
from app.services.audit import AuditService

router = APIRouter(tags=["sources"])


async def _get_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"project {project_id} not found")
    return project


async def _get_source(session: AsyncSession, source_id: str) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise NotFound(f"source {source_id} not found")
    return source


@router.get("/projects/{project_id}/sources", response_model=Page[SourceRead])
async def list_sources(
    project_id: str,
    triage_status: str | None = Query(default=None),
    discovery_channel: str | None = Query(default=None),
    cluster_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Match against title/venue/abstract."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Page[SourceRead]:
    await _get_project(session, project_id)
    where = [Source.project_id == project_id]
    if triage_status:
        where.append(Source.triage_status == triage_status)
    if discovery_channel:
        where.append(Source.discovery_channel == discovery_channel)
    if cluster_id:
        where.append(Source.cluster_id == cluster_id)
    if q:
        pattern = f"%{q}%"
        where.append(
            or_(
                Source.title.ilike(pattern),
                Source.venue.ilike(pattern),
                Source.abstract.ilike(pattern),
            )
        )
    total = (await session.scalar(select(func.count()).select_from(Source).where(*where))) or 0
    result = await session.execute(
        select(Source)
        .where(*where)
        .order_by(Source.relevance_score.desc().nulls_last(), Source.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page[SourceRead](
        items=[SourceRead.model_validate(s) for s in result.scalars().all()],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects/{project_id}/sources",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_source_manually(
    project_id: str,
    body: SourceCreateManual,
    session: AsyncSession = Depends(get_session),
) -> SourceRead:
    await _get_project(session, project_id)
    source = Source(
        project_id=project_id,
        title=body.title,
        authors=body.authors,
        venue=body.venue,
        year=body.year,
        doi=body.doi,
        url=body.url,
        abstract=body.abstract,
        discovery_channel=DiscoveryChannel.user_supplied.value,
        triage_status=TriageStatus.deep_read.value,
        triage_reason="Added manually by the user.",
    )
    session.add(source)
    await session.flush()
    await AuditService(session).record(
        project_id=project_id,
        action_type=AuditActionType.paper_triaged,
        description=f"User added source manually: {body.title[:120]}",
        reasoning="User-supplied sources are trusted as relevant and queued for deep read.",
        payload={"source_id": source.id, "doi": body.doi},
    )
    await session.refresh(source)
    return SourceRead.model_validate(source)


@router.get("/sources/{source_id}", response_model=SourceRead)
async def get_source(source_id: str, session: AsyncSession = Depends(get_session)) -> SourceRead:
    return SourceRead.model_validate(await _get_source(session, source_id))


@router.post("/sources/{source_id}/override", response_model=SourceRead)
async def override_source(
    source_id: str,
    body: SourceOverrideBody,
    session: AsyncSession = Depends(get_session),
) -> SourceRead:
    source = await _get_source(session, source_id)
    previous = source.triage_status
    if body.action == "promote":
        source.triage_status = TriageStatus.deep_read.value
        source.triage_reason = body.reason or "Promoted by the user."
        description = f"User promoted source to deep read: {source.title[:120]}"
    else:
        source.triage_status = TriageStatus.excluded.value
        source.triage_reason = body.reason or "Excluded by the user."
        description = f"User excluded source: {source.title[:120]}"
    await session.flush()
    await AuditService(session).record(
        project_id=source.project_id,
        action_type=AuditActionType.paper_triaged,
        description=description,
        reasoning=body.reason or "User override from the Source Library.",
        payload={
            "source_id": source.id,
            "override": body.action,
            "previous_triage_status": previous,
        },
    )
    await session.refresh(source)
    return SourceRead.model_validate(source)


@router.get("/sources/{source_id}/analysis", response_model=AnalysisDetail)
async def get_source_analysis(
    source_id: str, session: AsyncSession = Depends(get_session)
) -> AnalysisDetail:
    source = await _get_source(session, source_id)
    analysis = await session.scalar(
        select(PaperAnalysis)
        .where(PaperAnalysis.source_id == source_id)
        .order_by(PaperAnalysis.created_at.desc())
        .limit(1)
    )
    contradictions = (
        await session.execute(
            select(Contradiction).where(
                or_(
                    Contradiction.source_a_id == source_id,
                    Contradiction.source_b_id == source_id,
                )
            )
        )
    ).scalars()
    return AnalysisDetail(
        source=SourceRead.model_validate(source),
        analysis=PaperAnalysisRead.model_validate(analysis) if analysis else None,
        contradictions=[ContradictionRead.model_validate(c) for c in contradictions],
    )
