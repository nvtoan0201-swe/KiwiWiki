"""Engine-level phase 5: the run advances through the *real* report and
presentation handlers (as wired by the default registry) to completion, with
`output_ready` fired for both deliverables (acceptance 7)."""

from sqlalchemy import select

from app.core.constants import Stage
from app.db.models import Presentation, Report, Run
from app.schemas.presentation import SlideDeck, ThroughLineResult
from app.schemas.report import ReportOutline, ReportSection, SelfCheckResult
from app.stages import build_default_registry
from app.stages.presentation.handler import PresentationGenerationHandler
from app.stages.report.handler import ReportWritingHandler
from tests.llm_fakes import FakeLLM, llm_factory
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.report_utils import (
    QUESTION,
    clean_self_check,
    outline_responder,
    section_responder,
    seed_corpus,
)
from tests.stage_utils import topic_embeddings
from tests.test_presentation_handler import slide_deck, through_line_result
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


def test_default_registry_wires_real_phase5_handlers():
    registry = build_default_registry()
    assert isinstance(registry.get(Stage.report_writing), ReportWritingHandler)
    assert isinstance(registry.get(Stage.presentation_generation), PresentationGenerationHandler)


async def test_run_completes_through_both_deliverables(sessionmaker, bus):  # noqa: F811
    project = await make_project(
        sessionmaker,
        research_question=QUESTION,
        audience="expert",
        current_stage=Stage.report_writing.value,
    )
    async with sessionmaker() as setup:
        await seed_corpus(setup, project.id)
        await setup.commit()

    fake = FakeLLM(
        {
            ReportOutline: outline_responder,
            ReportSection: section_responder,
            SelfCheckResult: [clean_self_check()],
            ThroughLineResult: [through_line_result()],
            SlideDeck: [slide_deck()],
        }
    )
    registry, _ = stub_registry()
    registry.register(ReportWritingHandler())
    registry.register(PresentationGenerationHandler())
    engine = make_engine(
        sessionmaker, bus, registry, llm_factory=llm_factory(fake), embeddings=topic_embeddings()
    )

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as check:
        run = await check.get(Run, run_id)
        assert run.status == "complete"
        report = (
            (await check.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )
        deck = (
            (await check.execute(select(Presentation).where(Presentation.project_id == project.id)))
            .scalars()
            .one()
        )

    ready = {e.payload["output"]: e.payload for e in bus.of_type("output_ready")}
    assert ready["report"]["report_id"] == report.id
    assert ready["presentation"]["presentation_id"] == deck.id
    assert bus.of_type("run_finished")[-1].payload["status"] == "complete"
