"""Shared helpers for stage-handler tests (phases 3–4): direct StageContext
construction, corpus builders, and deterministic LLM responders keyed on the
paper title found in the rendered prompt."""

from __future__ import annotations

import datetime
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings.client import EmbeddingsClient
from app.core.constants import ConfidenceLabel, Stage
from app.db.models import PaperAnalysis, Project, Run, Source, StageExecution
from app.events.publisher import EventPublisher
from app.orchestrator.budget import BudgetGuard
from app.orchestrator.handler import StageContext
from app.schemas.analysis import (
    AuthorLimitation,
    CredibilityAssessment,
    CredibilityComponent,
    DeepReadExtraction,
    MissingReference,
    ResultFinding,
    SkimExtraction,
)
from app.services.audit import AuditService
from tests.llm_fakes import FakeLLM, KeywordEmbeddings, llm_factory

TOPICS = [f"topic{i}" for i in range(1, 10)]

_TITLE_LINE = re.compile(r"^Title: (.+)$", re.MULTILINE)


def title_from_prompt(messages) -> str:
    match = _TITLE_LINE.search(messages[-1]["content"])
    return match.group(1) if match else ""


def topic_embeddings() -> EmbeddingsClient:
    return EmbeddingsClient(provider=KeywordEmbeddings(TOPICS))


def topic_vector(topic: str) -> list[float]:
    return KeywordEmbeddings(TOPICS).embed([topic])[0]


async def make_ctx(
    session: AsyncSession,
    bus,
    project: Project,
    stage: Stage,
    fake_llm: FakeLLM,
    *,
    loop_back_context: dict[str, Any] | None = None,
) -> StageContext:
    run = Run(project_id=project.id, status="running")
    session.add(run)
    await session.flush()
    execution = StageExecution(
        run_id=run.id,
        stage=stage.value,
        status="running",
        started_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(execution)
    await session.flush()
    audit = AuditService(session, bus)
    events = EventPublisher(bus, project.id, run.id)
    guard = await BudgetGuard.create(session, run, project, audit, events, stage=stage.value)
    return StageContext(
        session=session,
        project=project,
        run=run,
        stage_execution=execution,
        budget=guard,
        audit=audit,
        events=events,
        embeddings=topic_embeddings(),
        llm_factory=llm_factory(fake_llm),
        loop_back_context=loop_back_context,
    )


async def new_execution(ctx: StageContext) -> StageContext:
    """A fresh execution of the same stage in the same run (re-entry)."""
    execution = StageExecution(
        run_id=ctx.run.id,
        stage=ctx.stage_execution.stage,
        status="running",
        started_at=datetime.datetime.now(datetime.UTC),
    )
    ctx.session.add(execution)
    await ctx.session.flush()
    ctx.stage_execution = execution
    return ctx


async def add_source(
    session: AsyncSession,
    project_id: str,
    title: str,
    *,
    status: str,
    topic: str = "topic1",
    relevance: float = 0.9,
    credibility: float | None = None,
    embed: bool = True,
) -> Source:
    source = Source(
        project_id=project_id,
        title=title,
        authors=["Ada Lovelace"],
        venue="Fake Journal",
        year=2023,
        abstract=f"A study of {topic} approaches.",
        discovery_channel="keyword_search",
        relevance_score=relevance,
        credibility_score=credibility,
        triage_status=status,
        triage_reason="fixture",
        embedding=topic_vector(topic) if embed else None,
    )
    session.add(source)
    await session.flush()
    return source


async def add_analysis(
    session: AsyncSession,
    source: Source,
    *,
    core_claim: str | None = None,
    method: str = "controlled experiment",
) -> PaperAnalysis:
    analysis = PaperAnalysis(
        source_id=source.id,
        core_claim=core_claim or f"{source.title} core claim",
        method=method,
        results={"depth": "deep_read", "findings": []},
        confidence_label=ConfidenceLabel.emerging.value,
    )
    session.add(analysis)
    await session.flush()
    return analysis


# --- responders -------------------------------------------------------------------


def make_deep_read_responder(
    *,
    missing_by_title: dict[str, list[MissingReference]] | None = None,
):
    def respond(messages) -> DeepReadExtraction:
        title = title_from_prompt(messages)
        return DeepReadExtraction(
            core_claim=f"{title}: approach works",
            core_claim_passage="approach outperforms baselines",
            method="randomized controlled comparison",
            method_passage="we randomly assign (Sec. 3)",
            results=[
                ResultFinding(
                    finding=f"{title}: accuracy 0.91 vs 0.84 baseline",
                    numbers="0.91 vs 0.84, n=1200",
                    passage="accuracy of 0.91 (n=1200)",
                )
            ],
            datasets=["BenchA"],
            author_limitations=[
                AuthorLimitation(limitation="single-domain evaluation", passage="Sec. 6")
            ],
            agent_critique="No ablation isolates the proposed component.",
            confidence_label=ConfidenceLabel.emerging,
            referenced_missing_works=(missing_by_title or {}).get(title, []),
        )

    return respond


def make_skim_responder(*, upgrade_titles: set[str] | None = None):
    def respond(messages) -> SkimExtraction:
        title = title_from_prompt(messages)
        upgrade = title in (upgrade_titles or set())
        return SkimExtraction(
            core_claim=f"{title}: modest effect",
            core_claim_passage="we find a modest effect",
            method="survey",
            headline_result=f"{title}: effect size 0.2",
            headline_result_passage="effect size 0.2",
            confidence_label=ConfidenceLabel.emerging,
            more_central_than_triage=upgrade,
            upgrade_reason="Directly answers the research question." if upgrade else None,
        )

    return respond


def credibility_component(score: float, known: bool = True) -> CredibilityComponent:
    return CredibilityComponent(score=score, note="fixture", known=known)


def make_credibility_responder(by_title: dict[str, CredibilityAssessment] | None = None):
    default = CredibilityAssessment(
        venue_quality=credibility_component(0.6),
        sample_size_power=credibility_component(0.7),
        methodology_rigor=credibility_component(0.8),
        conflicts_of_interest=credibility_component(0.5, known=False),
        replication_status=credibility_component(0.5, known=False),
        summary="Solid method.",
    )

    def respond(messages) -> CredibilityAssessment:
        title = title_from_prompt(messages)
        return (by_title or {}).get(title, default)

    return respond
