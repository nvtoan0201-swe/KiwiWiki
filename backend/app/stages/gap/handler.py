"""Gap & future-directions stage (phase 4 part B).

Gaps are synthesized from the comparison map — clusters, matrix, consensus and
contested points — never from imagination: every gap carries grounded
supporting evidence (provenance to the papers whose boundaries reveal it, or
an explicit inference flag). Future-direction suggestions are the agent's own
synthesis and are stored labeled `speculative` so the report renders them
honestly.

Resumable: if the project already has gap rows, the stage advances without
re-synthesizing.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from app.adapters.llm.prompt_loader import render_prompt
from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    ProvenanceContext,
    Stage,
)
from app.core.errors import BudgetExceeded
from app.db.models import Comparison, Gap
from app.orchestrator.handler import Advance, StageContext, StageHandler, StageResult
from app.schemas.gap import GapSynthesis
from app.services.provenance import ProvenanceService
from app.stages.comparison import roster as roster_mod

PROMPT_VERSION = "gap_synthesis_v1"


class GapAnalysisHandler(StageHandler):
    stage = Stage.gap_analysis

    async def run(self, ctx: StageContext) -> StageResult:
        existing = (
            await ctx.session.scalar(
                select(func.count()).select_from(Gap).where(Gap.project_id == ctx.project.id)
            )
        ) or 0
        if existing:
            return Advance(summary={"gaps": existing, "resumed": True})

        research_question = ctx.project.research_question or ctx.project.original_request
        roster = await roster_mod.load_roster(ctx)
        comparison = (
            await ctx.session.execute(
                select(Comparison)
                .where(Comparison.project_id == ctx.project.id)
                .order_by(Comparison.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        field_map = json.dumps(
            {
                "dimensions": comparison.dimensions if comparison else None,
                "matrix": comparison.matrix if comparison else None,
                "consensus_points": comparison.consensus_points if comparison else None,
                "contested_points": comparison.contested_points if comparison else None,
            },
            indent=2,
            default=str,
        )

        await ctx.events.emit(
            "activity",
            stage=self.stage.value,
            payload={"description": "Synthesizing gaps from the field map"},
        )
        try:
            synthesis = await ctx.llm_json(
                [
                    {
                        "role": "user",
                        "content": render_prompt(
                            PROMPT_VERSION,
                            research_question=research_question,
                            field_map=field_map,
                            roster=roster_mod.render_roster(roster),
                        ),
                    }
                ],
                GapSynthesis,
                prompt_version=PROMPT_VERSION,
                note="gap synthesis",
                max_tokens=8192,
            )
            summary = await self._persist(ctx, roster, synthesis)
        except BudgetExceeded:
            ctx.stage_execution.summary = {"partial": True}
            raise
        return Advance(summary=summary)

    async def _persist(
        self,
        ctx: StageContext,
        roster: list[roster_mod.AnalyzedSource],
        synthesis: GapSynthesis,
    ) -> dict[str, Any]:
        provenance = ProvenanceService(ctx.session)
        by_importance: dict[str, int] = {}

        for item in synthesis.gaps:
            cited = roster_mod.valid_indexes(item.source_indexes, roster)
            gap = Gap(
                project_id=ctx.project.id,
                description=item.description,
                supporting_evidence={
                    "evidence": item.evidence,
                    "source_ids": [c.source.id for c in cited],
                    "gap_type": item.gap_type,
                },
                importance=item.importance.value,
                confidence_label=item.confidence_label.value,
            )
            ctx.session.add(gap)
            await ctx.session.flush()
            sourced = bool(cited and item.passage)
            await provenance.attach(
                project_id=ctx.project.id,
                claim_text=item.description,
                context=ProvenanceContext.gap,
                ref_id=gap.id,
                source_id=cited[0].source.id if sourced else None,
                passage=item.passage if sourced else None,
                is_inference=not sourced,
                confidence_label=item.confidence_label,
            )
            by_importance[item.importance.value] = by_importance.get(item.importance.value, 0) + 1
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.gap_identified,
                description=f"Gap ({item.gap_type}, {item.importance.value}): "
                f"{item.description[:120]}",
                reasoning=item.evidence,
                payload={"gap_id": gap.id, "source_ids": [c.source.id for c in cited]},
                run_id=ctx.run.id,
                stage=self.stage.value,
            )

        for direction in synthesis.future_directions:
            gap = Gap(
                project_id=ctx.project.id,
                description=direction.description,
                supporting_evidence={
                    "type": "future_direction",
                    "rationale": direction.rationale,
                },
                importance=None,
                confidence_label=ConfidenceLabel.speculative.value,
            )
            ctx.session.add(gap)
            await ctx.session.flush()
            await provenance.attach(
                project_id=ctx.project.id,
                claim_text=direction.description,
                context=ProvenanceContext.gap,
                ref_id=gap.id,
                is_inference=True,
                confidence_label=ConfidenceLabel.speculative,
            )
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.gap_identified,
                description=f"Future direction (speculative): {direction.description[:120]}",
                reasoning=direction.rationale,
                payload={"gap_id": gap.id},
                run_id=ctx.run.id,
                stage=self.stage.value,
            )

        return {
            "gaps": len(synthesis.gaps),
            "future_directions": len(synthesis.future_directions),
            "by_importance": by_importance,
        }
