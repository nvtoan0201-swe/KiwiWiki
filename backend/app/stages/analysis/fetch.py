"""Content acquisition for analysis (phase 3): the best available text per source.

Tries the source's origin adapters (graph-capability order) for open-access
full text; falls back to the stored abstract + metadata. Access controls are
respected by construction — adapters only ever return openly retrievable
content, and there is no paywall/login/CAPTCHA path here. The outcome
(`full_text` vs `abstract_only`) is recorded on the source's `raw_metadata` so
reduced-depth analysis is visible downstream.

Each acquisition charges `papers_read` by 1 — once per analyzed paper.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import BudgetCategory
from app.core.errors import AppError
from app.db.models import Source
from app.orchestrator.handler import StageContext

TEXT_FULL = "full_text"
TEXT_ABSTRACT_ONLY = "abstract_only"
TEXT_METADATA_ONLY = "metadata_only"

# Same preference order the source router uses for graph operations.
_FETCH_PREFERENCE = ["openalex", "semantic_scholar", "crossref", "arxiv", "fake"]


@dataclass(slots=True)
class FetchedText:
    text: str
    text_available: str  # full_text | abstract_only | metadata_only


async def fetch_text(ctx: StageContext, source: Source, adapters_by_name: dict) -> FetchedText:
    """Charge one `papers_read`, then obtain the richest open text available."""
    await ctx.budget.charge(BudgetCategory.papers_read, 1, note=f"read: {source.title[:60]}")

    origins = dict((source.raw_metadata or {}).get("origins") or {})
    full_text: str | None = None
    abstract = source.abstract
    candidates = sorted(
        (name for name in origins if name in adapters_by_name),
        key=lambda n: (
            _FETCH_PREFERENCE.index(n) if n in _FETCH_PREFERENCE else len(_FETCH_PREFERENCE)
        ),
    )
    for name in candidates:
        try:
            record = await adapters_by_name[name].fetch(origins[name])
        except AppError:
            continue  # provider down or record gone; try the next origin
        if record.full_text:
            full_text = record.full_text
            break
        if record.abstract and not abstract:
            abstract = record.abstract

    if full_text:
        availability = TEXT_FULL
        text = full_text
    elif abstract:
        availability = TEXT_ABSTRACT_ONLY
        text = abstract
    else:
        availability = TEXT_METADATA_ONLY
        text = f"(no text available; metadata only)\nTitle: {source.title}"

    metadata = dict(source.raw_metadata or {})
    metadata["text_available"] = availability
    source.raw_metadata = metadata
    if ctx.trace is not None:
        ctx.trace.record_fetch(
            stage=ctx.stage_execution.stage,
            source_title=source.title,
            availability=availability,
        )
    return FetchedText(text=text, text_available=availability)
