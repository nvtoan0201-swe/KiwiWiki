"""Consensus vs. contested (phase 4 A.4–A.5).

Findings are partitioned explicitly. Each contested point — seeded from the
flagged contradictions plus newly detected disagreements — gets a *why*
investigation before any conclusion, ending in a conditional resolution or an
honest "unresolved". Consensus is weighted by credibility: agreement among
weak studies is capped below `well_established` in code, so the label cannot
be talked up by confident prose.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import AuditActionType, ConfidenceLabel, ProvenanceContext
from app.db.models import Comparison, Contradiction, PaperAnalysis, Source
from app.orchestrator.handler import StageContext
from app.schemas.comparison import ConsensusPartition, ContestedPoint, Investigation
from app.services.provenance import ProvenanceService
from app.stages.comparison.roster import AnalyzedSource, render_roster, valid_indexes

CONSENSUS_PROMPT = "consensus_v1"
INVESTIGATE_PROMPT = "contradiction_investigate_v1"


def _render_open_contradictions(rows: list[Contradiction]) -> str:
    if not rows:
        return "(none)"
    return "\n".join(f"[{i}] {row.description}" for i, row in enumerate(rows))


def capped_confidence(
    label: ConfidenceLabel, cited: list[AnalyzedSource]
) -> tuple[ConfidenceLabel, str | None]:
    """Cap `well_established` at `emerging` when the supporting evidence is weak."""
    scores = [c.source.credibility_score for c in cited if c.source.credibility_score is not None]
    if not scores:
        return label, None
    mean = sum(scores) / len(scores)
    floor = get_settings().consensus_credibility_floor
    if mean < floor and label is ConfidenceLabel.well_established:
        return (
            ConfidenceLabel.emerging,
            f"Downgraded from well_established: mean source credibility {mean:.2f} < {floor}.",
        )
    return label, None


async def partition_consensus(
    ctx: StageContext,
    research_question: str,
    roster: list[AnalyzedSource],
    comparison: Comparison,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Produce (consensus_points, contested_points) and run the contested-point
    investigations, updating the `contradictions` rows as it goes."""
    open_rows = list(
        (
            await ctx.session.execute(
                select(Contradiction)
                .where(
                    Contradiction.project_id == ctx.project.id,
                    Contradiction.resolved.is_(False),
                )
                .order_by(Contradiction.created_at)
            )
        ).scalars()
    )

    field_map = json.dumps(
        {"dimensions": comparison.dimensions, "matrix": comparison.matrix}, indent=2, default=str
    )
    partition = await ctx.llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    CONSENSUS_PROMPT,
                    research_question=research_question,
                    field_map=field_map,
                    roster=render_roster(roster),
                    contradictions=_render_open_contradictions(open_rows),
                ),
            }
        ],
        ConsensusPartition,
        prompt_version=CONSENSUS_PROMPT,
        note="consensus/contested partition",
        max_tokens=8192,
    )

    provenance = ProvenanceService(ctx.session)
    consensus_out: list[dict[str, Any]] = []
    for point in partition.consensus_points:
        cited = valid_indexes(point.source_indexes, roster)
        label, downgrade_note = capped_confidence(point.confidence_label, cited)
        sourced = bool(cited and point.passage)
        row = await provenance.attach(
            project_id=ctx.project.id,
            claim_text=point.statement,
            context=ProvenanceContext.comparison,
            ref_id=comparison.id,
            source_id=cited[0].source.id if sourced else None,
            passage=point.passage if sourced else None,
            is_inference=not sourced,
            confidence_label=label,
        )
        consensus_out.append(
            {
                "statement": point.statement,
                "source_ids": [c.source.id for c in cited],
                "confidence_label": label.value,
                "credibility_note": downgrade_note,
                "provenance_id": row.id,
            }
        )

    contested_out: list[dict[str, Any]] = []
    for contested in partition.contested_points:
        cited = valid_indexes(contested.source_indexes, roster)
        contradiction = await _matching_contradiction(ctx, contested, cited, open_rows)
        investigation = await _investigate(ctx, contradiction) if contradiction else None
        row = await provenance.attach(
            project_id=ctx.project.id,
            claim_text=contested.statement,
            context=ProvenanceContext.comparison,
            ref_id=comparison.id,
            is_inference=True,  # the *disagreement* is the agent's reading of the set
            confidence_label=ConfidenceLabel.contested,
        )
        contested_out.append(
            {
                "statement": contested.statement,
                "source_ids": [c.source.id for c in cited],
                "contradiction_id": contradiction.id if contradiction else None,
                "investigation": investigation.why if investigation else None,
                "resolution_type": investigation.resolution_type if investigation else None,
                "resolution": investigation.resolution if investigation else None,
                "confidence_label": ConfidenceLabel.contested.value,
                "provenance_id": row.id,
            }
        )
    return consensus_out, contested_out


