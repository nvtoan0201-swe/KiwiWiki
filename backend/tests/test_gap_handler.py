"""Gap & future-directions handler (phase 4B acceptance 6, 8) and the
end-to-end phase 3+4 pipeline with the thin-evidence loop-back (acceptance 7)."""

from sqlalchemy import select

from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    GapImportance,
    Stage,
)
from app.db.models import (
    AuditLogEntry,
    Comparison,
    Gap,
    PaperAnalysis,
    Provenance,
    Run,
    Source,
)
from app.orchestrator.handler import Advance
from app.schemas.analysis import (
    ContradictionJudgment,
    CredibilityAssessment,
    DeepReadExtraction,
    SkimExtraction,
)
from app.schemas.comparison import ClusterNaming, ConsensusPartition, DimensionSet, MatrixRow
from app.schemas.gap import FutureDirection, GapItem, GapSynthesis
from app.stages.analysis.handler import PaperAnalysisHandler
from app.stages.comparison.handler import ComparativeAnalysisHandler
from app.stages.gap.handler import GapAnalysisHandler
from tests.llm_fakes import FakeLLM, llm_factory
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.stage_utils import (
    add_analysis,
    add_source,
    make_credibility_responder,
    make_ctx,
    make_deep_read_responder,
    make_skim_responder,
    topic_embeddings,
)
from tests.test_comparison_handler import (
    cluster_naming_responder,
    grounded_dimension,
    matrix_responder,
)
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse

QUESTION = "Do transformers beat RNNs for forecasting?"


def gap_synthesis() -> GapSynthesis:
    return GapSynthesis(
        gaps=[
            GapItem(
                description="No analyzed paper evaluates horizons beyond 30 days.",
                gap_type="unanswered_question",
                importance=GapImportance.high,
                confidence_label=ConfidenceLabel.emerging,
                evidence="All papers cap evaluation at 30 days.",
                source_indexes=[0, 1],
                passage="we evaluate up to 30 days",
            ),
            GapItem(
                description="The stationarity assumption is shared but untested.",
                gap_type="untested_assumption",
                importance=GapImportance.medium,
                confidence_label=ConfidenceLabel.contested,
                evidence="Both clusters assume stationarity without testing it.",
                source_indexes=[],
                passage=None,
            ),
        ],
        future_directions=[
            FutureDirection(
                description="Run a long-horizon benchmark across both families.",
                rationale="Directly addresses the horizon gap.",
            )
        ],
    )


async def test_gaps_are_grounded_and_future_directions_speculative(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 6 + 8: gaps carry grounded evidence and importance; every gap
    has provenance or an inference flag; future directions are speculative."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    # Distinct relevance pins the roster order: index 0 = cited, 1 = other.
    cited = await add_source(
        session, project.id, "Paper A", status="deep_read", topic="topic1", relevance=0.95
    )
    await add_analysis(session, cited)
    other = await add_source(
        session, project.id, "Paper B", status="deep_read", topic="topic2", relevance=0.9
    )
    await add_analysis(session, other)
    session.add(Comparison(project_id=project.id, dimensions=[], matrix={"cells": []}))
    await session.flush()

    llm = FakeLLM({GapSynthesis: [gap_synthesis()]})
    ctx = await make_ctx(session, bus, project, Stage.gap_analysis, llm)
    result = await GapAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    assert result.summary == {
        "gaps": 2,
        "future_directions": 1,
        "by_importance": {"high": 1, "medium": 1},
    }
    gaps = (await session.execute(select(Gap).where(Gap.project_id == project.id))).scalars().all()
    assert len(gaps) == 3

    grounded = next(g for g in gaps if "horizons" in g.description)
    assert grounded.importance == "high"
    assert grounded.supporting_evidence["source_ids"] == [cited.id, other.id]
    assert grounded.supporting_evidence["gap_type"] == "unanswered_question"
    grounded_prov = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == grounded.id)))
        .scalars()
        .one()
    )
    assert grounded_prov.source_id == cited.id and grounded_prov.passage
    assert grounded_prov.context == "gap"

    inferred = next(g for g in gaps if "stationarity" in g.description)
    inferred_prov = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == inferred.id)))
        .scalars()
        .one()
    )
    assert inferred_prov.is_inference is True  # no passage → flagged, never silent

    future = next(g for g in gaps if "long-horizon benchmark" in g.description)
    assert future.confidence_label == ConfidenceLabel.speculative.value
    assert future.supporting_evidence["type"] == "future_direction"
    future_prov = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == future.id)))
        .scalars()
        .one()
    )
    assert future_prov.is_inference is True

    audited = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.gap_identified.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audited) == 3


