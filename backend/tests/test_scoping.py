"""Scoping handler (phase 2A acceptance): escalate on ambiguity / thin
literature, advance and persist on a clear request, merge resolutions."""

from sqlalchemy import select

from app.core.constants import EscalationTrigger, ProjectStatus
from app.db.models import Escalation, Project, Run
from app.orchestrator.escalation import resolve_escalation
from app.schemas.scoping import (
    Ambiguity,
    AmbiguityOption,
    ProposedScope,
    ScopeProposal,
)
from app.stages.scoping.handler import ScopingHandler
from tests.llm_fakes import FakeLLM, llm_factory
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


def _registry_with_scoping():
    registry, handlers = stub_registry()
    registry.register(ScopingHandler())
    return registry, handlers


def _proposal(**overrides) -> ScopeProposal:
    fields = {
        "research_question": "How do transformer models compare to RNNs for forecasting?",
        "scope": ProposedScope(time_window="2015–present", included_subfields=["ML"]),
        "audience": "technical",
        "outputs": ["report"],
        "ambiguities": [],
        "answerable_from_literature": True,
        "answerability_reasoning": "A well-studied empirical question.",
    }
    fields.update(overrides)
    return ScopeProposal(**fields)


_AMBIGUITY = Ambiguity(
    id="amb1",
    question="Which forecasting domain matters?",
    material=True,
    options=[
        AmbiguityOption(id="finance", label="Financial time series"),
        AmbiguityOption(id="weather", label="Weather/climate"),
    ],
)


async def test_clear_request_advances_and_persists(sessionmaker, bus):  # noqa: F811
    fake = FakeLLM({ScopeProposal: [_proposal()]})
    registry, _ = _registry_with_scoping()
    engine = make_engine(sessionmaker, bus, registry, llm_factory=llm_factory(fake))
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
    assert run.status == "complete"
    assert reloaded.research_question == _proposal().research_question
    assert reloaded.scope["time_window"] == "2015–present"
    assert reloaded.audience == "technical"


async def test_ambiguous_request_escalates_with_options(sessionmaker, bus):  # noqa: F811
    fake = FakeLLM({ScopeProposal: [_proposal(ambiguities=[_AMBIGUITY])]})
    registry, _ = _registry_with_scoping()
    engine = make_engine(sessionmaker, bus, registry, llm_factory=llm_factory(fake))
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
        reloaded = await session.get(Project, project.id)
    assert reloaded.status == ProjectStatus.awaiting_input.value
    assert escalation.trigger == EscalationTrigger.ambiguous_scope.value
    assert escalation.options[0]["id"] == "amb1"
    assert len(escalation.options[0]["options"]) == 2

    # Resolve and resume: the chosen option is merged into the scope.
    async with sessionmaker() as session:
        await resolve_escalation(session, escalation.id, {"resolutions": {"amb1": "finance"}})
        await session.commit()
    await engine.resume(run_id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
    assert run.status == "complete"
    assert reloaded.research_question is not None
    resolved = reloaded.scope["resolved_ambiguities"]
    assert resolved[0]["choice"] == "finance"
    assert resolved[0]["label"] == "Financial time series"


async def test_unanswerable_question_escalates_thin_literature(sessionmaker, bus):  # noqa: F811
    fake = FakeLLM(
        {
            ScopeProposal: [
                _proposal(
                    answerable_from_literature=False,
                    answerability_reasoning="Requires proprietary sales data.",
                )
            ]
        }
    )
    registry, _ = _registry_with_scoping()
    engine = make_engine(sessionmaker, bus, registry, llm_factory=llm_factory(fake))
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
    assert escalation.trigger == EscalationTrigger.thin_literature.value

    # Proceed anyway → advances with the question persisted.
    async with sessionmaker() as session:
        await resolve_escalation(session, escalation.id, {"selected_option": "proceed_anyway"})
        await session.commit()
    await engine.resume(run_id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
    assert run.status == "complete"
    assert reloaded.research_question is not None


async def test_already_scoped_project_advances_without_llm(sessionmaker, bus):  # noqa: F811
    fake = FakeLLM({})  # any LLM call would raise
    registry, _ = _registry_with_scoping()
    engine = make_engine(sessionmaker, bus, registry, llm_factory=llm_factory(fake))
    project = await make_project(sessionmaker, research_question="Already confirmed question?")

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
    assert run.status == "complete"
    assert fake.calls == []

    # Stage executions for scoping show exactly one pass (idempotent re-entry
    # is exercised by the kill/resume test in test_runner).
