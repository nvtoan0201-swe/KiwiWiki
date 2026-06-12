"""Presentation-generation stage (phase 5 part B).

A re-authoring, never the report with bullets: the through-line is chosen
first, 3–5 key messages are selected to serve it, and slides carry only the
distilled evidence those messages need (headline + evidence + optional visual
spec). Nuance moves to speaker notes. Slide evidence keeps provenance: every
point resolves to source ids or is flagged as the agent's own synthesis.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.adapters.llm.prompt_loader import render_prompt
from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    ProvenanceContext,
    Stage,
)
from app.db.models import Comparison, Presentation, Report
from app.orchestrator.handler import Advance, StageContext, StageHandler, StageResult
from app.schemas.presentation import SlideDeck, ThroughLineResult
from app.services.provenance import ProvenanceService
from app.stages.comparison import roster as roster_mod

THROUGH_LINE_PROMPT = "through_line_v1"
SLIDE_BUILD_PROMPT = "slide_build_v1"

_REPORT_EXCERPT_CHARS = 12_000


class PresentationGenerationHandler(StageHandler):
    stage = Stage.presentation_generation

    async def run(self, ctx: StageContext) -> StageResult:
        existing = (
            (
                await ctx.session.execute(
                    select(Presentation)
                    .where(Presentation.project_id == ctx.project.id)
                    .order_by(Presentation.version.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return Advance(
                summary={
                    "presentation_id": existing.id,
                    "version": existing.version,
                    "resumed": True,
                }
            )

        audience = ctx.project.audience or "expert"
        research_question = ctx.project.research_question or ctx.project.original_request
        roster = await roster_mod.load_roster(ctx)
        field_map, gaps_text, report_text = await self._context_blocks(ctx)

        await ctx.events.emit(
            "activity",
            stage=self.stage.value,
            payload={"description": "Choosing the presentation through-line"},
        )
        through: ThroughLineResult = await ctx.llm_json(
            [
                {
                    "role": "user",
                    "content": render_prompt(
                        THROUGH_LINE_PROMPT,
                        research_question=research_question,
                        audience=audience,
                        field_map=field_map,
                        gaps=gaps_text,
                        report=report_text,
                        roster=roster_mod.render_roster(roster),
                    ),
                }
            ],
            ThroughLineResult,
            prompt_version=THROUGH_LINE_PROMPT,
            note="presentation through-line",
            max_tokens=4096,
        )

        await ctx.events.emit(
            "activity",
            stage=self.stage.value,
            payload={
                "description": (f"Building slides around {len(through.key_messages)} key messages")
            },
        )
        key_messages_text = "\n".join(
            f"[{i}] {m.message}" for i, m in enumerate(through.key_messages)
        )
        deck: SlideDeck = await ctx.llm_json(
            [
                {
                    "role": "user",
                    "content": render_prompt(
                        SLIDE_BUILD_PROMPT,
                        through_line=through.through_line,
                        key_messages=key_messages_text,
                        audience=audience,
                        field_map=field_map,
                        roster=roster_mod.render_roster(roster),
                    ),
                }
            ],
            SlideDeck,
            prompt_version=SLIDE_BUILD_PROMPT,
            note="presentation slides",
            max_tokens=8192,
        )

        presentation = await self._persist(ctx, roster, through, deck)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.presentation_generated,
            description=(
                f"Presentation v{presentation.version} generated: "
                f"{len(deck.slides)} slides around {len(through.key_messages)} key messages"
            ),
            reasoning=f"Through-line: {through.through_line}",
            payload={"presentation_id": presentation.id},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )
        await ctx.events.emit(
            "output_ready",
            stage=self.stage.value,
            payload={
                "output": "presentation",
                "presentation_id": presentation.id,
                "version": presentation.version,
            },
        )
        return Advance(
            summary={
                "presentation_id": presentation.id,
                "version": presentation.version,
                "key_messages": len(through.key_messages),
                "slides": len(deck.slides),
            }
        )

    async def _context_blocks(self, ctx: StageContext) -> tuple[str, str, str]:
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
        from app.db.models import Gap

        gaps = (
            (
                await ctx.session.execute(
                    select(Gap).where(Gap.project_id == ctx.project.id).order_by(Gap.created_at)
                )
            )
            .scalars()
            .all()
        )
        gaps_text = "\n".join(f"- {g.description}" for g in gaps) or "(none recorded)"
        report = (
            (
                await ctx.session.execute(
                    select(Report)
                    .where(Report.project_id == ctx.project.id)
                    .order_by(Report.version.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        report_text = (
            (report.content_markdown or "")[:_REPORT_EXCERPT_CHARS]
            if report
            else ("(no report available)")
        )
        return field_map, gaps_text, report_text

    async def _persist(
        self,
        ctx: StageContext,
        roster: list[roster_mod.AnalyzedSource],
        through: ThroughLineResult,
        deck: SlideDeck,
    ) -> Presentation:
        latest = (
            (
                await ctx.session.execute(
                    select(Presentation.version)
                    .where(Presentation.project_id == ctx.project.id)
                    .order_by(Presentation.version.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        def resolve_ids(indexes: list[int]) -> list[str]:
            return [c.source.id for c in roster_mod.valid_indexes(indexes, roster)]

        key_messages: list[dict[str, Any]] = [
            {"message": m.message, "source_ids": resolve_ids(m.source_indexes)}
            for m in through.key_messages
        ]
        slides: list[dict[str, Any]] = []
        speaker_notes: list[dict[str, Any]] = []
        for i, slide in enumerate(deck.slides):
            slides.append(
                {
                    "headline": slide.headline,
                    "key_message_index": slide.key_message_index,
                    "evidence": [
                        {
                            "text": point.text,
                            "source_ids": resolve_ids(point.source_indexes),
                            "passage": point.passage,
                            "is_inference": point.is_inference,
                        }
                        for point in slide.evidence
                    ],
                    "visual": slide.visual.model_dump(mode="json") if slide.visual else None,
                }
            )
            speaker_notes.append({"slide": i, "notes": slide.speaker_notes or ""})

        presentation = Presentation(
            project_id=ctx.project.id,
            through_line=through.through_line,
            key_messages=key_messages,
            slides=slides,
            speaker_notes=speaker_notes,
            version=(latest or 0) + 1,
        )
        ctx.session.add(presentation)
        await ctx.session.flush()

        provenance = ProvenanceService(ctx.session)
        # The through-line and key messages are the agent's synthesis by nature.
        await provenance.attach(
            project_id=ctx.project.id,
            claim_text=through.through_line,
            context=ProvenanceContext.presentation,
            ref_id=presentation.id,
            is_inference=True,
            confidence_label=ConfidenceLabel.emerging,
        )
        for slide in deck.slides:
            for point in slide.evidence:
                cited = roster_mod.valid_indexes(point.source_indexes, roster)
                sourced = bool(cited and point.passage and point.passage.strip())
                await provenance.attach(
                    project_id=ctx.project.id,
                    claim_text=point.text,
                    context=ProvenanceContext.presentation,
                    ref_id=presentation.id,
                    source_id=cited[0].source.id if sourced else None,
                    passage=point.passage if sourced else None,
                    is_inference=point.is_inference or not sourced,
                )
        return presentation
