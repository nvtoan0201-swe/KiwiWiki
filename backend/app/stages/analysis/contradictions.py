"""Contradiction flagging (phase 3): conflicts are flagged, never resolved here.

When a newly analyzed paper's claim conflicts with an already-analyzed one,
a `contradictions` row is written (`resolved=False`, no winner). Candidate
pairs are limited by embedding similarity so the pairwise LLM cost stays
bounded; the comparison stage investigates *why* the papers disagree.
"""

from __future__ import annotations

from sqlalchemy import or_, select

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import AuditActionType
from app.db.models import Contradiction, PaperAnalysis, Source
from app.orchestrator.handler import StageContext
from app.schemas.analysis import ContradictionJudgment
from app.stages.search.saturation import cosine_similarity

PROMPT_VERSION = "contradiction_v1"


async def _candidates(ctx: StageContext, source: Source) -> list[tuple[Source, PaperAnalysis]]:
    """Already-analyzed sources near `source` in embedding space, most similar first."""
    if source.embedding is None:
        return []
    settings = get_settings()
    rows = await ctx.session.execute(
        select(Source, PaperAnalysis)
        .join(PaperAnalysis, PaperAnalysis.source_id == Source.id)
        .where(
            Source.project_id == ctx.project.id,
            Source.id != source.id,
            Source.embedding.is_not(None),
        )
    )
    scored = []
    for other, analysis in rows.all():
        if other.embedding is None or not analysis.core_claim:
            continue
        similarity = cosine_similarity(list(source.embedding), list(other.embedding))
        if similarity >= settings.contradiction_candidate_similarity:
            scored.append((similarity, other, analysis))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        (other, analysis) for _, other, analysis in scored[: settings.contradiction_max_candidates]
    ]


async def _already_flagged(ctx: StageContext, a_id: str, b_id: str) -> bool:
    row = await ctx.session.scalar(
        select(Contradiction.id).where(
            Contradiction.project_id == ctx.project.id,
            or_(
                (Contradiction.source_a_id == a_id) & (Contradiction.source_b_id == b_id),
                (Contradiction.source_a_id == b_id) & (Contradiction.source_b_id == a_id),
            ),
        )
    )
    return row is not None


async def flag_contradictions(
    ctx: StageContext, source: Source, core_claim: str
) -> list[Contradiction]:
    """Compare the new claim against nearby analyzed claims; write a row per
    genuine conflict. Returns the rows written (none is the common case)."""
    candidates = await _candidates(ctx, source)
    fresh = [
        (other, analysis)
        for other, analysis in candidates
        if not await _already_flagged(ctx, source.id, other.id)
    ]
    if not fresh:
        return []

    listing = "\n".join(
        f"[{i}] {other.title}\nClaim: {analysis.core_claim}"
        for i, (other, analysis) in enumerate(fresh)
    )
    judgment = await ctx.llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    PROMPT_VERSION,
                    new_claim=core_claim,
                    new_title=source.title,
                    candidates=listing,
                ),
            }
        ],
        ContradictionJudgment,
        prompt_version=PROMPT_VERSION,
        note=f"contradiction check: {source.title[:50]}",
    )

    written: list[Contradiction] = []
    for flag in judgment.flags:
        if not 0 <= flag.candidate_index < len(fresh):
            continue  # the model invented an index; drop it
        other, _ = fresh[flag.candidate_index]
        row = Contradiction(
            project_id=ctx.project.id,
            source_a_id=source.id,
            source_b_id=other.id,
            description=flag.description,
            resolved=False,
        )
        ctx.session.add(row)
        written.append(row)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.contradiction_flagged,
            description=(f"Contradiction flagged: '{source.title[:60]}' vs '{other.title[:60]}'"),
            reasoning=flag.description,
            payload={"source_a_id": source.id, "source_b_id": other.id},
            run_id=ctx.run.id,
            stage=ctx.stage.value,
        )
    if written:
        await ctx.session.flush()
    return written
