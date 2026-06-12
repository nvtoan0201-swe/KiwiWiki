"""Literature search handler (phase 2C acceptance 2–7): iteration, dedup,
triage, snowballing, saturation stop, cap stop, budget stop, echo chamber."""

import datetime

from sqlalchemy import select

from app.adapters.embeddings.client import EmbeddingsClient
from app.adapters.sources.fake import FakeSourceAdapter, make_hit
from app.core.config import get_settings
from app.core.constants import (
    AuditActionType,
    DiscoveryChannel,
    Stage,
    TriageStatus,
)
from app.db.models import AuditLogEntry, Run, Source, StageExecution
from app.events.publisher import EventPublisher
from app.orchestrator.budget import BudgetGuard
from app.orchestrator.handler import StageContext
from app.schemas.search import (
    DiversityJudgment,
    ReformulatedQueries,
    RelevanceBatch,
    SaturationJudgment,
    SeedQueries,
)
from app.services.audit import AuditService
from app.stages.search.handler import LiteratureSearchHandler
from tests.llm_fakes import FakeLLM, KeywordEmbeddings, llm_factory, relevance_by_title
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse

TOPICS = [f"topic{i}" for i in range(1, 10)]


def _embeddings() -> EmbeddingsClient:
    return EmbeddingsClient(provider=KeywordEmbeddings(TOPICS))


def _search_engine(sessionmaker, bus, adapters, fake_llm):  # noqa: F811
    registry, _ = stub_registry()
    registry.register(LiteratureSearchHandler(adapters=adapters))
    return make_engine(
        sessionmaker,
        bus,
        registry,
        llm_factory=llm_factory(fake_llm),
        embeddings=_embeddings(),
    )


async def _sources(sessionmaker, project_id):
    async with sessionmaker() as session:
        result = await session.execute(select(Source).where(Source.project_id == project_id))
        return list(result.scalars())


async def _search_summary(sessionmaker, run_id):
    async with sessionmaker() as session:
        result = await session.execute(
            select(StageExecution).where(
                StageExecution.run_id == run_id,
                StageExecution.stage == Stage.literature_search.value,
            )
        )
        return result.scalars().one().summary


