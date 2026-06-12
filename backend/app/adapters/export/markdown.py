"""Markdown exporters: the portable report `.md` and the slides `.md` fallback.

The report's stored markdown is canonical; export rewrites the `[^src:id]`
markers to `[n]` numbered by first appearance and appends a references section
built from the same numbering, so inline citations and the list always agree.
Confidence tags are already plain markdown and pass through untouched.
"""

from __future__ import annotations

from typing import Any

from app.adapters.export.base import (
    Exporter,
    PresentationContent,
    ReportContent,
    format_reference,
    presentation_source_ids,
)
from app.services import citations

_MD_MEDIA_TYPE = "text/markdown; charset=utf-8"


def references_lines(numbering: dict[str, int], sources: dict[str, Any]) -> list[str]:
    if not numbering:
        return []
    lines = ["## References", ""]
    for source_id, number in sorted(numbering.items(), key=lambda kv: kv[1]):
        lines.append(format_reference(number, source_id, sources.get(source_id)))
    lines.append("")
    return lines


class ReportMarkdownExporter(Exporter[ReportContent]):
    extension = "md"
    media_type = _MD_MEDIA_TYPE

    def render(self, content: ReportContent) -> bytes:
        markdown = content.report.content_markdown or ""
        numbered, numbering = citations.number_citations(markdown)
        lines = [numbered.rstrip(), ""]
        lines.extend(references_lines(numbering, content.sources))
        return "\n".join(lines).rstrip("\n").encode("utf-8") + b"\n"


def _refs(source_ids: Any, numbering: dict[str, int]) -> str:
    markers = "".join(
        f"[{numbering[s]}]" for s in (source_ids or []) if isinstance(s, str) and s in numbering
    )
    return f" {markers}" if markers else ""


def visual_lines(visual: dict[str, Any]) -> list[str]:
    """A VisualSpec as markdown: tables for tabular types, bullets otherwise."""
    lines: list[str] = []
    if visual.get("title"):
        lines.append(f"**{visual['title']}**")
        lines.append("")
    if visual.get("type") == "bullet_set":
        lines.extend(f"- {point}" for point in visual.get("points") or [])
        lines.append("")
        return lines
    columns = [str(c) for c in visual.get("columns") or []]
    rows = [[str(cell) for cell in row] for row in visual.get("rows") or []]
    if not columns:
        defaults = {"timeline": ["When", "What"], "trend": ["x", "y"]}
        width = max((len(r) for r in rows), default=2)
        columns = (defaults.get(str(visual.get("type"))) or [])[:width]
        columns += [f"col{i + 1}" for i in range(len(columns), width)]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + " --- |" * len(columns))
    for row in rows:
        padded = (row + [""] * len(columns))[: len(columns)]
        lines.append("| " + " | ".join(padded) + " |")
    lines.append("")
    return lines


class SlidesMarkdownExporter(Exporter[PresentationContent]):
    extension = "md"
    media_type = _MD_MEDIA_TYPE

    def render(self, content: PresentationContent) -> bytes:
        deck = content.presentation
        numbering = {s: i + 1 for i, s in enumerate(presentation_source_ids(deck))}
        notes_by_slide = {note.get("slide"): note.get("notes") for note in deck.speaker_notes or []}

        lines: list[str] = ["# Presentation", ""]
        if deck.through_line:
            lines.extend([f"**Through-line:** {deck.through_line}", ""])
        if deck.key_messages:
            lines.extend(["## Key messages", ""])
            for message in deck.key_messages:
                lines.append(
                    f"- {message.get('message', '')}{_refs(message.get('source_ids'), numbering)}"
                )
            lines.append("")

        for i, slide in enumerate(deck.slides or []):
            lines.extend([f"## Slide {i + 1}: {slide.get('headline', '')}", ""])
            for point in slide.get("evidence") or []:
                inference = " *(inference)*" if point.get("is_inference") else ""
                lines.append(
                    f"- {point.get('text', '')}"
                    f"{_refs(point.get('source_ids'), numbering)}{inference}"
                )
            if slide.get("evidence"):
                lines.append("")
            if slide.get("visual"):
                lines.extend(visual_lines(slide["visual"]))
            notes = notes_by_slide.get(i)
            if notes:
                lines.extend([f"> Speaker notes: {notes}", ""])

        lines.extend(references_lines(numbering, content.sources))
        return "\n".join(lines).rstrip("\n").encode("utf-8") + b"\n"
