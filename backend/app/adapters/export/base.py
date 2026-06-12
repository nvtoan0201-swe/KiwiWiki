"""Exporter contract and the shared export content models.

Exporters are pure transforms over the *stored* output rows (plus the cited
source rows for the references list) — no LLM, no DB access — so re-export
after edits is deterministic. Citation markers in the canonical markdown embed
full source ids (see `services/citations.py`); exporters renumber them by
first appearance and build the references list from the same mapping, which is
what keeps inline markers and the references section consistent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from app.db.models import Presentation, Report, Source

ContentT = TypeVar("ContentT")


@dataclass(slots=True)
class ReportContent:
    """A report row plus the source rows its markdown cites (id → Source)."""

    report: Report
    sources: dict[str, Source] = field(default_factory=dict)


@dataclass(slots=True)
class PresentationContent:
    """A presentation row plus the source rows its slides/messages cite."""

    presentation: Presentation
    sources: dict[str, Source] = field(default_factory=dict)


class Exporter(ABC, Generic[ContentT]):
    """Renders a stored output model into a downloadable byte stream."""

    #: file extension this exporter produces, e.g. "docx".
    extension: str = ""
    #: MIME type for the HTTP response.
    media_type: str = "application/octet-stream"

    @abstractmethod
    def render(self, content: ContentT) -> bytes:
        raise NotImplementedError


def presentation_source_ids(presentation: Presentation) -> list[str]:
    """Source ids cited anywhere in the stored deck, in order of first
    appearance (key messages first, then slide evidence), deduplicated.
    The numbering every presentation exporter shares."""
    seen: set[str] = set()
    ordered: list[str] = []

    def take(ids: Any) -> None:
        for source_id in ids or []:
            if isinstance(source_id, str) and source_id not in seen:
                seen.add(source_id)
                ordered.append(source_id)

    for message in presentation.key_messages or []:
        take(message.get("source_ids"))
    for slide in presentation.slides or []:
        for point in slide.get("evidence") or []:
            take(point.get("source_ids"))
    return ordered


def format_authors(authors: Any) -> str:
    if isinstance(authors, list) and authors:
        return ", ".join(str(a) for a in authors)
    return "Unknown authors"


def format_reference(number: int, source_id: str, source: Source | None) -> str:
    """One numbered references-list entry. A missing source row still renders
    (deterministically) so an export never fails on a dangling citation."""
    if source is None:
        return f"[{number}] (source {source_id} not on record)"
    parts = [f"[{number}] {format_authors(source.authors)} ({source.year or 'n.d.'})."]
    parts.append(f"{source.title}.")
    if source.venue:
        parts.append(f"{source.venue}.")
    if source.doi:
        parts.append(f"https://doi.org/{source.doi}")
    elif source.url:
        parts.append(source.url)
    return " ".join(parts)