async def test_saturating_corpus_stops_on_saturation(sessionmaker, bus):  # noqa: F811
    """Acceptance 2, 3, 4, 5(a), 7: iterations, dedup with multi-origin, triage,
    embeddings, snowballing as a distinct channel, saturation stop, events."""
    alpha = FakeSourceAdapter(
        "alpha",
        search_results={
            "seed one": [
                make_hit(
                    "p1",
                    "Transformers for forecasting",
                    doi="10.1/p1",
                    abstract="Deep dive into topic1 methods.",
                    adapter="alpha",
                ),
                make_hit(
                    "p2",
                    "Attention models in practice",
                    doi="10.1/p2",
                    abstract="More on topic1 variants.",
                    adapter="alpha",
                ),
            ],
            "round two": [
                make_hit(
                    "r1",
                    "Restating attention for forecasting",
                    doi="10.1/r1",
                    abstract="Deep dive into topic1 methods.",
                    adapter="alpha",
                ),
            ],
            "round three": [
                make_hit(
                    "r2",
                    "Another recurrent baseline study",
                    doi="10.1/r2",
                    abstract="Classic topic2 baselines.",
                    adapter="alpha",
                ),
            ],
        },
        references_map={
            "p1": [
                make_hit(
                    "s1",
                    "Snowballed foundations",
                    doi="10.1/s1",
                    abstract="Foundations of topic1.",
                    adapter="alpha",
                )
            ],
        },
        citations_map={
            "p1": [
                make_hit(
                    "s2",
                    "Snowballed follow-up",
                    doi="10.1/s2",
                    abstract="Follow-up topic2 work.",
                    adapter="alpha",
                )
            ],
        },
    )
    beta = FakeSourceAdapter(
        "beta",
        search_results={
            "seed one": [
                # Same DOI as alpha's p1 → must merge into one row, two origins.
                make_hit(
                    "b1",
                    "Transformers for Forecasting",
                    doi="10.1/P1",
                    abstract="Deep dive into topic1 methods, richer text.",
                    adapter="beta",
                ),
            ],
            "seed two": [
                make_hit(
                    "b2",
                    "Recurrent networks revisited",
                    doi="10.1/b2",
                    abstract="A look at topic2 ideas.",
                    adapter="beta",
                ),
                make_hit(
                    "b3",
                    "Fringe numerology of markets",
                    doi="10.1/b3",
                    abstract="Unrelated topic9 content.",
                    adapter="beta",
                ),
            ],
        },
    )
    fake_llm = FakeLLM(
        {
            SeedQueries: [SeedQueries(queries=["seed one", "seed two"])],
            RelevanceBatch: relevance_by_title(),
            ReformulatedQueries: [
                ReformulatedQueries(strategy="adjacent subtopics", queries=["round two"]),
                ReformulatedQueries(strategy="baselines", queries=["round three"]),
            ],
            SaturationJudgment: [
                SaturationJudgment(new_ideas=True, reasoning="First batch is all new."),
                SaturationJudgment(new_ideas=False, reasoning="Restates iteration one."),
                SaturationJudgment(new_ideas=False, reasoning="Still nothing new."),
            ],
            DiversityJudgment: [DiversityJudgment(homogeneous=False, reasoning="Spread is fine.")],
        }
    )

    engine = _search_engine(sessionmaker, bus, [alpha, beta], fake_llm)
    project = await make_project(
        sessionmaker, research_question="Transformers vs RNNs for forecasting?"
    )
    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
    assert run.status == "complete"

    sources = await _sources(sessionmaker, project.id)
    by_title = {s.title: s for s in sources}

    # Dedup: alpha p1 and beta b1 (same DOI, case-insensitive) → one row, both origins.
    merged = by_title["Transformers for forecasting"]
    assert set(merged.raw_metadata["origins"]) == {"alpha", "beta"}
    assert sum(1 for s in sources if s.doi == "10.1/p1") == 1

    # Triage: four statuses with reasons; the fringe paper is excluded.
    assert by_title["Fringe numerology of markets"].triage_status == (TriageStatus.excluded.value)
    assert all(s.triage_status is not None and s.triage_reason for s in sources)

    # Embeddings stored for triaged-in papers only.
    assert merged.embedding is not None
    assert by_title["Fringe numerology of markets"].embedding is None

    # Snowballing: tagged citation_snowball, distinct from keyword hits.
    snowballed = [
        s for s in sources if s.discovery_channel == (DiscoveryChannel.citation_snowball.value)
    ]
    assert {s.title for s in snowballed} == {"Snowballed foundations", "Snowballed follow-up"}
    assert by_title["Recurrent networks revisited"].discovery_channel == (
        DiscoveryChannel.keyword_search.value
    )

    # Saturation: three iterations, ending saturated.
    updates = [e.payload["state"] for e in bus.of_type("saturation_update")]
    assert updates == [
        "still finding new ideas",
        "approaching saturation",
        "saturated",
    ]
    assert len(bus.of_type("counter_update")) >= 3  # at least one per iteration

    summary = await _search_summary(sessionmaker, run_id)
    assert summary["stopping"] == "saturation"
    assert summary["saturation"]["coverage"] == "thorough"
    assert summary["counts"]["by_channel"][DiscoveryChannel.citation_snowball.value] == 2
    assert summary["iterations_run"] == 3


