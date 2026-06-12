"""Export plumbing: load the cited sources for an output row and pick the
exporter for a requested format. The exporters themselves are pure transforms
(`adapters/export/`); this is the only place export touches the DB.

`project_bundle` (phase 7 part D) zips a project's complete deliverable set —
latest report, latest deck, the full source list, and the audit log — into one
downloadable archive."""

from __future__ import annotations

import datetime
import io
import json
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.export.base import (
    Exporter,
    PresentationContent,
    ReportContent,
    presentation_source_ids,
)
from app.adapters.export.docx import DocxReportExporter
from app.adapters.export.markdown import ReportMarkdownExporter, SlidesMarkdownExporter
from app.adapters.export.pptx import PptxPresentationExporter
from app.core.errors import ValidationError
from app.db.models import AuditLogEntry, Presentation, Project, Report, Source
from app.services import citations

_REPORT_EXPORTERS: dict[str, Exporter[ReportContent]] = {
    "md": ReportMarkdownExporter(),
    "docx": DocxReportExporter(),
}
_PRESENTATION_EXPORTERS: dict[str, Exporter[PresentationContent]] = {
    "md": SlidesMarkdownExporter(),
    "pptx": PptxPresentationExporter(),
}


def report_exporter(format: str) -> Exporter[ReportContent]:
    exporter = _REPORT_EXPORTERS.get(format)
    if exporter is None:
        raise ValidationError(
            f"Unsupported report export format '{format}'",
            {"supported": sorted(_REPORT_EXPORTERS)},
        )
    return exporter


def presentation_exporter(format: str) -> Exporter[PresentationContent]:
    exporter = _PRESENTATION_EXPORTERS.get(format)
    if exporter is None:
        raise ValidationError(
            f"Unsupported presentation export format '{format}'",
            {"supported": sorted(_PRESENTATION_EXPORTERS)},
        )
    return exporter


async def _sources_by_id(session: AsyncSession, source_ids: list[str]) -> dict[str, Source]:
    if not source_ids:
        return {}
    rows = await session.execute(select(Source).where(Source.id.in_(source_ids)))
    return {source.id: source for source in rows.scalars()}


async def report_content(session: AsyncSession, report: Report) -> ReportContent:
    cited = citations.cited_source_ids(report.content_markdown or "")
    return ReportContent(report=report, sources=await _sources_by_id(session, cited))


async def presentation_content(
    session: AsyncSession, presentation: Presentation
) -> PresentationContent:
    cited = presentation_source_ids(presentation)
    return PresentationContent(
        presentation=presentation, sources=await _sources_by_id(session, cited)
    )


# --- project export bundle (phase 7 part D) -------------------------------------------


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, indent=2, default=str).encode("utf-8")


async def project_bundle(session: AsyncSession, project: Project) -> bytes:
    """Zip bundle: report (md), deck (md), source list (json), audit log (json),
    and a manifest. Includes whatever exists — a partially-completed project
    still exports its partial deliverables."""
    report = (
        (
            await session.execute(
                select(Report)
                .where(Report.project_id == project.id)
                .order_by(Report.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    presentation = (
        (
            await session.execute(
                select(Presentation)
                .where(Presentation.project_id == project.id)
                .order_by(Presentation.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    sources = (
        (
            await session.execute(
                select(Source).where(Source.project_id == project.id).order_by(Source.title)
            )
        )
        .scalars()
        .all()
    )
    audit_entries = (
        (
            await session.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.project_id == project.id)
                .order_by(AuditLogEntry.timestamp)
            )
        )
        .scalars()
        .all()
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest: dict[str, Any] = {
            "project_id": project.id,
            "title": project.title,
            "research_question": project.research_question,
            "status": project.status,
            "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "contents": {
                "report": report is not None,
                "presentation": presentation is not None,
                "sources": len(sources),
                "audit_entries": len(audit_entries),
            },
        }
        archive.writestr("manifest.json", _json_bytes(manifest))
        if report is not None:
            content = await report_content(session, report)
            archive.writestr(f"report-v{report.version}.md", report_exporter("md").render(content))
        if presentation is not None:
            deck = await presentation_content(session, presentation)
            archive.writestr("presentation.md", presentation_exporter("md").render(deck))
        archive.writestr(
            "sources.json",
            _json_bytes(
                [
                    {
                        "id": s.id,
                        "title": s.title,
                        "authors": s.authors,
                        "venue": s.venue,
                        "year": s.year,
                        "doi": s.doi,
                        "url": s.url,
                        "discovery_channel": s.discovery_channel,
                        "triage_status": s.triage_status,
                        "relevance_score": s.relevance_score,
                        "credibility_score": s.credibility_score,
                    }
                    for s in sources
                ]
            ),
        )
        archive.writestr(
            "audit_log.json",
            _json_bytes(
                [
                    {
                        "timestamp": e.timestamp,
                        "action_type": e.action_type,
                        "stage": e.stage,
                        "description": e.description,
                        "reasoning": e.reasoning,
                        "run_id": e.run_id,
                    }
                    for e in audit_entries
                ]
            ),
        )
    return buffer.getvalue()
