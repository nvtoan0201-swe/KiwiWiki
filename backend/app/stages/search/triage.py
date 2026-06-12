"""Relevance triage (phase 2C step 3): batch-score new hits against the
research question, assign a TriageStatus by configurable thresholds, persist
score + reason, audit each decision."""

from __future__ import annotations

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import AuditActionType, TriageStatus
from app.db.models import Source
from app.orchestrator.handler import StageContext
from app.schemas.search import RelevanceBatch

# v2 fences the paper list as data-only (phase 7 input-safety hardening).
PROMPT_VERSION = "relevance_triage_v2"
_BATCH_SIZE = 20

TRIAGED_IN = {TriageStatus.deep_read.value, TriageStatus.skimmed.value}


def status_for_score(score: float) -> TriageStatus:
    settings = get_settings()
    if score >= settings.relevance_deep_read_threshold:
        return TriageStatus.deep_read
    if score >= settings.relevance_skim_threshold:
        return TriageStatus.skimmed
    if score >= settings.relevance_set_aside_threshold:
        return TriageStatus.set_aside
    return TriageStatus.excluded


def _batch_prompt(research_question: str, batch: list[Source]) -> str:
    papers = "\n\n".join(
        f"[{i}] {source.title}\nAbstract: {source.abstract or '(no abstract available)'}"
        for i, source in enumerate(batch)
    )
    return render_prompt(PROMPT_VERSION, research_question=research_question, papers=papers)


async def triage_sources(
    ctx: StageContext, sources: list[Source], research_question: str
) -> dict[str, int]:
    """Score and triage every not-yet-triaged source. Already-scored sources are
    skipped (cache by source id — safe on re-entry). Returns counts by status."""
    counts: dict[str, int] = {status.value: 0 for status in TriageStatus}
    pending = [s for s in sources if s.relevance_score is None]
    for already in (s for s in sources if s.relevance_score is not None):
        if already.triage_status:
            counts[already.triage_status] += 1

    for start in range(0, len(pending), _BATCH_SIZE):
        batch = pending[start : start + _BATCH_SIZE]
        result = await ctx.llm_json(
            [{"role": "user", "content": _batch_prompt(research_question, batch)}],
            RelevanceBatch,
            prompt_version=PROMPT_VERSION,
            note=f"relevance triage ({len(batch)} papers)",
        )
        by_index = {score.index: score for score in result.scores}
        for i, source in enumerate(batch):
            score = by_index.get(i)
            if score is None:
                # The model skipped one; be conservative, keep it for a human eye.
                source.relevance_score = 0.0
                source.triage_status = TriageStatus.set_aside.value
                source.triage_reason = "Model did not score this paper; set aside."
            else:
                status = status_for_score(score.relevance)
                source.relevance_score = score.relevance
                source.triage_status = status.value
                source.triage_reason = score.reason
            counts[source.triage_status] += 1
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.paper_triaged,
                description=f"Triaged '{source.title[:80]}' → {source.triage_status}",
                reasoning=source.triage_reason,
                payload={"source_id": source.id, "relevance": source.relevance_score},
                run_id=ctx.run.id,
                stage=ctx.stage.value,
                emit_activity=False,
            )
        await ctx.session.flush()
    return counts