async def test_diverse_corpus_iterates_to_cap(sessionmaker, bus, monkeypatch):  # noqa: F811
    """Acceptance 5(b): a corpus that keeps yielding new ideas runs to the cap."""
    monkeypatch.setattr(get_settings(), "search_iteration_cap", 3)
    calls = {"n": 0}

    def fresh_results(query):
        calls["n"] += 1
        n = calls["n"]
        return [
            make_hit(
                f"d{n}",
                f"Distinct study {n}",
                doi=f"10.2/d{n}",
                abstract=f"Brand new angle on topic{min(n, 9)}.",
            )
        ]

    adapter = FakeSourceAdapter("fake", search_results=fresh_results)
    fake_llm = FakeLLM(
        {
            SeedQueries: [SeedQueries(queries=["q one", "q two"])],
            RelevanceBatch: relevance_by_title(),
            ReformulatedQueries: [ReformulatedQueries(strategy="keep widening", queries=["next"])],
            SaturationJudgment: [
                SaturationJudgment(new_ideas=True, reasoning="Every batch is new.")
            ],
            DiversityJudgment: [DiversityJudgment(homogeneous=False, reasoning="Diverse.")],
        }
    )

    engine = _search_engine(sessionmaker, bus, [adapter], fake_llm)
    project = await make_project(sessionmaker, research_question="Q?")
    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    summary = await _search_summary(sessionmaker, run_id)
    assert summary["iterations_run"] == 3
    assert summary["stopping"] == "iteration_cap"
    assert summary["saturation"]["coverage"] == "thin (stopped on iteration_cap)"
    states = [e.payload["state"] for e in bus.of_type("saturation_update")]
    assert all(s == "still finding new ideas" for s in states)


async def test_tiny_budget_stops_gracefully_with_thin_coverage(sessionmaker, bus):  # noqa: F811
    """Acceptance 5(c): a tiny search budget produces a budget stop and an
    honest 'thin coverage' summary — not a crash."""
    adapter = FakeSourceAdapter(
        "fake",
        default_results=[make_hit("p1", "Some paper", doi="10.3/p1", abstract="topic1 things")],
    )
    fake_llm = FakeLLM(
        {
            SeedQueries: [SeedQueries(queries=["q one", "q two"])],
            RelevanceBatch: relevance_by_title(),
            ReformulatedQueries: [ReformulatedQueries(strategy="next", queries=["more"])],
            SaturationJudgment: [SaturationJudgment(new_ideas=True, reasoning="new")],
            DiversityJudgment: [DiversityJudgment(homogeneous=False, reasoning="fine")],
        }
    )

    engine = _search_engine(sessionmaker, bus, [adapter], fake_llm)
    project = await make_project(sessionmaker, research_question="Q?", budget={"search_calls": 3})
    run_id = await engine.start(project.id)
    await engine.execute(run_id)  # must not raise

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
    assert run.status == "stopped"
    assert run.stopping_criterion == "budget"

    summary = await _search_summary(sessionmaker, run_id)
    assert summary["search_state"]["stopped_on"] == "budget"
    assert "thin" in summary["saturation"]["coverage"]
    assert summary["partial"] is True

    finished = bus.of_type("run_finished")
    assert finished and finished[0].payload["stopping_criterion"] == "budget"


