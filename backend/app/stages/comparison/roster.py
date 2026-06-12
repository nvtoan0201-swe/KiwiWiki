"""The roster: analyzed sources presented to phase-4 LLM calls by stable index.

Models reference papers by roster index (never raw ids — models invent ids);
code maps indexes back to rows and drops out-of-range references. The order is
stable across calls within a stage execution (relevance, then id).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PaperAnalysis, Source
from app.orchestrator.handler import StageContext


@dataclass(slots=True)
class AnalyzedSource:
    index: int
    source: Source
    analysis: PaperAnalysis


async def load_roster(ctx: StageContext) -> list[AnalyzedSource]:
    return await load_project_roster(ctx.session, ctx.project.id)


async def load_project_roster(session: AsyncSession, project_id: str) -> list[AnalyzedSource]:
    """Session-level loader for callers outside a stage run (e.g. report rewrite)."""
    rows = await session.execute(
        select(Source, PaperAnalysis)
        .join(PaperAnalysis, PaperAnalysis.source_id == Source.id)
        .where(Source.project_id == project_id)
        .order_by(Source.relevance_score.desc().nullslast(), Source.id)
    )
    return [
        AnalyzedSource(index=i, source=source, analysis=analysis)
        for i, (source, analysis) in enumerate(rows.all())
    ]


def render_roster(roster: list[AnalyzedSource]) -> str:
    lines = []
    for item in roster:
        source, analysis = item.source, item.analysis
        credibility = (
            f"{source.credibility_score:.2f}" if source.credibility_score is not None else "n/a"
        )
        lines.append(
            f"[{item.index}] {source.title} ({source.year or 'n.d.'}, "
            f"{source.venue or 'unknown venue'}; credibility {credibility})\n"
            f"  Claim: {analysis.core_claim or '(none)'}\n"
            f"  Method: {analysis.method or '(none)'}"
        )
    return "\n".join(lines)


def valid_indexes(indexes: list[int], roster: list[AnalyzedSource]) -> list[AnalyzedSource]:
    """Map model-cited indexes to roster entries, dropping invented ones."""
    seen: set[int] = set()
    out: list[AnalyzedSource] = []
    for i in indexes:
        if 0 <= i < len(roster) and i not in seen:
            seen.add(i)
            out.append(roster[i])
    return out
