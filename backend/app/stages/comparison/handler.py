"""Comparative analysis stage (phase 4 part A): per-paper records → field map.

Steps, each checkpointed onto the project's `comparisons` row so a killed run
resumes at the step boundary instead of redoing finished work:
1. thin/lopsided evidence check (loop back rather than map a field that isn't
   there);
2. clustering (data-driven count; LLM names/characterizes);
3. comparison dimensions (derived from actual contestation, generic ones
   rejected);
4. matrix (clusters × dimensions, each non-trivial cell source-grounded with
   provenance);
5. consensus vs. contested, with why-investigations on every contested point.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    ProvenanceContext,
    Stage,
    TriageStatus,
)
from app.core.errors import BudgetExceeded
from app.db.models import Cluster, Comparison, Contradiction, Source
from app.orchestrator.handler import Advance, LoopBack, StageContext, StageHandler, StageResult
from app.schemas.comparison import MatrixRow
from app.services.provenance import ProvenanceService
from app.stages.comparison import roster as roster_mod
from app.stages.comparison.clustering import cluster_sources
from app.stages.comparison.consensus import partition_consensus
from app.stages.comparison.dimensions import derive_dimensions

MATRIX_PROMPT = "matrix_v1"


class ComparativeAnalysisHandler(StageHandler):
    stage = Stage.comparative_analysis

    async def run(self, ctx: StageContext) -> StageResult:
        research_question = ctx.project.research_question or ctx.project.original_request
        roster = await roster_mod.load_roster(ctx)

        thin = await self._thin_evidence_loop_back(ctx, roster)
        if thin is not None:
            return thin

        comparison = await self._get_or_create_comparison(ctx)
        try:
            clusters = await self._ensure_clusters(ctx, research_question, roster)
            lopsided = await self._lopsided_loop_back(ctx, clusters)
            if lopsided is not None:
                return lopsided

            contradictions = list(
                (
                    await ctx.session.execute(
                        select(Contradiction)
                        .where(Contradiction.project_id == ctx.project.id)
                        .order_by(Contradiction.created_at)
                    )
                ).scalars()
            )

            if comparison.dimensions is None:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": "Deriving comparison dimensions"},
                )
                comparison.dimensions = await derive_dimensions(
                    ctx, research_question, roster, contradictions
                )
                await ctx.checkpoint({"step": "dimensions", "count": len(comparison.dimensions)})

            if comparison.matrix is None:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": "Building the comparison matrix"},
                )
                comparison.matrix = await self._build_matrix(
                    ctx, research_question, roster, clusters, comparison
                )
                await ctx.checkpoint({"step": "matrix"})

            if comparison.consensus_points is None:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": "Partitioning consensus vs. contested"},
                )
                consensus, contested = await partition_consensus(
                    ctx, research_question, roster, comparison
                )
                comparison.consensus_points = consensus
                comparison.contested_points = contested
                await ctx.checkpoint({"step": "consensus"})
        except BudgetExceeded:
            ctx.stage_execution.summary = {
                **(ctx.stage_execution.summary or {}),
                "partial": True,
            }
            raise

        summary = await self._summary(ctx, comparison)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.comparison_updated,
            description=(
                f"Field map built: {summary['clusters']} clusters × "
                f"{summary['dimensions']} dimensions; {summary['consensus_points']} consensus, "
                f"{summary['contested_points']} contested"
            ),
            reasoning="Clustering, matrix, and consensus/contested partition completed.",
            payload={"comparison_id": comparison.id},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )
        return Advance(summary=summary)

    # --- evidence sufficiency ---------------------------------------------------------

    async def _thin_evidence_loop_back(
        self, ctx: StageContext, roster: list[roster_mod.AnalyzedSource]
    ) -> LoopBack | None:
        minimum = get_settings().comparison_min_analyzed_sources
        if len(roster) >= minimum:
            return None
        reason = (
            f"evidence base too thin to map the field: {len(roster)} analyzed "
            f"paper(s), need at least {minimum}"
        )
        return await self._strengthen_evidence(ctx, reason)

    async def _lopsided_loop_back(
        self, ctx: StageContext, clusters: list[Cluster]
    ) -> LoopBack | None:
        """A single-paper cluster resting on one weak study cannot anchor a map."""
        weak_floor = get_settings().weak_cluster_credibility
        for cluster in clusters:
            members = list(
                (
                    await ctx.session.execute(select(Source).where(Source.cluster_id == cluster.id))
                ).scalars()
            )
            if len(members) == 1 and (members[0].credibility_score or 0.0) < weak_floor:
                score = members[0].credibility_score
                reason = (
                    f"evidence is lopsided: cluster '{cluster.label}' rests on a single "
                    f"weak paper (credibility {score if score is not None else 'unscored'})"
                )
                return await self._strengthen_evidence(ctx, reason)
        return None

    async def _strengthen_evidence(self, ctx: StageContext, reason: str) -> LoopBack:
        """Prefer promoting set-aside papers (cheap, already found); fall back to
        a fresh search. The engine's loop-back cap bounds both."""
        set_aside = list(
            (
                await ctx.session.execute(
                    select(Source)
                    .where(
                        Source.project_id == ctx.project.id,
                        Source.triage_status == TriageStatus.set_aside.value,
                    )
                    .order_by(Source.relevance_score.desc().nullslast())
                    .limit(5)
                )
            ).scalars()
        )
        if set_aside:
            return LoopBack(
                to_stage=Stage.paper_analysis,
                reason=reason,
                context={"promote_source_ids": [s.id for s in set_aside]},
            )
        research_question = ctx.project.research_question or ctx.project.original_request
        return LoopBack(
            to_stage=Stage.literature_search,
            reason=reason,
            context={"queries": [research_question]},
        )

    # --- steps ----------------------------------------------------------------------

    async def _get_or_create_comparison(self, ctx: StageContext) -> Comparison:
        existing = (
            await ctx.session.execute(
                select(Comparison)
                .where(Comparison.project_id == ctx.project.id)
                .order_by(Comparison.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        comparison = Comparison(project_id=ctx.project.id)
        ctx.session.add(comparison)
        await ctx.session.flush()
        return comparison

    async def _ensure_clusters(
        self,
        ctx: StageContext,
        research_question: str,
        roster: list[roster_mod.AnalyzedSource],
    ) -> list[Cluster]:
        """Reuse clusters when every analyzed source is already assigned;
        otherwise rebuild (new analyses arrived since the last attempt)."""
        existing = list(
            (
                await ctx.session.execute(
                    select(Cluster).where(Cluster.project_id == ctx.project.id)
                )
            ).scalars()
        )
        if existing and all(item.source.cluster_id is not None for item in roster):
            return existing
        await ctx.events.emit(
            "activity",
            stage=self.stage.value,
            payload={"description": f"Clustering {len(roster)} analyzed papers"},
        )
        clusters = await cluster_sources(ctx, research_question, roster)
        await ctx.checkpoint({"step": "clustering", "clusters": len(clusters)})
        return clusters

    async def _build_matrix(
        self,
        ctx: StageContext,
        research_question: str,
        roster: list[roster_mod.AnalyzedSource],
        clusters: list[Cluster],
        comparison: Comparison,
    ) -> dict[str, Any]:
        dimensions: list[dict[str, Any]] = comparison.dimensions or []
        provenance = ProvenanceService(ctx.session)
        by_source_id = {item.source.id: item for item in roster}
        cells: list[dict[str, Any]] = []

        dimensions_text = "\n".join(
            f"[{i}] {d['name']}: {d['description']}" for i, d in enumerate(dimensions)
        )
        for cluster in clusters:
            members = [
                item
                for item in roster
                if item.source.cluster_id == cluster.id and item.source.id in by_source_id
            ]
            if not members or not dimensions:
                continue
            members_text = "\n".join(
                f"[{m.index}] {m.source.title}\n  Claim: {m.analysis.core_claim or '(none)'}\n"
                f"  Method: {m.analysis.method or '(none)'}\n"
                f"  Findings: {json.dumps((m.analysis.results or {}).get('findings', []))[:600]}"
                for m in members
            )
            row = await ctx.llm_json(
                [
                    {
                        "role": "user",
                        "content": render_prompt(
                            MATRIX_PROMPT,
                            research_question=research_question,
                            cluster_label=cluster.label,
                            cluster_description=cluster.description or "",
                            members=members_text,
                            dimensions=dimensions_text,
                        ),
                    }
                ],
                MatrixRow,
                prompt_version=MATRIX_PROMPT,
                note=f"matrix row: {cluster.label[:40]}",
                max_tokens=8192,
            )
            for cell in row.cells:
                if not 0 <= cell.dimension_index < len(dimensions):
                    continue
                if cell.empty:
                    cells.append(
                        {
                            "cluster_id": cluster.id,
                            "dimension": dimensions[cell.dimension_index]["name"],
                            "empty": True,
                        }
                    )
                    continue
                cited = roster_mod.valid_indexes(cell.source_indexes, roster)
                sourced = bool(cited and cell.passage)
                provenance_row = await provenance.attach(
                    project_id=ctx.project.id,
                    claim_text=cell.summary,
                    context=ProvenanceContext.comparison,
                    ref_id=comparison.id,
                    source_id=cited[0].source.id if sourced else None,
                    passage=cell.passage if sourced else None,
                    is_inference=not sourced,
                    confidence_label=ConfidenceLabel(cell.confidence_label),
                )
                cells.append(
                    {
                        "cluster_id": cluster.id,
                        "dimension": dimensions[cell.dimension_index]["name"],
                        "summary": cell.summary,
                        "source_ids": [c.source.id for c in cited],
                        "confidence_label": cell.confidence_label.value,
                        "provenance_id": provenance_row.id,
                        "empty": False,
                    }
                )
        return {
            "clusters": [{"id": c.id, "label": c.label} for c in clusters],
            "dimensions": [d["name"] for d in dimensions],
            "cells": cells,
        }

    # --- reporting --------------------------------------------------------------------

    async def _summary(self, ctx: StageContext, comparison: Comparison) -> dict[str, Any]:
        cluster_count = (
            await ctx.session.scalar(
                select(func.count())
                .select_from(Cluster)
                .where(Cluster.project_id == ctx.project.id)
            )
        ) or 0
        investigated = sum(1 for p in (comparison.contested_points or []) if p.get("investigation"))
        return {
            "comparison_id": comparison.id,
            "clusters": cluster_count,
            "dimensions": len(comparison.dimensions or []),
            "matrix_cells": len((comparison.matrix or {}).get("cells", [])),
            "consensus_points": len(comparison.consensus_points or []),
            "contested_points": len(comparison.contested_points or []),
            "contested_investigated": investigated,
        }