async def test_echo_chamber_triggers_counter_viewpoint_queries(
    sessionmaker,
    bus,  # noqa: F811
    monkeypatch,
):
    """Acceptance 6: a homogeneous result set triggers at least one
    counter-viewpoint reformulation."""
    monkeypatch.setattr(get_settings(), "search_iteration_cap", 3)
    calls = {"n": 0}

    def results(query):
        calls["n"] += 1
        n = calls["n"]
        if "counter" in query:
            return [
                make_hit(
                    f"c{n}-{i}",
                    f"Counter study {n}-{i}",
                    doi=f"10.4/c{n}{i}",
                    abstract=f"Critique grounded in topic2 ({n}-{i}).",
                )
                for i in range(2)
            ]
        return [
            make_hit(
                f"e{n}-{i}",
                f"Echo study {n}-{i}",
                doi=f"10.4/e{n}{i}",
                abstract=f"Yet more topic1 evidence ({n}-{i}).",
            )
            for i in range(3)
        ]

    adapter = FakeSourceAdapter("fake", search_results=results)
    fake_llm = FakeLLM(
        {
            SeedQueries: [SeedQueries(queries=["echo one", "echo two"])],
            ReformulatedQueries: [ReformulatedQueries(strategy="widen", queries=["widen more"])],
            SaturationJudgment: [
                SaturationJudgment(new_ideas=True, reasoning="new viewpoints"),
            ],
            DiversityJudgment: [
                DiversityJudgment(
                    homogeneous=True,
                    dominant_viewpoint="pro-topic1 school",
                    counter_viewpoint_queries=["counter viewpoint query"],
                    reasoning="Every paper argues the same position.",
                ),
                DiversityJudgment(homogeneous=False, reasoning="Now mixed."),
            ],
            RelevanceBatch: relevance_by_title(),
        }
    )

    engine = _search_engine(sessionmaker, bus, [adapter], fake_llm)
    project = await make_project(sessionmaker, research_question="Echo?")
    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    # The counter query actually ran and brought in the other viewpoint.
    assert any("counter" in q for q in adapter.search_calls)
    sources = await _sources(sessionmaker, project.id)
    assert any("topic2" in (s.abstract or "") for s in sources)

    async with sessionmaker() as session:
        reformulations = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.action_type == AuditActionType.query_reformulated.value
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any("echo-chamber" in r.description.lower() for r in reformulations)

    summary = await _search_summary(sessionmaker, run_id)
    assert summary["diversity"]["echo_chamber_detected"] is True
    assert summary["diversity"]["counter_viewpoint_rounds"] >= 1


async def test_loop_back_context_queries_are_used_directly(  # noqa: F811
    sessionmaker,
    session,
    bus,  # noqa: F811
    monkeypatch,
):
    """On re-entry via loop-back, injected seed terms are used and the existing
    source set is added to, not restarted."""
    monkeypatch.setattr(get_settings(), "search_iteration_cap", 1)
    adapter = FakeSourceAdapter(
        "fake",
        default_results=[make_hit("n1", "Newly requested angle", doi="10.5/n1", abstract="topic3")],
    )
    # No SeedQueries scripted: a seed-query LLM call would fail the test.
    fake_llm = FakeLLM(
        {
            SaturationJudgment: [SaturationJudgment(new_ideas=True, reasoning="new")],
            DiversityJudgment: [DiversityJudgment(homogeneous=False, reasoning="ok")],
            RelevanceBatch: relevance_by_title(),
        }
    )

    project = await make_project(sessionmaker, research_question="Q?")
    project = await session.merge(project)
    run = Run(project_id=project.id, status="running")
    session.add(run)
    await session.flush()
    # Pre-existing source from the first pass through search.
    session.add(
        Source(
            project_id=project.id,
            title="Original paper",
            doi="10.5/orig",
            abstract="topic1",
            discovery_channel=DiscoveryChannel.keyword_search.value,
            triage_status=TriageStatus.skimmed.value,
            relevance_score=0.5,
            triage_reason="prior pass",
        )
    )
    execution = StageExecution(
        run_id=run.id,
        stage=Stage.literature_search.value,
        status="running",
        started_at=datetime.datetime.now(datetime.UTC),
        loop_back_from=Stage.paper_analysis.value,
    )
    session.add(execution)
    await session.flush()

    audit = AuditService(session, bus)
    events = EventPublisher(bus, project.id, run.id)
    guard = await BudgetGuard.create(
        session, run, project, audit, events, stage=Stage.literature_search.value
    )
    ctx = StageContext(
        session=session,
        project=project,
        run=run,
        stage_execution=execution,
        budget=guard,
        audit=audit,
        events=events,
        embeddings=_embeddings(),
        llm_factory=llm_factory(fake_llm),
        loop_back_context={"queries": ["the missing angle"]},
    )

    handler = LiteratureSearchHandler(adapters=[adapter])
    result = await handler.run(ctx)

    assert adapter.search_calls == ["the missing angle"]
    sources = (
        (await session.execute(select(Source).where(Source.project_id == project.id)))
        .scalars()
        .all()
    )
    titles = {s.title for s in sources}
    assert titles == {"Original paper", "Newly requested angle"}  # added, not restarted
    assert result.summary["counts"]["total"] == 2
