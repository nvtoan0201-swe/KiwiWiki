"""Presentation-generation handler (phase 5 part B): through-line first,
3–5 key messages, distilled slides with evidence/visuals/speaker notes,
provenance on every point, and idempotent re-entry."""

from sqlalchemy import select

from app.core.constants import AuditActionType, Stage
from app.db.models import AuditLogEntry, Presentation, Provenance, Report
from app.orchestrator.handler import Advance
from app.schemas.presentation import (
    EvidencePoint,
    KeyMessage,
    Slide,
    SlideDeck,
    ThroughLineResult,
    VisualSpec,
)
from app.stages.presentation.handler import PresentationGenerationHandler
from tests.llm_fakes import FakeLLM
from tests.orchestrator_utils import make_project
from tests.report_utils import QUESTION, seed_corpus
from tests.stage_utils import make_ctx, new_execution
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse

THROUGH_LINE = "The forecast horizon, not the architecture, decides the winner."


def through_line_result() -> ThroughLineResult:
    return ThroughLineResult(
        through_line=THROUGH_LINE,
        key_messages=[
            KeyMessage(message="Transformers win only beyond short horizons.", source_indexes=[0]),
            KeyMessage(message="Evidence beyond 30 days is missing.", source_indexes=[1]),
            KeyMessage(message="Pick the model per use case, not per fashion.", source_indexes=[]),
        ],
    )


def slide_deck() -> SlideDeck:
    return SlideDeck(
        slides=[
            Slide(
                headline="Architecture is the wrong question",
                key_message_index=0,
                evidence=[
                    EvidencePoint(
                        text="Paper A reports 0.91 accuracy on short horizons.",
                        source_indexes=[0],
                        passage="accuracy of 0.91 (Sec. 4)",
                    )
                ],
                visual=VisualSpec(
                    type="comparison_table",
                    title="Accuracy by horizon",
                    columns=["Model", "Short", "Long"],
                    rows=[["Transformer", "0.91", "?"], ["RNN", "0.84", "?"]],
                ),
                speaker_notes="Caveat: both papers cap evaluation at 30 days.",
            ),
            Slide(
                headline="The 30-day wall",
                key_message_index=1,
                evidence=[
                    EvidencePoint(
                        text="No analyzed paper evaluates beyond 30 days.",
                        source_indexes=[1],
                        passage="we evaluate up to 30 days",
                    )
                ],
                speaker_notes="This is the field's largest gap.",
            ),
            Slide(
                headline="What to do on Monday",
                key_message_index=2,
                evidence=[
                    EvidencePoint(
                        text="Match the model family to the forecast horizon.",
                        source_indexes=[],
                        is_inference=True,
                    )
                ],
            ),
        ]
    )


def presentation_llm() -> FakeLLM:
    return FakeLLM({ThroughLineResult: [through_line_result()], SlideDeck: [slide_deck()]})


async def test_presentation_is_a_distilled_reauthoring(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 4 + 7: stored through-line, 3–5 key messages, slides with
    headline + evidence + optional visual spec, speaker notes, provenance on
    every evidence point, and `output_ready`."""
    project = await session.merge(
        await make_project(sessionmaker, research_question=QUESTION, audience="executive")
    )
    first, second = await seed_corpus(session, project.id)
    session.add(
        Report(project_id=project.id, audience="executive", content_markdown="# Report", version=1)
    )
    await session.flush()

    ctx = await make_ctx(session, bus, project, Stage.presentation_generation, presentation_llm())
    result = await PresentationGenerationHandler().run(ctx)

    assert isinstance(result, Advance)
    assert result.summary["key_messages"] == 3
    assert result.summary["slides"] == 3

    deck = (
        (await session.execute(select(Presentation).where(Presentation.project_id == project.id)))
        .scalars()
        .one()
    )
    assert deck.through_line == THROUGH_LINE
    assert 3 <= len(deck.key_messages) <= 5
    # Roster indexes were resolved to real source ids.
    assert deck.key_messages[0]["source_ids"] == [first.id]
    assert deck.key_messages[1]["source_ids"] == [second.id]

    assert [s["headline"] for s in deck.slides] == [
        "Architecture is the wrong question",
        "The 30-day wall",
        "What to do on Monday",
    ]
    assert deck.slides[0]["evidence"][0]["source_ids"] == [first.id]
    assert deck.slides[0]["visual"]["type"] == "comparison_table"
    assert deck.slides[0]["visual"]["rows"][0] == ["Transformer", "0.91", "?"]
    assert deck.slides[1]["visual"] is None
    assert deck.slides[2]["evidence"][0]["is_inference"] is True
    # Nuance lives in the speaker notes, indexed per slide.
    assert deck.speaker_notes[0] == {
        "slide": 0,
        "notes": "Caveat: both papers cap evaluation at 30 days.",
    }

    provenance = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == deck.id)))
        .scalars()
        .all()
    )
    by_claim = {p.claim_text: p for p in provenance}
    # The through-line is the agent's synthesis: always flagged inference.
    assert by_claim[THROUGH_LINE].is_inference is True
    sourced = by_claim["Paper A reports 0.91 accuracy on short horizons."]
    assert sourced.source_id == first.id and sourced.passage
    inferred = by_claim["Match the model family to the forecast horizon."]
    assert inferred.is_inference is True and inferred.source_id is None

    ready = bus.of_type("output_ready")
    assert len(ready) == 1
    assert ready[0].payload == {
        "output": "presentation",
        "presentation_id": deck.id,
        "version": 1,
    }
    audited = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.presentation_generated.value
                )
            )
        )
        .scalars()
        .one()
    )
    assert THROUGH_LINE in audited.reasoning


async def test_presentation_stage_is_idempotent_on_reentry(
    sessionmaker, session, bus  # noqa: F811
):
    project = await session.merge(
        await make_project(sessionmaker, research_question=QUESTION, audience="executive")
    )
    await seed_corpus(session, project.id)
    ctx = await make_ctx(session, bus, project, Stage.presentation_generation, presentation_llm())
    handler = PresentationGenerationHandler()
    first_result = await handler.run(ctx)

    result = await handler.run(await new_execution(ctx))
    assert isinstance(result, Advance)
    assert result.summary == {
        "presentation_id": first_result.summary["presentation_id"],
        "version": 1,
        "resumed": True,
    }
    count = len(
        (await session.execute(select(Presentation).where(Presentation.project_id == project.id)))
        .scalars()
        .all()
    )
    assert count == 1
