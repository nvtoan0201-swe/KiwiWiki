"""Comparative analysis handler (phase 4A acceptance 1–5, 7, 8): data-driven
clusters, grounded dimensions, source-backed matrix cells, why-investigations
on contested points, credibility-capped consensus, thin-evidence loop-back."""

import re

from sqlalchemy import select

from app.core.constants import (
    AuditActionType,
    ConfidenceLabel,
    Stage,
)
from app.db.models import (
    AuditLogEntry,
    Cluster,
    Comparison,
    Contradiction,
    Provenance,
)
from app.orchestrator.handler import Advance, LoopBack
from app.schemas.comparison import (
    ClusterCharacterization,
    ClusterNaming,
    ConsensusPartition,
    ConsensusPoint,
    ContestedPoint,
    Dimension,
    DimensionSet,
    Investigation,
    MatrixCell,
    MatrixRow,
)
from app.stages.comparison.clustering import greedy_clusters
from app.stages.comparison.handler import ComparativeAnalysisHandler
from app.stages.comparison.roster import load_roster
from tests.llm_fakes import FakeLLM
from tests.orchestrator_utils import make_project
from tests.stage_utils import add_analysis, add_source, make_ctx
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse

QUESTION = "Do transformers beat RNNs for forecasting?"

_CLUSTER_BLOCK = re.compile(r"^Cluster (\d+):$", re.MULTILINE)
_MEMBER_LINE = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


def cluster_naming_responder(messages) -> ClusterNaming:
    """Name however many candidate groups the prompt presents."""
    prompt = messages[-1]["content"]
    indexes = [int(m.group(1)) for m in _CLUSTER_BLOCK.finditer(prompt)]
    return ClusterNaming(
        clusters=[
            ClusterCharacterization(
                cluster_index=i,
                label=f"School {i + 1}",
                description=f"Papers sharing approach {i + 1}.",
                defining_characteristics=[f"characteristic {i + 1}"],
            )
            for i in indexes
        ]
    )


def matrix_responder(messages) -> MatrixRow:
    """Ground each cell in the first member paper listed in the prompt."""
    prompt = messages[-1]["content"]
    members_section = prompt.split("### Member papers", 1)[1].split("## Dimensions", 1)[0]
    member_indexes = [int(m.group(1)) for m in _MEMBER_LINE.finditer(members_section)]
    return MatrixRow(
        cells=[
            MatrixCell(
                dimension_index=0,
                summary="This cluster evaluates on benchmark accuracy.",
                source_indexes=member_indexes[:1],
                passage="evaluated on benchmark accuracy",
                confidence_label=ConfidenceLabel.emerging,
            )
        ]
    )


def grounded_dimension(indexes: list[int]) -> Dimension:
    return Dimension(
        name="evaluation methodology",
        description="What counts as a fair forecasting benchmark.",
        why_contested="The papers disagree on metrics.",
        source_indexes=indexes,
        values_observed=["rolling-origin backtests", "fixed train/test split"],
    )


_SCHEMAS = {
    cls.__name__: cls
    for cls in (ClusterNaming, DimensionSet, MatrixRow, ConsensusPartition, Investigation)
}


def comparison_llm(**overrides) -> FakeLLM:
    responses = {
        ClusterNaming: cluster_naming_responder,
        DimensionSet: [DimensionSet(dimensions=[grounded_dimension([0, 1])])],
        MatrixRow: matrix_responder,
        ConsensusPartition: [ConsensusPartition()],
        Investigation: [
            Investigation(
                why="Different datasets and metrics.",
                resolution_type="unresolved",
                resolution=None,
                confidence_label=ConfidenceLabel.contested,
            )
        ],
    }
    for name, value in overrides.items():
        responses[_SCHEMAS[name]] = value
    return FakeLLM(responses)


async def _corpus(session, project_id, spec):
    """spec: list of (title, topic, credibility) → analyzed sources."""
    sources = []
    for title, topic, credibility in spec:
        source = await add_source(
            session, project_id, title, status="deep_read", topic=topic, credibility=credibility
        )
        await add_analysis(session, source)
        sources.append(source)
    return sources


