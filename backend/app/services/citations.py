"""Inline citation markers: the deterministic markdown ↔ sources mapping.

A claim cites source `abc-123` as `[^src:abc-123]` in the canonical markdown.
The marker embeds the full source id, so the viewer can resolve it to a
provenance trace and exporters can rebuild a numbered references list without
any side table — re-export after edits stays deterministic.

Confidence labels are rendered as `*(confidence: …)*` so hedged vs. firm
claims survive every transform (overview invariant 6).
"""

from __future__ import annotations

import re

from app.core.constants import ConfidenceLabel

_MARKER_RE = re.compile(r"\[\^src:([0-9a-fA-F-]{8,36})\]")
_CONFIDENCE_RE = re.compile(r"\*\(confidence: ([a-z ]+)((?:; inference)?)\)\*")

_LABEL_TEXT = {
    ConfidenceLabel.well_established: "well established",
    ConfidenceLabel.emerging: "emerging",
    ConfidenceLabel.contested: "contested",
    ConfidenceLabel.speculative: "speculative",
}
_TEXT_LABEL = {text: label for label, text in _LABEL_TEXT.items()}


def citation_marker(source_id: str) -> str:
    return f"[^src:{source_id}]"


def citation_markers(source_ids: list[str]) -> str:
    return "".join(citation_marker(s) for s in source_ids)


def confidence_tag(label: ConfidenceLabel, *, is_inference: bool = False) -> str:
    suffix = "; inference" if is_inference else ""
    return f"*(confidence: {_LABEL_TEXT[label]}{suffix})*"


def parse_confidence_text(text: str) -> ConfidenceLabel | None:
    return _TEXT_LABEL.get(text)


def cited_source_ids(markdown: str) -> list[str]:
    """Source ids cited in `markdown`, in order of first appearance, deduplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _MARKER_RE.finditer(markdown):
        source_id = match.group(1)
        if source_id not in seen:
            seen.add(source_id)
            out.append(source_id)
    return out


def number_citations(markdown: str) -> tuple[str, dict[str, int]]:
    """Rewrite `[^src:id]` markers to `[n]` numbered by first appearance.

    Returns the rewritten text and the id → number mapping (the references
    list must be built from the same mapping to stay consistent).
    """
    numbering = {source_id: i + 1 for i, source_id in enumerate(cited_source_ids(markdown))}

    def _sub(match: re.Match[str]) -> str:
        return f"[{numbering[match.group(1)]}]"

    return _MARKER_RE.sub(_sub, markdown), numbering


def strip_markers(markdown: str) -> str:
    """Remove citation markers entirely (plain-text contexts)."""
    return _MARKER_RE.sub("", markdown)
