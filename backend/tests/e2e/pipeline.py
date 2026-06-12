"""Full-pipeline e2e harness (phase 7 part A).

Builds a deterministic world for the seven *real* stage handlers: a canned
source corpus behind `FakeSourceAdapter`, a scripted `FakeLLM` covering every
schema the pipeline requests, keyword embeddings, and a `RunEngine` wired to a
registry of real handlers (fake adapters injected into search and analysis).

The corpus: three relevant papers on distinct topics (two deep reads, one
skim), one off-topic paper that gets excluded, and — for the loop-back
scenario — a "Kalman" paper that only the injected loop-back query surfaces.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.sources.base import SourceAdapter, SourceHit
from app.adapters.sources.fake import FakeSourceAdapter, make_hit
from app.orchestrator.registry import StageRegistry
from app.orchestrator.runner import RunEngine
from app.schemas.analysis import (
    CredibilityAssessment,
    DeepReadExtraction,
    MissingReference,
    SkimExtraction,
)
from app.schemas.comparison import ClusterNaming, ConsensusPartition, DimensionSet, MatrixRow
from app.schemas.gap import GapSynthesis
from app.schemas.presentation import SlideDeck, ThroughLineResult
from app.schemas.report import ReportOutline, ReportSection, SelfCheckResult
from app.schemas.scoping import Ambiguity, AmbiguityOption, ProposedScope, ScopeProposal
from app.schemas.search import (
    ReformulatedQueries,
    RelevanceBatch,
    RelevanceScore,
    SaturationJudgment,
    SeedQueries,
)
from app.stages.analysis.handler import PaperAnalysisHandler
from app.stages.comparison.handler import ComparativeAnalysisHandler
from app.stages.gap.handler import GapAnalysisHandler
from app.stages.presentation.handler import PresentationGenerationHandler
from app.stages.report.handler import ReportWritingHandler
from app.stages.scoping.handler import ScopingHandler
from app.stages.search.handler import LiteratureSearchHandler
from tests.llm_fakes import FakeLLM, llm_factory
from tests.report_utils import clean_self_check, outline_responder, section_responder
from tests.stage_utils import (
    make_credibility_responder,
    make_deep_read_responder,
    make_skim_responder,
    topic_embeddings,
)
from tests.test_comparison_handler import (
    cluster_naming_responder,
    grounded_dimension,
    matrix_responder,
)
from tests.test_gap_handler import gap_synthesis
from tests.test_presentation_handler import slide_deck, through_line_result

# --- the corpus -----------------------------------------------------------------

TRANSFORMER_TITLE = "Transformer forecasting at scale"
RECURRENT_TITLE = "Recurrent models revisited"
HYBRID_TITLE = "Hybrid forecasting survey"
FRINGE_TITLE = "Fringe numerology of markets"
KALMAN_TITLE = "Foundational Kalman filtering for forecasting"

KALMAN_QUERY = "kalman filtering forecasting"

# Distinct relevance per title pins the roster order (0=Transformer, 1=Recurrent).
_RELEVANCE_BY_MARKER = {
    "Transformer": 0.95,
    "Recurrent": 0.9,
    "Hybrid": 0.5,  # skimmed
    "Fringe": 0.05,  # excluded
}


def corpus_hits() -> list[SourceHit]:
    return [
        make_hit("e2e-1", TRANSFORMER_TITLE, abstract="A study of topic1 approaches."),
        make_hit("e2e-2", RECURRENT_TITLE, abstract="A study of topic2 approaches."),
        make_hit("e2e-3", HYBRID_TITLE, abstract="A study of topic3 approaches."),
        make_hit("e2e-4", FRINGE_TITLE, abstract="A study of topic4 approaches."),
    ]


def kalman_hit() -> SourceHit:
    return make_hit("e2e-5", KALMAN_TITLE, abstract="A study of topic5 approaches.")


def corpus_adapter(*, with_kalman: bool = False) -> FakeSourceAdapter:
    """Every query returns the static corpus; only the loop-back query surfaces
    the Kalman paper."""
    search_results = {KALMAN_QUERY: [kalman_hit()]} if with_kalman else None
    return FakeSourceAdapter("fake", search_results=search_results, default_results=corpus_hits())


def missing_kalman_references() -> dict[str, list[MissingReference]]:
    """Two distinct deep reads name the same missing foundational work — enough
    mentions to trigger the analysis → search loop-back."""
    reference = MissingReference(
        name="Foundational Kalman filtering",
        why_important="Both papers benchmark against it.",
        search_terms=[KALMAN_QUERY],
    )
    return {TRANSFORMER_TITLE: [reference], RECURRENT_TITLE: [reference]}


# --- scripted LLM ------------------------------------------------------------------

_PAPER_LINE = re.compile(r"^\[(\d+)\] (.+)$", re.MULTILINE)

SCOPE_AMBIGUITY = Ambiguity(
    id="domain",
    question="Which forecasting domain matters most?",
    material=True,
    options=[
        AmbiguityOption(id="finance", label="Financial time series"),
        AmbiguityOption(id="energy", label="Energy demand"),
    ],
)


def scope_proposal(**overrides: Any) -> ScopeProposal:
    fields: dict[str, Any] = {
        "research_question": "Do transformers beat RNNs for time-series forecasting?",
        "scope": ProposedScope(time_window="2015–present", included_subfields=["forecasting"]),
        "audience": "technical",
        "outputs": ["report", "presentation"],
        "ambiguities": [],
        "answerable_from_literature": True,
        "answerability_reasoning": "A well-studied empirical question.",
    }
    fields.update(overrides)
    return ScopeProposal(**fields)


def relevance_responder(messages: Sequence[dict[str, Any]]) -> RelevanceBatch:
    prompt = messages[-1]["content"]
    scores = []
    for match in _PAPER_LINE.finditer(prompt):
        index, title = int(match.group(1)), match.group(2)
        relevance = next(
            (value for marker, value in _RELEVANCE_BY_MARKER.items() if marker in title), 0.9
        )
        scores.append(RelevanceScore(index=index, relevance=relevance, reason="scripted"))
    return RelevanceBatch(scores=scores)


def scripted_llm(
    *,
    ambiguous_scope: bool = False,
    missing_by_title: dict[str, list[MissingReference]] | None = None,
    deep_read_responder: Any = None,
) -> FakeLLM:
    """A FakeLLM scripted for every schema the seven real handlers request.

    Schemas that must *not* be requested in these scenarios (contradiction
    judgments, diversity checks) are deliberately absent: FakeLLM raises if
    they are asked for, which catches contract drift.
    """
    ambiguities = [SCOPE_AMBIGUITY] if ambiguous_scope else []
    return FakeLLM(
        {
            ScopeProposal: [scope_proposal(ambiguities=ambiguities)],
            SeedQueries: [
                SeedQueries(queries=["transformer forecasting", "recurrent forecasting"])
            ],
            ReformulatedQueries: [
                ReformulatedQueries(
                    strategy="probe adjacent subtopics", queries=["forecasting benchmarks"]
                )
            ],
            SaturationJudgment: [
                SaturationJudgment(new_ideas=True, reasoning="New methods appeared."),
                SaturationJudgment(new_ideas=False, reasoning="Nothing new in this batch."),
            ],
            RelevanceBatch: relevance_responder,
            DeepReadExtraction: deep_read_responder
            or make_deep_read_responder(missing_by_title=missing_by_title),
            SkimExtraction: make_skim_responder(),
            CredibilityAssessment: make_credibility_responder(),
            ClusterNaming: cluster_naming_responder,
            DimensionSet: [DimensionSet(dimensions=[grounded_dimension([0, 1])])],
            MatrixRow: matrix_responder,
            ConsensusPartition: [ConsensusPartition()],
            GapSynthesis: [gap_synthesis()],
            ReportOutline: outline_responder,
            ReportSection: section_responder,
            SelfCheckResult: [clean_self_check()],
            ThroughLineResult: [through_line_result()],
            SlideDeck: [slide_deck()],
        },
        tokens_per_call=(500, 200),
    )


# --- engine -------------------------------------------------------------------------


def build_e2e_registry(adapters: list[SourceAdapter]) -> StageRegistry:
    registry = StageRegistry()
    registry.register(ScopingHandler())
    registry.register(LiteratureSearchHandler(adapters=adapters))
    registry.register(PaperAnalysisHandler(adapters=adapters))
    registry.register(ComparativeAnalysisHandler())
    registry.register(GapAnalysisHandler())
    registry.register(ReportWritingHandler())
    registry.register(PresentationGenerationHandler())
    return registry


def e2e_engine(
    sessionmaker: async_sessionmaker[AsyncSession],
    bus: Any,
    fake_llm: FakeLLM,
    adapters: list[SourceAdapter] | None = None,
) -> RunEngine:
    if adapters is None:
        adapters = [corpus_adapter()]
    return RunEngine(
        sessionmaker,
        registry=build_e2e_registry(adapters),
        bus=bus,
        llm_factory=llm_factory(fake_llm),
        embeddings=topic_embeddings(),
    )


# --- output normalization (for identical-output comparisons) --------------------------


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normalize_ids(markdown: str, id_to_label: dict[str, str]) -> str:
    """Replace per-project UUIDs (citation keys) with stable labels so reports
    from two different projects can be compared for identity."""
    for source_id, label in id_to_label.items():
        markdown = markdown.replace(source_id, label)
    return _UUID.sub("<uuid>", markdown)
