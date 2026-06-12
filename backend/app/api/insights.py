"""Read endpoints for the field map (comparison), gaps, and provenance traces.

These views are produced by the comparison/gap stages; this router only reads.
Provenance lookup is what the ProvenancePopover binds to — given a `ref_id`
(an output entity id) it returns the claim → source → passage chain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db.models import Cluster, Comparison, Contradiction, Gap, Project, Provenance
from app.db.session import get_session
from app.schemas.insights import (
    ClusterRead,
    ComparisonRead,
    FieldMapRead,
    GapRead,
    ProvenanceRead,
)
from app.schemas.sources import ContradictionRead

router = APIRouter(prefix="/projects", tags=["insights"])


async def _get_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"project {project_id} not found")
    return project


@router.get("/{project_id}/comparison", response_model=FieldMapRead)
async def get_field_map(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> FieldMapRead:
    await _get_project(session, project_id)
    clusters = (
        await session.execute(
            select(Cluster).where(Cluster.project_id == project_id).order_by(Cluster.created_at)
        )
    ).scalars()
    comparison = await session.scalar(
        select(Comparison)
        .where(Comparison.project_id == project_id)
        .order_by(Comparison.created_at.desc())
        .limit(1)
    )
    contradictions = (
        await session.execute(select(Contradiction).where(Contradiction.project_id == project_id))
    ).scalars()
    return FieldMapRead(
        clusters=[ClusterRead.model_validate(c) for c in clusters],
        comparison=ComparisonRead.model_validate(comparison) if comparison else None,
        contradictions=[ContradictionRead.model_validate(c) for c in contradictions],
    )


@router.get("/{project_id}/gaps", response_model=list[GapRead])
async def list_gaps(project_id: str, session: AsyncSession = Depends(get_session)) -> list[GapRead]:
    await _get_project(session, project_id)
    gaps = (
        await session.execute(
            select(Gap).where(Gap.project_id == project_id).order_by(Gap.created_at)
        )
    ).scalars()
    return [GapRead.model_validate(g) for g in gaps]


@router.get("/{project_id}/provenance", response_model=list[ProvenanceRead])
async def list_provenance(
    project_id: str,
    ref_id: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    context: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[ProvenanceRead]:
    await _get_project(session, project_id)
    where = [Provenance.project_id == project_id]
    if ref_id:
        where.append(Provenance.ref_id == ref_id)
    if source_id:
        where.append(Provenance.source_id == source_id)
    if context:
        where.append(Provenance.context == context)
    rows = (
        await session.execute(select(Provenance).where(*where).order_by(Provenance.created_at))
    ).scalars()
    return [ProvenanceRead.model_validate(p) for p in rows]
