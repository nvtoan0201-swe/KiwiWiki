"""Paper analysis stage (phase 3): tiered reading → structured, credibility-
weighted, provenance-linked analysis records.

Flow per batch (bounded by `analysis_concurrency`):
1. fetch best available text per source (charges `papers_read`, sequential —
   budget writes share the handler's DB session);
2. run extraction LLM calls concurrently (skim or deep read by triage status;
   a skim that proves central upgrades to a deep read, recorded + audited);
3. persist the analysis, its provenance rows (agent critique flagged as
   inference), the credibility breakdown/score, and contradiction flags.

Resumability: a source with an existing `paper_analyses` row is skipped, so
re-entry (resume or post-loop-back) never duplicates work or double-charges.
Budget: hitting any ceiling persists an honest partial-coverage summary and
re-raises, which the engine turns into a graceful budget stop.

Loop-back: deep reads report seminal works/subfields they lean on; when the
same missing subfield is named by enough distinct papers and matches nothing
in `sources`, the stage loops back to literature_search with new seed terms.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.adapters.sources.arxiv import ArxivAdapter
from app.adapters.sources.base import SourceAdapter
from app.adapters.sources.crossref import CrossrefAdapter
from app.adapters.sources.openalex import OpenAlexAdapter
from app.adapters.sources.router import normalized_title
from app.adapters.sources.semantic_scholar import SemanticScholarAdapter
from app.core.config import get_settings
from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    ProvenanceContext,
    Stage,
    TriageStatus,
)
from app.core.errors import BudgetExceeded
from app.db.models import PaperAnalysis, Source
from app.orchestrator.handler import Advance, LoopBack, StageContext, StageHandler, StageResult
from app.schemas.analysis import DeepReadExtraction, SkimExtraction
from app.services.provenance import ProvenanceService
from app.stages.analysis import reader
from app.stages.analysis.contradictions import flag_contradictions
from app.stages.analysis.credibility import assess_credibility, breakdown, scalar_score
from app.stages.analysis.fetch import fetch_text

IN_SCOPE = {TriageStatus.deep_read.value, TriageStatus.skimmed.value}


def _default_adapters() -> list[SourceAdapter]:
    return [
        OpenAlexAdapter(),
        ArxivAdapter(),
        SemanticScholarAdapter(),
        CrossrefAdapter(),
    ]


class PaperAnalysisHandler(StageHandler):
    stage = Stage.paper_analysis

    def __init__(self, adapters: list[SourceAdapter] | None = None) -> None:
        self._adapters = adapters

    def _adapters_by_name(self) -> dict[str, SourceAdapter]:
        adapters = self._adapters if self._adapters is not None else _default_adapters()
        return {a.name: a for a in adapters}

    async def run(self, ctx: StageContext) -> StageResult:
        research_question = ctx.project.research_question or ctx.project.original_request
        await self._apply_promotions(ctx)

        pending = await self._pending_sources(ctx)
        in_scope_total = await self._in_scope_count(ctx)
        already_done = in_scope_total - len(pending)

        state: dict[str, Any] = {
            "in_scope": in_scope_total,
            "analyzed_before_entry": already_done,
            "analyzed_this_execution": 0,
            "upgraded": [],
            "abstract_only": 0,
            "contradictions_flagged": 0,
            "stopped_on": None,
        }
        # Missing-work mentions accumulate per execution only: papers analyzed
        # before a loop-back are skipped on re-entry, so they cannot re-trigger.
        missing_mentions: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"papers": set(), "terms": [], "why": ""}
        )

        adapters_by_name = self._adapters_by_name()
        concurrency = max(1, get_settings().analysis_concurrency)
        try:
            for start in range(0, len(pending), concurrency):
                batch = pending[start : start + concurrency]
                await self._process_batch(
                    ctx, research_question, batch, adapters_by_name, state, missing_mentions
                )
                await ctx.checkpoint({"analysis": self._summary(state, partial=True)})
        except BudgetExceeded as exc:
            state["stopped_on"] = f"budget ({exc.details.get('category')})"
            ctx.stage_execution.summary = {"analysis": self._summary(state, partial=True)}
            raise

        state["stopped_on"] = "complete"
        loop_back = await self._missing_subfield_loop_back(ctx, missing_mentions, state)
        if loop_back is not None:
            return loop_back
        return Advance(summary={"analysis": self._summary(state, partial=False)})

    # --- selection -------------------------------------------------------------------

    async def _apply_promotions(self, ctx: StageContext) -> None:
        """A loop-back (or the user) may promote set-aside papers into scope."""
        promote_ids = ctx.loop_back_context.get("promote_source_ids") or []
        if not promote_ids:
            return
        rows = await ctx.session.execute(select(Source).where(Source.id.in_(promote_ids)))
        for source in rows.scalars():
            if source.triage_status in IN_SCOPE:
                continue
            source.triage_status = TriageStatus.skimmed.value
            source.triage_reason = (
                f"{source.triage_reason or ''} Promoted into scope for analysis.".strip()
            )
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.paper_triaged,
                description=f"Promoted '{source.title[:80]}' → skimmed",
                reasoning="Promoted into analysis scope (loop-back/user request).",
                payload={"source_id": source.id},
                run_id=ctx.run.id,
                stage=self.stage.value,
            )
        await ctx.session.flush()

    async def _pending_sources(self, ctx: StageContext) -> list[Source]:
        """In-scope sources without an analysis row yet — the resumability gate."""
        analyzed = select(PaperAnalysis.source_id)
        result = await ctx.session.execute(
            select(Source)
            .where(
                Source.project_id == ctx.project.id,
                Source.triage_status.in_(IN_SCOPE),
                Source.id.notin_(analyzed),
            )
            .order_by(Source.relevance_score.desc().nullslast(), Source.id)
        )
        return list(result.scalars())

    async def _in_scope_count(self, ctx: StageContext) -> int:
        return (
            await ctx.session.scalar(
                select(func.count())
                .select_from(Source)
                .where(
                    Source.project_id == ctx.project.id,
                    Source.triage_status.in_(IN_SCOPE),
                )
            )
        ) or 0

    # --- per-batch pipeline -------------------------------------------------------------

    async def _process_batch(
        self,
        ctx: StageContext,
        research_question: str,
        batch: list[Source],
        adapters_by_name: dict[str, SourceAdapter],
        state: dict[str, Any],
        missing_mentions: dict[str, dict[str, Any]],
    ) -> None:
        jobs: list[reader.ReadJob] = []
        budget_hit: BudgetExceeded | None = None
        for source in batch:
            await ctx.events.emit(
                "activity",
                stage=self.stage.value,
                payload={"description": f"Reading: {source.title[:80]}"},
            )
            try:
                fetched = await fetch_text(ctx, source, adapters_by_name)
            except BudgetExceeded as exc:
                # Finish the papers already charged/fetched in this batch, then
                # let the ceiling propagate — coverage stays honest either way.
                budget_hit = exc
                break
            if fetched.text_available != "full_text":
                state["abstract_only"] += 1
            depth = (
                reader.DEPTH_DEEP
                if source.triage_status == TriageStatus.deep_read.value
                else reader.DEPTH_SKIM
            )
            jobs.append(reader.ReadJob(source=source, fetched=fetched, depth=depth))

        extractions = await reader.extract_batch(ctx, research_question, jobs)

        for job, extraction in zip(jobs, extractions, strict=True):
            extraction = await self._maybe_upgrade(ctx, research_question, job, extraction, state)
            await self._persist_one(ctx, job, extraction, state, missing_mentions)
            state["analyzed_this_execution"] += 1
            await ctx.events.emit(
                "counter_update",
                stage=self.stage.value,
                payload={
                    "papers_analyzed": state["analyzed_before_entry"]
                    + state["analyzed_this_execution"],
                    "in_scope": state["in_scope"],
                },
            )

        if budget_hit is not None:
            raise budget_hit

    async def _maybe_upgrade(
        self,
        ctx: StageContext,
        research_question: str,
        job: reader.ReadJob,
        extraction: DeepReadExtraction | SkimExtraction,
        state: dict[str, Any],
    ) -> DeepReadExtraction | SkimExtraction:
        """A skim that proves central is re-read at full depth, on the record."""
        if not isinstance(extraction, SkimExtraction) or not extraction.more_central_than_triage:
            return extraction
        source = job.source
        reason = extraction.upgrade_reason or "Skim showed the paper is central to the question."
        source.triage_status = TriageStatus.deep_read.value
        state["upgraded"].append({"source_id": source.id, "reason": reason})
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.paper_triaged,
            description=f"Reading depth upgraded to deep read: '{source.title[:70]}'",
            reasoning=reason,
            payload={"source_id": source.id},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )
        job.depth = reader.DEPTH_DEEP
        deep = await reader.extract_batch(ctx, research_question, [job])
        return deep[0]

    async def _persist_one(
        self,
        ctx: StageContext,
        job: reader.ReadJob,
        extraction: DeepReadExtraction | SkimExtraction,
        state: dict[str, Any],
        missing_mentions: dict[str, dict[str, Any]],
    ) -> None:
        source = job.source
        provenance = ProvenanceService(ctx.session)
        depth = (
            reader.DEPTH_DEEP if isinstance(extraction, DeepReadExtraction) else reader.DEPTH_SKIM
        )

        if isinstance(extraction, DeepReadExtraction):
            analysis = PaperAnalysis(
                source_id=source.id,
                core_claim=extraction.core_claim,
                method=extraction.method,
                results={
                    "depth": reader.DEPTH_DEEP,
                    "text_available": job.fetched.text_available,
                    "findings": [f.model_dump() for f in extraction.results],
                },
                datasets=list(extraction.datasets),
                author_limitations=[lim.model_dump() for lim in extraction.author_limitations],
                agent_critique=extraction.agent_critique,
                confidence_label=extraction.confidence_label.value,
            )
        else:
            analysis = PaperAnalysis(
                source_id=source.id,
                core_claim=extraction.core_claim,
                method=extraction.method,
                results={
                    "depth": reader.DEPTH_SKIM,
                    "text_available": job.fetched.text_available,
                    "findings": [
                        {
                            "finding": extraction.headline_result,
                            "numbers": None,
                            "passage": extraction.headline_result_passage,
                        }
                    ],
                },
                datasets=None,
                author_limitations=None,
                agent_critique=None,
                confidence_label=extraction.confidence_label.value,
            )
        ctx.session.add(analysis)
        await ctx.session.flush()

        await self._write_provenance(ctx, provenance, source, analysis, extraction)
        await self._score_credibility(ctx, source, analysis, extraction)
        await self._ensure_embedding(ctx, source)
        flagged = await flag_contradictions(ctx, source, extraction.core_claim)
        state["contradictions_flagged"] += len(flagged)

        if isinstance(extraction, DeepReadExtraction):
            for missing in extraction.referenced_missing_works:
                key = normalized_title(missing.name)
                entry = missing_mentions[key]
                entry["papers"].add(source.id)
                entry["name"] = missing.name
                entry["why"] = missing.why_important
                for term in missing.search_terms:
                    if term not in entry["terms"]:
                        entry["terms"].append(term)

        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.paper_analyzed,
            description=(
                f"Analyzed ({depth}, {job.fetched.text_available}): '{source.title[:70]}'"
            ),
            reasoning=f"Core claim: {extraction.core_claim[:200]}",
            payload={
                "source_id": source.id,
                "analysis_id": analysis.id,
                "credibility_score": source.credibility_score,
                "confidence_label": analysis.confidence_label,
            },
            run_id=ctx.run.id,
            stage=self.stage.value,
        )

    async def _write_provenance(
        self,
        ctx: StageContext,
        provenance: ProvenanceService,
        source: Source,
        analysis: PaperAnalysis,
        extraction: DeepReadExtraction | SkimExtraction,
    ) -> None:
        """Every sourced extracted point gets a passage-backed provenance row;
        the agent critique is the one inference, flagged as such."""
        label = ConfidenceLabel(extraction.confidence_label)

        async def sourced(claim: str, passage: str) -> None:
            await provenance.attach(
                project_id=ctx.project.id,
                claim_text=claim,
                context=ProvenanceContext.analysis,
                ref_id=analysis.id,
                source_id=source.id,
                passage=passage,
                confidence_label=label,
            )

        await sourced(extraction.core_claim, extraction.core_claim_passage)
        if isinstance(extraction, DeepReadExtraction):
            await sourced(extraction.method, extraction.method_passage)
            for finding in extraction.results:
                await sourced(finding.finding, finding.passage)
            for limitation in extraction.author_limitations:
                await sourced(limitation.limitation, limitation.passage)
            await provenance.attach(
                project_id=ctx.project.id,
                claim_text=extraction.agent_critique,
                context=ProvenanceContext.analysis,
                ref_id=analysis.id,
                source_id=source.id,
                passage=None,
                is_inference=True,
                confidence_label=ConfidenceLabel.speculative,
            )
        else:
            await sourced(extraction.headline_result, extraction.headline_result_passage)

    async def _score_credibility(
        self,
        ctx: StageContext,
        source: Source,
        analysis: PaperAnalysis,
        extraction: DeepReadExtraction | SkimExtraction,
    ) -> None:
        if isinstance(extraction, DeepReadExtraction):
            results = [f.model_dump() for f in extraction.results]
            limitations = [lim.limitation for lim in extraction.author_limitations]
        else:
            results = [{"finding": extraction.headline_result}]
            limitations = []
        assessment = await assess_credibility(
            ctx,
            source,
            core_claim=extraction.core_claim,
            method=extraction.method,
            results=results,
            limitations=limitations,
        )
        analysis.credibility_breakdown = breakdown(assessment)
        source.credibility_score = scalar_score(assessment)
        await ctx.session.flush()

    async def _ensure_embedding(self, ctx: StageContext, source: Source) -> None:
        """Promoted papers may never have been embedded; contradiction pairing
        and phase-4 clustering need a vector for every analyzed source."""
        if source.embedding is not None:
            return
        vectors = await ctx.embed([f"{source.title}\n{source.abstract or ''}"])
        source.embedding = vectors[0]
        await ctx.session.flush()

    # --- loop-back ------------------------------------------------------------------

    async def _missing_subfield_loop_back(
        self,
        ctx: StageContext,
        missing_mentions: dict[str, dict[str, Any]],
        state: dict[str, Any],
    ) -> LoopBack | None:
        settings = get_settings()
        threshold = settings.analysis_missing_subfield_min_mentions
        repeated = {
            key: entry
            for key, entry in missing_mentions.items()
            if len(entry["papers"]) >= threshold
        }
        if not repeated:
            return None

        # Drop anything that is in fact already in the collected sources.
        rows = await ctx.session.execute(
            select(Source.title).where(Source.project_id == ctx.project.id)
        )
        collected = [normalized_title(title) for (title,) in rows.all()]
        truly_missing = {
            key: entry
            for key, entry in repeated.items()
            if not any(key in t or t in key for t in collected if t)
        }
        if not truly_missing:
            return None

        names = [entry["name"] for entry in truly_missing.values()]
        queries: list[str] = []
        for entry in truly_missing.values():
            for term in entry["terms"] or [entry["name"]]:
                if term not in queries:
                    queries.append(term)
        state["stopped_on"] = "loop_back"
        state["missing_subfields"] = names
        return LoopBack(
            to_stage=Stage.literature_search,
            reason=f"missed subfield: {', '.join(names)}",
            summary={"analysis": self._summary(state, partial=True)},
            context={"queries": queries},
        )

    # --- reporting ---------------------------------------------------------------------

    @staticmethod
    def _summary(state: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        analyzed = state["analyzed_before_entry"] + state["analyzed_this_execution"]
        stopped = state["stopped_on"]
        if stopped and stopped.startswith("budget"):
            coverage = f"{analyzed}/{state['in_scope']} in-scope papers analyzed; stopped on budget"
        elif analyzed >= state["in_scope"]:
            coverage = f"all {state['in_scope']} in-scope papers analyzed"
        else:
            coverage = f"{analyzed}/{state['in_scope']} in-scope papers analyzed"
        return {
            "in_scope": state["in_scope"],
            "analyzed": analyzed,
            "analyzed_this_execution": state["analyzed_this_execution"],
            "upgraded": state["upgraded"],
            "abstract_only": state["abstract_only"],
            "contradictions_flagged": state["contradictions_flagged"],
            "coverage": coverage,
            "stopped_on": stopped,
            "missing_subfields": state.get("missing_subfields", []),
            "partial": partial,
        }
