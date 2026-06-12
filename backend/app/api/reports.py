"""Report REST endpoints (Phase 5 editing/export support, consumed by the
Phase 6 viewer).

Generated report versions are immutable: a user edit (`PATCH`) and a rewrite
(`POST .../rewrite`) both create the next version rather than mutating the row
whose `self_check_result` vouched for its content. Exports are deterministic
transforms of the stored markdown (see `adapters/export/`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.client import LLMClient
from app.core.constants import AuditActionType, Stage
from app.core.errors import NotFound
from app.db.models import Project, Report
from app.db.session import get_session
from app.events.bus import get_event_bus
from app.schemas.report import ReportPatch, ReportRead, ReportRewriteRequest
from app.services import exports
from app.services.audit import AuditService
from app.stages.report import writer
from app.stages.report.rewrite import rewrite_report

router = APIRouter(tags=["reports"])

T = TypeVar("T", bound=BaseModel)


def get_llm_json() -> writer.LLMJson:
    """The rewrite pipeline's LLM seam: same wrapper the stages use, run off
    the event loop. Tests override this dependency with a fake."""
    client = LLMClient()

    async def llm_json(
        messages: Sequence[dict[str, Any]],
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        prompt_version: str | None = None,
        note: str = "llm call",
    ) -> T:
        return await asyncio.to_thread(
            client.complete_json,
            messages,
            schema,
            system=system,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
        )

    return llm_json


async def _get_report(session: AsyncSession, report_id: str) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFound(f"Report {report_id} not found")
    return report


@router.get("/projects/{project_id}/reports", response_model=list[ReportRead])
async def list_reports(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> list[ReportRead]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"Project {project_id} not found")
    rows = await session.execute(
        select(Report).where(Report.project_id == project_id).order_by(Report.version.desc())
    )
    return [ReportRead.model_validate(r) for r in rows.scalars().all()]


@router.get("/reports/{report_id}", response_model=ReportRead)
async def get_report(report_id: str, session: AsyncSession = Depends(get_session)) -> ReportRead:
    return ReportRead.model_validate(await _get_report(session, report_id))


@router.patch("/reports/{report_id}", response_model=ReportRead)
async def patch_report(
    report_id: str, body: ReportPatch, session: AsyncSession = Depends(get_session)
) -> ReportRead:
    """Store a user edit as the next report version. The generated version it
    edits — and the self-check result that vouched for it — stay intact."""
    report = await _get_report(session, report_id)
    latest = (
        (
            await session.execute(
                select(Report.version)
                .where(Report.project_id == report.project_id)
                .order_by(Report.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    edited = Report(
        project_id=report.project_id,
        audience=report.audience,
        content_markdown=body.content_markdown,
        self_check_result={"user_edited": True, "edited_from_version": report.version},
        stopping_criterion=report.stopping_criterion,
        version=(latest or 0) + 1,
    )
    session.add(edited)
    await session.flush()
    await AuditService(session).record(
        project_id=report.project_id,
        action_type=AuditActionType.report_revised,
        description=f"Report edited by user: v{report.version} → v{edited.version}",
        reasoning=(
            "User edits are stored as a new version; generated, self-checked "
            "versions are never mutated."
        ),
        payload={"report_id": edited.id, "from_report_id": report.id},
        stage=Stage.report_writing.value,
    )
    return ReportRead.model_validate(edited)


@router.post("/reports/{report_id}/rewrite", response_model=ReportRead)
async def rewrite(
    report_id: str,
    body: ReportRewriteRequest,
    session: AsyncSession = Depends(get_session),
    llm_json: writer.LLMJson = Depends(get_llm_json),
) -> ReportRead:
    report = await _get_report(session, report_id)
    new_report = await rewrite_report(session, get_event_bus(), llm_json, report, body)
    return ReportRead.model_validate(new_report)


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = Query("md", description="docx | md"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    report = await _get_report(session, report_id)
    exporter = exports.report_exporter(format)
    content = await exports.report_content(session, report)
    data = exporter.render(content)
    filename = f"report-v{report.version}.{exporter.extension}"
    return Response(
        content=data,
        media_type=exporter.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
