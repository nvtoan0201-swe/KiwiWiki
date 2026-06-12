"""Export plumbing: load the cited sources for an output row and pick the
exporter for a requested format. The exporters themselves are pure transforms
(`adapters/export/`); this is the only place export touches the DB."""

from __future__ import annotations

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
from app.db.models import Presentation, Report, Source
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