async def test_gap_stage_is_idempotent_on_reentry(sessionmaker, session, bus):  # noqa: F811
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    source = await add_source(session, project.id, "Paper A", status="deep_read")
    await add_analysis(session, source)

    llm = FakeLLM({GapSynthesis: [gap_synthesis()]})
    ctx = await make_ctx(session, bus, project, Stage.gap_analysis, llm)
    handler = GapAnalysisHandler()
    await handler.run(ctx)
    first_count = len(
        (await session.execute(select(Gap).where(Gap.project_id == project.id))).scalars().all()
    )

    result = await handler.run(ctx)
    assert isinstance(result, Advance)
    assert result.summary["resumed"] is True
    second_count = len(
        (await session.execute(select(Gap).where(Gap.project_id == project.id))).scalars().all()
    )
    assert second_count == first_count


async def test_thin_evidence_loop_back_promotes_and_pipeline_completes(
    sessionmaker, bus  # noqa: F811
):
    """Acceptance 7, engine-level: comparison finds the evidence too thin,
    loops back to paper_analysis with set-aside promotions, analysis processes
    them without re-reading prior papers, and the run completes through gap
    analysis."""
    project = await make_project(
        sessionmaker,
        research_question=QUESTION,
        current_stage=Stage.comparative_analysis.value,
    )
    async with sessionmaker() as setup:
        analyzed = []
        for title, topic in [("Read paper A", "topic1"), ("Read paper B", "topic1")]:
            source = await add_source(setup, project.id, title, status="deep_read", topic=topic)
            source.credibility_score = 0.8
            await add_analysis(setup, source)
            analyzed.append(source.id)
        for title, topic in [("Benched A", "topic2"), ("Benched B", "topic2")]:
            await add_source(setup, project.id, title, status="set_aside", topic=topic)
        await setup.commit()

    fake = FakeLLM(
        {
            # Analysis of the promoted (→ skimmed) papers.
            SkimExtraction: make_skim_responder(),
            DeepReadExtraction: make_deep_read_responder(),
            CredibilityAssessment: make_credibility_responder(),
            ContradictionJudgment: [ContradictionJudgment(flags=[])],
            # Comparison + gap, scripted as in the unit tests.
            ClusterNaming: cluster_naming_responder,
            DimensionSet: [DimensionSet(dimensions=[grounded_dimension([0, 1])])],
            MatrixRow: matrix_responder,
            ConsensusPartition: [ConsensusPartition()],
            GapSynthesis: [gap_synthesis()],
        }
    )
    registry, _ = stub_registry()
    registry.register(PaperAnalysisHandler(adapters=[]))
    registry.register(ComparativeAnalysisHandler())
    registry.register(GapAnalysisHandler())
    engine = make_engine(
        sessionmaker, bus, registry, llm_factory=llm_factory(fake), embeddings=topic_embeddings()
    )

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as check:
        run = await check.get(Run, run_id)
        assert run.status == "complete"

        loop_backs = [e for e in bus.of_type("loop_back")]
        assert len(loop_backs) == 1
        assert loop_backs[0].payload["from"] == Stage.comparative_analysis.value
        assert loop_backs[0].payload["to"] == Stage.paper_analysis.value

        analyses = (
            await check.execute(
                select(PaperAnalysis, Source.title)
                .join(Source, Source.id == PaperAnalysis.source_id)
                .where(Source.project_id == project.id)
            )
        ).all()
        titles = {title for _, title in analyses}
        # Promoted papers analyzed; prior analyses not duplicated.
        assert titles == {"Read paper A", "Read paper B", "Benched A", "Benched B"}
        assert len(analyses) == 4

        comparison = (
            (await check.execute(select(Comparison).where(Comparison.project_id == project.id)))
            .scalars()
            .one()
        )
        assert comparison.matrix["cells"]
        gaps = (
            (await check.execute(select(Gap).where(Gap.project_id == project.id))).scalars().all()
        )
        assert len(gaps) == 3