async def _matching_contradiction(
    ctx: StageContext,
    point: ContestedPoint,
    cited: list[AnalyzedSource],
    open_rows: list[Contradiction],
) -> Contradiction | None:
    """The contradiction row behind a contested point: an existing flagged one,
    or a new row for a disagreement first detected here (two papers required)."""
    if point.contradiction_index is not None and 0 <= point.contradiction_index < len(open_rows):
        return open_rows[point.contradiction_index]
    if len(cited) < 2:
        return None
    row = Contradiction(
        project_id=ctx.project.id,
        source_a_id=cited[0].source.id,
        source_b_id=cited[1].source.id,
        description=point.statement,
        resolved=False,
    )
    ctx.session.add(row)
    await ctx.session.flush()
    await ctx.audit.record(
        project_id=ctx.project.id,
        action_type=AuditActionType.contradiction_flagged,
        description=f"Disagreement detected during comparison: {point.statement[:120]}",
        reasoning="Surfaced while partitioning consensus vs. contested points.",
        payload={"source_a_id": row.source_a_id, "source_b_id": row.source_b_id},
        run_id=ctx.run.id,
        stage=ctx.stage.value,
    )
    return row


async def _investigate(ctx: StageContext, contradiction: Contradiction) -> Investigation:
    """Why do the two papers disagree? Conditional resolution or honest unresolved."""

    async def side(source_id: str) -> tuple[Source, PaperAnalysis | None]:
        source = await ctx.session.get(Source, source_id)
        if source is None:  # FK guarantees existence; guard for type-safety
            raise ValueError(f"Contradiction references missing source {source_id}")
        analysis = (
            await ctx.session.execute(
                select(PaperAnalysis).where(PaperAnalysis.source_id == source_id).limit(1)
            )
        ).scalar_one_or_none()
        return source, analysis

    source_a, analysis_a = await side(contradiction.source_a_id)
    source_b, analysis_b = await side(contradiction.source_b_id)

    def fields(source: Source, analysis: PaperAnalysis | None) -> dict[str, Any]:
        return {
            "title": source.title,
            "claim": (analysis.core_claim if analysis else None) or "(not analyzed)",
            "method": (analysis.method if analysis else None) or "(unknown)",
            "datasets": (
                json.dumps(analysis.datasets) if analysis and analysis.datasets else "(unknown)"
            ),
            "credibility": (
                f"{source.credibility_score:.2f}"
                if source.credibility_score is not None
                else "unknown"
            ),
        }

    a, b = fields(source_a, analysis_a), fields(source_b, analysis_b)
    investigation = await ctx.llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    INVESTIGATE_PROMPT,
                    description=contradiction.description,
                    title_a=a["title"],
                    claim_a=a["claim"],
                    method_a=a["method"],
                    datasets_a=a["datasets"],
                    credibility_a=a["credibility"],
                    title_b=b["title"],
                    claim_b=b["claim"],
                    method_b=b["method"],
                    datasets_b=b["datasets"],
                    credibility_b=b["credibility"],
                ),
            }
        ],
        Investigation,
        prompt_version=INVESTIGATE_PROMPT,
        note="contradiction investigation",
    )

    contradiction.investigation = investigation.why
    contradiction.resolution = investigation.resolution
    contradiction.resolved = investigation.resolution_type == "conditional"
    await ctx.session.flush()
    await ctx.audit.record(
        project_id=ctx.project.id,
        action_type=AuditActionType.contradiction_investigated,
        description=(
            f"Contradiction investigated → {investigation.resolution_type}: "
            f"'{source_a.title[:50]}' vs '{source_b.title[:50]}'"
        ),
        reasoning=investigation.why,
        payload={
            "contradiction_id": contradiction.id,
            "resolution": investigation.resolution,
            "resolution_type": investigation.resolution_type,
        },
        run_id=ctx.run.id,
        stage=ctx.stage.value,
    )
    return investigation
