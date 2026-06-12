"""Literature search stage (phase 2C): iterative, budget- and saturation-bounded.

Each iteration: run queries through the SourceRouter, merge/dedup into the
`sources` table, triage by relevance, embed triaged-in papers, snowball
citations from the strongest papers, check viewpoint diversity, then measure
idea saturation. Stops on saturation, budget, or the iteration cap — and says
honestly which one it was.

State (iterations, pending queries, snowballed ids, saturation streak) is
checkpointed into the stage execution summary after every iteration, so a
killed run resumes mid-search instead of restarting. Sources are deduplicated
against the database, so re-entry — including loop-backs from later stages —
adds to the existing set rather than starting over.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.prompt_loader import render_prompt
from app.adapters.sources.arxiv import ArxivAdapter
from app.adapters.sources.base import SourceAdapter, SourceHit
from app.adapters.sources.crossref import CrossrefAdapter
from app.adapters.sources.openalex import OpenAlexAdapter
from app.adapters.sources.router import MergedHit, SourceRouter, dedup_key
from app.adapters.sources.semantic_scholar import SemanticScholarAdapter
from app.core.config import get_settings
from app.core.constants import (
    AuditActionType,
    BudgetCategory,
    DiscoveryChannel,
    EscalationTrigger,
    Stage,
    StoppingCriterion,
    TriageStatus,
)
from app.core.errors import BudgetExceeded
from app.db.models import Source
from app.orchestrator.handler import (
    Advance,
    Complete,
    Escalate,
    StageContext,
    StageHandler,
    StageResult,
)
from app.schemas.search import (
    DiversityJudgment,
    ReformulatedQueries,
    SaturationJudgment,
    SearchIteration,
    SeedQueries,
)
from app.stages.search import saturation as sat
from app.stages.search.triage import TRIAGED_IN, triage_sources

SEED_PROMPT = "seed_queries_v1"
REFORMULATE_PROMPT = "reformulate_v1"
# v2 of these two fence fetched paper text as data-only (phase 7 input safety).
SATURATION_PROMPT = "saturation_judge_v2"
DIVERSITY_PROMPT = "diversity_check_v2"


def _default_adapters() -> list[SourceAdapter]:
    return [
        OpenAlexAdapter(),
        ArxivAdapter(),
        SemanticScholarAdapter(),
        CrossrefAdapter(),
    ]


def _fresh_state() -> dict[str, Any]:
    return {
        "iterations": [],
        "consecutive_saturated": 0,
        "next_queries": None,
        "snowballed_ids": [],
        "queries_used": [],
        "reformulations": 0,
        "diversity_flagged": False,
        "stopped_on": None,
    }


class LiteratureSearchHandler(StageHandler):
    stage = Stage.literature_search

    def __init__(self, adapters: list[SourceAdapter] | None = None) -> None:
        self._adapters = adapters

    def _adapter_list(self) -> list[SourceAdapter]:
        return self._adapters if self._adapters is not None else _default_adapters()

    def _router(self, ctx: StageContext, adapters: list[SourceAdapter]) -> SourceRouter:
        async def charge(amount: int, note: str) -> None:
            await ctx.budget.charge(BudgetCategory.search_calls, amount, note)
            if ctx.trace is not None:
                ctx.trace.record_source_note(stage=self.stage.value, note=note)

        return SourceRouter(adapters, charge=charge)

    async def run(self, ctx: StageContext) -> StageResult:
        research_question = ctx.project.research_question or ctx.project.original_request
        state = (ctx.stage_execution.summary or {}).get("search_state") or _fresh_state()

        # Re-entry after the all-sources-down escalation: the user chose to
        # stop, or to retry (in which case the loop just continues below).
        response = ctx.escalation_response or {}
        if response.get("selected_option") == "stop":
            state["stopped_on"] = "source_outage"
            return Complete(
                stopping_criterion=StoppingCriterion.user_stopped,
                summary=self._summary(ctx, state, partial=True),
            )

        # A loop-back from a later stage may carry new seed terms.
        injected = ctx.loop_back_context.get("queries") or ctx.loop_back_context.get("new_terms")
        if injected and not state["next_queries"]:
            state["next_queries"] = list(injected)

        adapters = self._adapter_list()
        router = self._router(ctx, adapters)
        try:
            outage = await self._search_loop(
                ctx, router, research_question, state, adapter_count=len(adapters)
            )
        except BudgetExceeded:
            # Graceful: persist honest state; the runner turns this into a
            # budget stop. Coverage is thin and the summary says so.
            state["stopped_on"] = "budget"
            ctx.stage_execution.summary = self._summary(ctx, state, partial=True)
            raise
        if outage is not None:
            return outage

        return Advance(summary=await self._final_summary(ctx, state))

    # --- the loop -----------------------------------------------------------------

    async def _search_loop(
        self,
        ctx: StageContext,
        router: SourceRouter,
        research_question: str,
        state: dict[str, Any],
        *,
        adapter_count: int,
    ) -> Escalate | None:
        """Run the search iterations. Returns an `Escalate` when every source
        adapter is down (the run pauses for the user), else None."""
        settings = get_settings()
        while len(state["iterations"]) < settings.search_iteration_cap:
            iteration_no = len(state["iterations"]) + 1
            queries = state["next_queries"] or await self._seed_queries(ctx, research_question)
            state["next_queries"] = None
            state["queries_used"].extend(q for q in queries if q not in state["queries_used"])

            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.search_run,
                description=f"Search iteration {iteration_no}: {len(queries)} queries",
                reasoning="Executing the current query set across enabled sources.",
                payload={"iteration": iteration_no, "queries": queries},
                run_id=ctx.run.id,
                stage=self.stage.value,
            )
            for query in queries:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": f'Searching: "{query}"'},
                )

            existing_vectors = await self._existing_embeddings(ctx.session, ctx.project.id)

            merged, failed = await self._run_queries(router, queries)
            if failed:
                # One adapter down → continue on the others, on the record.
                await ctx.audit.record(
                    project_id=ctx.project.id,
                    action_type=AuditActionType.error,
                    description=(
                        f"Source adapter outage: {', '.join(sorted(failed))} "
                        f"({len(failed)}/{adapter_count} adapters failed)"
                    ),
                    reasoning=(
                        "All source adapters are unreachable; the search cannot continue."
                        if len(failed) >= adapter_count
                        else "The search continued on the remaining adapters."
                    ),
                    payload={"failed_adapters": failed, "iteration": iteration_no},
                    run_id=ctx.run.id,
                    stage=self.stage.value,
                )
            if len(failed) >= adapter_count and not merged:
                # Every source is down: do not fabricate a "saturated" stop from
                # empty results — pause and ask. Re-running these queries on
                # retry is the resume path, so put them back first.
                state["next_queries"] = queries
                await ctx.checkpoint(self._summary(ctx, state, partial=True))
                return Escalate(
                    trigger=EscalationTrigger.thin_literature,
                    question=(
                        "All literature sources are currently unreachable "
                        f"({', '.join(sorted(failed))}). The search cannot proceed. "
                        "Retry now, or stop the run?"
                    ),
                    context={"failed_adapters": failed, "iteration": iteration_no},
                    options=[
                        {"id": "retry", "label": "Retry the search now"},
                        {"id": "stop", "label": "Stop the run"},
                    ],
                )
            new_sources, duplicates = await self._merge_into_db(
                ctx, merged, DiscoveryChannel.keyword_search
            )
            counts = await triage_sources(ctx, new_sources, research_question)
            new_vectors = await self._embed_triaged_in(ctx, new_sources)

            snowballed = await self._snowball(ctx, router, research_question, state)
            new_sources.extend(snowballed)
            new_vectors.extend(await self._embed_triaged_in(ctx, snowballed))

            await self._emit_counters(ctx, iteration_no)

            # Diversity / echo chamber: a homogeneous triaged-in set forces a
            # counter-viewpoint iteration.
            reformulated = False
            reformulation_reason: str | None = None
            diversity = await self._check_diversity(ctx, research_question)
            if diversity is not None and diversity.homogeneous:
                state["diversity_flagged"] = True
                if diversity.counter_viewpoint_queries:
                    state["next_queries"] = diversity.counter_viewpoint_queries
                    state["reformulations"] += 1
                    reformulated = True
                    reformulation_reason = "echo_chamber"
                    await ctx.audit.record(
                        project_id=ctx.project.id,
                        action_type=AuditActionType.query_reformulated,
                        description="Counter-viewpoint queries generated (echo-chamber check)",
                        reasoning=diversity.reasoning,
                        payload={"queries": diversity.counter_viewpoint_queries},
                        run_id=ctx.run.id,
                        stage=self.stage.value,
                    )

            # Saturation.
            triaged_in_new = [s for s in new_sources if s.triage_status in TRIAGED_IN]
            share = sat.novelty_share(new_vectors, existing_vectors)
            judge = await self._judge_saturation(ctx, research_question, triaged_in_new)
            if sat.iteration_saturated(share, judge.new_ideas):
                state["consecutive_saturated"] += 1
            else:
                state["consecutive_saturated"] = 0
            sat_state = sat.saturation_state(state["consecutive_saturated"])
            await ctx.events.emit(
                "saturation_update",
                stage=self.stage.value,
                payload={
                    "state": sat_state,
                    "novelty_share": round(share, 3),
                    "iteration": iteration_no,
                },
            )

            low_relevance = counts.get(TriageStatus.set_aside.value, 0) + counts.get(
                TriageStatus.excluded.value, 0
            )
            record = SearchIteration(
                iteration=iteration_no,
                queries=queries,
                raw_hits=sum(len(m.origins) for m in merged),
                new_sources=len(new_sources),
                duplicates=duplicates,
                low_relevance=low_relevance,
                snowballed=len(snowballed),
                novelty_share=round(share, 3),
                judge_new_ideas=judge.new_ideas,
                saturation_state=sat_state,
                reformulated=reformulated,
                reformulation_reason=reformulation_reason,
                failed_adapters=failed,
            )
            state["iterations"].append(record.model_dump())
            await ctx.checkpoint(self._summary(ctx, state, partial=True))

            if sat_state == sat.STATE_SATURATED:
                state["stopped_on"] = "saturation"
                return None

            # Plan the next iteration's queries (unless diversity already did,
            # or the cap means there is no next iteration).
            will_iterate = len(state["iterations"]) < settings.search_iteration_cap
            if will_iterate and state["next_queries"] is None:
                state["next_queries"] = await self._plan_next_queries(
                    ctx, research_question, state, record
                )

        if state["stopped_on"] is None:
            state["stopped_on"] = "iteration_cap"
        return None

    # --- query generation -----------------------------------------------------------

    async def _seed_queries(self, ctx: StageContext, research_question: str) -> list[str]:
        settings = get_settings()
        prompt = render_prompt(
            SEED_PROMPT,
            count=settings.search_seed_query_count,
            research_question=research_question,
            scope=json.dumps(ctx.project.scope or {}, indent=2),
        )
        result = await ctx.llm_json(
            [{"role": "user", "content": prompt}],
            SeedQueries,
            prompt_version=SEED_PROMPT,
            note="seed queries",
        )
        return result.queries

    async def _plan_next_queries(
        self,
        ctx: StageContext,
        research_question: str,
        state: dict[str, Any],
        record: SearchIteration,
    ) -> list[str]:
        settings = get_settings()
        total_results = record.new_sources + record.duplicates
        dup_ratio = record.duplicates / total_results if total_results else 1.0
        low_rel_ratio = record.low_relevance / record.new_sources if record.new_sources else 0.0

        if dup_ratio >= settings.reformulate_duplicate_ratio:
            failure = (
                f"{record.duplicates}/{total_results} results were duplicates of papers "
                "already collected — the queries are retreading covered ground."
            )
            reason = "mostly_duplicates"
        elif low_rel_ratio >= settings.reformulate_low_relevance_ratio:
            failure = (
                f"{record.low_relevance}/{record.new_sources} new papers were low-relevance "
                "— the queries are pulling in off-topic material."
            )
            reason = "mostly_low_relevance"
        else:
            failure = (
                "The queries are productive; explore adjacent framings and subtopics "
                "not yet covered to test whether new ideas remain."
            )
            reason = None

        prompt = render_prompt(
            REFORMULATE_PROMPT,
            research_question=research_question,
            previous_queries="\n".join(f"- {q}" for q in state["queries_used"][-8:]),
            failure_description=failure,
            count=get_settings().search_seed_query_count,
        )
        result = await ctx.llm_json(
            [{"role": "user", "content": prompt}],
            ReformulatedQueries,
            prompt_version=REFORMULATE_PROMPT,
            note="query planning",
        )
        if reason is not None:
            state["reformulations"] += 1
            record.reformulated = True
            record.reformulation_reason = reason
            state["iterations"][-1] = record.model_dump()
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.query_reformulated,
                description=f"Queries reformulated ({reason}): {result.strategy}",
                reasoning=failure,
                payload={"queries": result.queries},
                run_id=ctx.run.id,
                stage=self.stage.value,
            )
        return result.queries

    # --- search + persistence ----------------------------------------------------------

    @staticmethod
    async def _run_queries(
        router: SourceRouter, queries: list[str]
    ) -> tuple[list[MergedHit], dict[str, str]]:
        merged_by_key: dict[str, MergedHit] = {}
        failed: dict[str, str] = {}
        for query in queries:
            outcome = await router.search(query)
            failed.update(outcome.failed_adapters)
            for item in outcome.merged:
                key = dedup_key(item.hit)
                if key in merged_by_key:
                    merged_by_key[key].absorb(item.hit)
                    merged_by_key[key].origins.update(item.origins)
                else:
                    merged_by_key[key] = item
        return list(merged_by_key.values()), failed

    async def _merge_into_db(
        self,
        ctx: StageContext,
        merged: list[MergedHit],
        channel: DiscoveryChannel,
    ) -> tuple[list[Source], int]:
        """Insert new sources, count duplicates against what's already stored."""
        existing = await ctx.session.execute(
            select(Source).where(Source.project_id == ctx.project.id)
        )
        existing_keys: dict[str, Source] = {}
        for source in existing.scalars():
            hit_like = SourceHit(
                external_id=source.id,
                title=source.title,
                authors=list(source.authors or []),
                year=source.year,
                doi=source.doi,
            )
            existing_keys[dedup_key(hit_like)] = source

        new_sources: list[Source] = []
        duplicates = 0
        for item in merged:
            key = dedup_key(item.hit)
            if key in existing_keys:
                duplicates += 1
                # Remember the additional origin adapters on the stored row.
                stored = existing_keys[key]
                metadata = dict(stored.raw_metadata or {})
                origins = dict(metadata.get("origins") or {})
                origins.update(item.origins)
                metadata["origins"] = origins
                stored.raw_metadata = metadata
                continue
            source = Source(
                project_id=ctx.project.id,
                title=item.hit.title,
                authors=item.hit.authors,
                venue=item.hit.venue,
                year=item.hit.year,
                doi=item.hit.doi,
                url=item.hit.url,
                abstract=item.hit.abstract,
                discovery_channel=channel.value,
                raw_metadata={"origins": item.origins, "raw": item.hit.raw},
            )
            ctx.session.add(source)
            new_sources.append(source)
            existing_keys[key] = source
        await ctx.session.flush()
        return new_sources, duplicates

    async def _snowball(
        self,
        ctx: StageContext,
        router: SourceRouter,
        research_question: str,
        state: dict[str, Any],
    ) -> list[Source]:
        """One hop of citation snowballing from the strongest unexplored papers."""
        settings = get_settings()
        result = await ctx.session.execute(
            select(Source)
            .where(
                Source.project_id == ctx.project.id,
                Source.triage_status == TriageStatus.deep_read.value,
                Source.id.notin_(state["snowballed_ids"] or [""]),
            )
            .order_by(Source.relevance_score.desc())
            .limit(settings.snowball_top_n)
        )
        seeds = list(result.scalars())
        if not seeds:
            return []

        merged_by_key: dict[str, MergedHit] = {}
        for seed in seeds:
            origins = dict((seed.raw_metadata or {}).get("origins") or {})
            hits = await router.references(origins) + await router.citations(origins)
            for hit in hits:
                key = dedup_key(hit)
                if key in merged_by_key:
                    merged_by_key[key].absorb(hit)
                else:
                    merged_by_key[key] = MergedHit(hit=hit, origins={hit.adapter: hit.external_id})
            state["snowballed_ids"].append(seed.id)

        new_sources, _ = await self._merge_into_db(
            ctx, list(merged_by_key.values()), DiscoveryChannel.citation_snowball
        )
        if new_sources:
            await triage_sources(ctx, new_sources, research_question)
        return new_sources

    # --- embeddings, diversity, saturation -------------------------------------------------

    async def _embed_triaged_in(
        self, ctx: StageContext, sources: list[Source]
    ) -> list[list[float]]:
        targets = [s for s in sources if s.triage_status in TRIAGED_IN and s.embedding is None]
        if not targets:
            return []
        vectors = await ctx.embed([f"{s.title}\n{s.abstract or ''}" for s in targets])
        for source, vector in zip(targets, vectors, strict=True):
            source.embedding = vector
        await ctx.session.flush()
        return vectors

    @staticmethod
    async def _existing_embeddings(session: AsyncSession, project_id: str) -> list[list[float]]:
        result = await session.execute(
            select(Source.embedding).where(
                Source.project_id == project_id, Source.embedding.is_not(None)
            )
        )
        # JSON columns can hold a JSON null that the SQL filter lets through.
        return [list(v) for (v,) in result.all() if v is not None]

    async def _check_diversity(
        self, ctx: StageContext, research_question: str
    ) -> DiversityJudgment | None:
        settings = get_settings()
        result = await ctx.session.execute(
            select(Source)
            .where(
                Source.project_id == ctx.project.id,
                Source.triage_status.in_(TRIAGED_IN),
            )
            .order_by(Source.relevance_score.desc())
            .limit(30)
        )
        triaged_in = list(result.scalars())
        if len(triaged_in) < settings.echo_chamber_min_papers:
            return None

        vectors = [list(s.embedding) for s in triaged_in if s.embedding is not None]
        mean_sim = sat.mean_pairwise_similarity(vectors)
        if mean_sim < settings.echo_chamber_similarity:
            return None  # embeddings already show spread; no LLM call needed

        papers = "\n".join(f"- {s.title} — {(s.abstract or '')[:200]}" for s in triaged_in)
        return await ctx.llm_json(
            [
                {
                    "role": "user",
                    "content": render_prompt(
                        DIVERSITY_PROMPT,
                        research_question=research_question,
                        papers=papers,
                    ),
                }
            ],
            DiversityJudgment,
            prompt_version=DIVERSITY_PROMPT,
            note="diversity check",
        )

    async def _judge_saturation(
        self, ctx: StageContext, research_question: str, new_sources: list[Source]
    ) -> SaturationJudgment:
        if not new_sources:
            return SaturationJudgment(
                new_ideas=False, reasoning="The iteration added no triaged-in papers."
            )
        result = await ctx.session.execute(
            select(Source.title)
            .where(
                Source.project_id == ctx.project.id,
                Source.triage_status.in_(TRIAGED_IN),
                Source.id.notin_([s.id for s in new_sources]),
            )
            .limit(30)
        )
        existing_titles = [title for (title,) in result.all()]
        prompt = render_prompt(
            SATURATION_PROMPT,
            research_question=research_question,
            existing_papers="\n".join(f"- {t}" for t in existing_titles) or "(none yet)",
            new_papers="\n".join(
                f"- {s.title} — {(s.abstract or '')[:200]}" for s in new_sources[:15]
            ),
        )
        return await ctx.llm_json(
            [{"role": "user", "content": prompt}],
            SaturationJudgment,
            prompt_version=SATURATION_PROMPT,
            note="saturation judgment",
        )

    # --- reporting ----------------------------------------------------------------------

    async def _emit_counters(self, ctx: StageContext, iteration: int) -> None:
        result = await ctx.session.execute(
            select(Source.triage_status, func.count())
            .where(Source.project_id == ctx.project.id)
            .group_by(Source.triage_status)
        )
        by_status = {status or "untriaged": count for status, count in result.all()}
        await ctx.events.emit(
            "counter_update",
            stage=self.stage.value,
            payload={
                "papers_found": sum(by_status.values()),
                "papers_triaged": sum(v for k, v in by_status.items() if k != "untriaged"),
                "by_status": by_status,
                "searches": iteration,
            },
        )

    def _summary(
        self, ctx: StageContext, state: dict[str, Any], *, partial: bool
    ) -> dict[str, Any]:
        stopped_on = state.get("stopped_on")
        coverage = (
            "thorough"
            if stopped_on == "saturation"
            else f"thin (stopped on {stopped_on})" if stopped_on else "in progress"
        )
        return {
            **{
                k: v
                for k, v in (ctx.stage_execution.summary or {}).items()
                if k == "_loop_back_context"
            },
            "search_state": state,
            "saturation": {
                "saturated": stopped_on == "saturation",
                "consecutive_saturated": state["consecutive_saturated"],
                "last_novelty_share": (
                    state["iterations"][-1]["novelty_share"] if state["iterations"] else None
                ),
                "state": sat.saturation_state(state["consecutive_saturated"]),
                "coverage": coverage,
                "note": (
                    "Search stopped at idea saturation; coverage is thorough."
                    if stopped_on == "saturation"
                    else f"Coverage {coverage}."
                ),
            },
            "diversity": {
                "echo_chamber_detected": state["diversity_flagged"],
                "counter_viewpoint_rounds": state["reformulations"],
            },
            "partial": partial,
        }

    async def _final_summary(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        status_rows = await ctx.session.execute(
            select(Source.triage_status, func.count())
            .where(Source.project_id == ctx.project.id)
            .group_by(Source.triage_status)
        )
        by_status: dict[str | None, int] = {s: c for s, c in status_rows.all()}
        channel_rows = await ctx.session.execute(
            select(Source.discovery_channel, func.count())
            .where(Source.project_id == ctx.project.id)
            .group_by(Source.discovery_channel)
        )
        by_channel: dict[str | None, int] = {ch: c for ch, c in channel_rows.all()}
        return {
            **self._summary(ctx, state, partial=False),
            "counts": {
                "total": sum(by_status.values()),
                "by_status": {k or "untriaged": v for k, v in by_status.items()},
                "by_channel": {k or "unknown": v for k, v in by_channel.items()},
            },
            "queries_used": state["queries_used"],
            "iterations_run": len(state["iterations"]),
            "stopping": state.get("stopped_on"),
        }