async def test_cluster_count_is_data_driven(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 1: a mixed corpus yields several named clusters; members get
    cluster ids; a single-topic roster yields exactly one group."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    sources = await _corpus(
        session,
        project.id,
        [
            ("Attention paper A", "topic1", 0.8),
            ("Attention paper B", "topic1", 0.7),
            ("Attention paper C", "topic1", 0.7),
            ("Recurrent paper A", "topic2", 0.8),
            ("Recurrent paper B", "topic2", 0.6),
        ],
    )

    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, comparison_llm())
    result = await ComparativeAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    clusters = (
        (await session.execute(select(Cluster).where(Cluster.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(clusters) == 2
    assert {c.label for c in clusters} == {"School 1", "School 2"}
    assert all(c.description and c.defining_characteristics["characteristics"] for c in clusters)
    assert all(s.cluster_id is not None for s in sources)
    by_cluster = {}
    for s in sources:
        by_cluster.setdefault(s.cluster_id, []).append(s.title)
    assert sorted(len(v) for v in by_cluster.values()) == [2, 3]

    # Single-topic fixture → one cluster (pure grouping, no LLM needed).
    roster = await load_roster(ctx)
    same_topic = [item for item in roster if "Attention" in item.source.title]
    assert len(greedy_clusters(same_topic)) == 1


async def test_generic_dimensions_are_rejected(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 2: a dimension no papers actually vary on is dropped."""
    generic = Dimension(
        name="publication year",
        description="When the paper appeared.",
        why_contested="(none)",
        source_indexes=[0],  # only one paper cited
        values_observed=["2023"],  # only one value observed
    )
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await _corpus(
        session,
        project.id,
        [("Paper A", "topic1", 0.8), ("Paper B", "topic1", 0.7), ("Paper C", "topic2", 0.7)],
    )
    llm = comparison_llm(
        DimensionSet=[DimensionSet(dimensions=[grounded_dimension([0, 1]), generic])]
    )
    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, llm)
    result = await ComparativeAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    comparison = (
        (await session.execute(select(Comparison).where(Comparison.project_id == project.id)))
        .scalars()
        .one()
    )
    assert [d["name"] for d in comparison.dimensions] == ["evaluation methodology"]
    rejected = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.description.like("%Rejected comparison dimension%")
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rejected) == 1 and "publication year" in rejected[0].description


async def test_matrix_cells_cite_sources_with_provenance(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 3 + 8: every non-trivial cell carries source_ids and a
    provenance row."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await _corpus(
        session,
        project.id,
        [("Paper A", "topic1", 0.8), ("Paper B", "topic1", 0.7), ("Paper C", "topic2", 0.7)],
    )
    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, comparison_llm())
    result = await ComparativeAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    comparison = (
        (await session.execute(select(Comparison).where(Comparison.project_id == project.id)))
        .scalars()
        .one()
    )
    cells = [c for c in comparison.matrix["cells"] if not c.get("empty")]
    assert cells and all(c["source_ids"] and c["provenance_id"] for c in cells)
    assert all(c["confidence_label"] for c in cells)
    for cell in cells:
        provenance = await session.get(Provenance, cell["provenance_id"])
        assert provenance.context == "comparison"
        assert provenance.ref_id == comparison.id
        assert (provenance.source_id and provenance.passage) or provenance.is_inference


async def test_contested_points_get_why_investigations(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 4: a genuine conflict yields a contested point with a recorded
    why-investigation; the contradictions row is updated. A conditional
    resolution resolves; an honest 'unresolved' stays open."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    sources = await _corpus(
        session,
        project.id,
        [("Paper up", "topic1", 0.8), ("Paper down", "topic1", 0.7), ("Paper C", "topic2", 0.7)],
    )
    flagged = Contradiction(
        project_id=project.id,
        source_a_id=sources[0].id,
        source_b_id=sources[1].id,
        description="Up reports gains; Down reports losses on the same task.",
        resolved=False,
    )
    session.add(flagged)
    await session.flush()

    partition = ConsensusPartition(
        consensus_points=[],
        contested_points=[
            ContestedPoint(
                statement="Whether attention helps long-horizon forecasting.",
                source_indexes=[0, 1],
                contradiction_index=0,
            ),
            ContestedPoint(
                statement="Which preprocessing matters most.",
                source_indexes=[1, 2],
                contradiction_index=None,  # newly detected here
            ),
        ],
    )
    llm = comparison_llm(
        ConsensusPartition=[partition],
        Investigation=[
            Investigation(
                why="They evaluate on different horizons and metrics.",
                resolution_type="unresolved",
                resolution=None,
                confidence_label=ConfidenceLabel.contested,
            ),
            Investigation(
                why="Dataset families differ.",
                resolution_type="conditional",
                resolution="Normalization wins on dataset family X; detrending on Y.",
                confidence_label=ConfidenceLabel.emerging,
            ),
        ],
    )
    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, llm)
    result = await ComparativeAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    await session.refresh(flagged)
    assert flagged.investigation == "They evaluate on different horizons and metrics."
    assert flagged.resolved is False and flagged.resolution is None

    rows = (
        (await session.execute(select(Contradiction).where(Contradiction.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2  # the newly detected disagreement got its own row
    conditional = next(r for r in rows if r.id != flagged.id)
    assert conditional.resolved is True
    assert "wins on dataset family X" in conditional.resolution

    comparison = (
        (await session.execute(select(Comparison).where(Comparison.project_id == project.id)))
        .scalars()
        .one()
    )
    contested = comparison.contested_points
    assert len(contested) == 2
    assert all(p["investigation"] for p in contested)
    assert contested[0]["resolution_type"] == "unresolved"
    assert contested[1]["resolution_type"] == "conditional"

    investigated = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.contradiction_investigated.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(investigated) == 2 and all(e.reasoning for e in investigated)


async def test_weak_consensus_is_capped_below_well_established(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 5: consensus resting on low-credibility sources cannot be
    labeled well_established."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await _corpus(
        session,
        project.id,
        [
            ("Weak paper A", "topic1", 0.3),
            ("Weak paper B", "topic1", 0.25),
            ("Weak paper C", "topic2", 0.35),
            ("Weak paper D", "topic2", 0.3),
        ],
    )
    partition = ConsensusPartition(
        consensus_points=[
            ConsensusPoint(
                statement="Everyone agrees X improves Y.",
                source_indexes=[0, 1, 2],
                passage="X improves Y consistently",
                confidence_label=ConfidenceLabel.well_established,
            )
        ],
        contested_points=[],
    )
    llm = comparison_llm(ConsensusPartition=[partition])
    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, llm)
    result = await ComparativeAnalysisHandler().run(ctx)

    assert isinstance(result, Advance)
    comparison = (
        (await session.execute(select(Comparison).where(Comparison.project_id == project.id)))
        .scalars()
        .one()
    )
    point = comparison.consensus_points[0]
    assert point["confidence_label"] == ConfidenceLabel.emerging.value
    assert "Downgraded from well_established" in point["credibility_note"]
    provenance = await session.get(Provenance, point["provenance_id"])
    assert provenance.confidence_label == ConfidenceLabel.emerging.value


async def test_thin_evidence_loops_back_and_sufficient_advances(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 7 (handler level): a thin roster loops back — promoting
    set-aside papers when they exist, else searching anew."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await _corpus(session, project.id, [("Lonely paper", "topic1", 0.8)])
    aside = await add_source(session, project.id, "Benched paper", status="set_aside")

    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, comparison_llm())
    handler = ComparativeAnalysisHandler()
    result = await handler.run(ctx)
    assert isinstance(result, LoopBack)
    assert result.to_stage is Stage.paper_analysis
    assert result.context["promote_source_ids"] == [aside.id]
    assert "too thin" in result.reason

    # Without set-aside candidates the fallback is a fresh search.
    aside.triage_status = "excluded"
    await session.flush()
    result = await handler.run(ctx)
    assert isinstance(result, LoopBack)
    assert result.to_stage is Stage.literature_search
    assert result.context["queries"] == [QUESTION]


async def test_resume_skips_completed_steps(sessionmaker, session, bus):  # noqa: F811
    """Re-entry reuses the checkpointed comparison row instead of redoing
    clustering/dimension/matrix/consensus work."""
    project = await session.merge(await make_project(sessionmaker, research_question=QUESTION))
    await _corpus(
        session,
        project.id,
        [("Paper A", "topic1", 0.8), ("Paper B", "topic1", 0.7), ("Paper C", "topic2", 0.7)],
    )
    llm = comparison_llm()
    ctx = await make_ctx(session, bus, project, Stage.comparative_analysis, llm)
    handler = ComparativeAnalysisHandler()
    assert isinstance(await handler.run(ctx), Advance)
    calls_after_first = len(llm.calls)

    result = await handler.run(ctx)
    assert isinstance(result, Advance)
    assert len(llm.calls) == calls_after_first  # nothing recomputed
    comparisons = (
        (await session.execute(select(Comparison).where(Comparison.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(comparisons) == 1
