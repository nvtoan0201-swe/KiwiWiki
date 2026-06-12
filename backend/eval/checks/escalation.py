"""Escalation precision/recall over a fixture suite.

Cases that *should* escalate (material ambiguity, unanswerable question,
runaway loop-back) and cases that should *not* (clear scope, non-material
ambiguity, a bounded loop-back that resolves) are run through the real engine.
Both false escalations (asking when it shouldn't) and missed escalations
(silently proceeding when it must ask) are reported; the gate is both at zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.core.constants import Stage
from app.db.models import Escalation
from app.orchestrator.runner import RunEngine
from app.schemas.scoping import Ambiguity, AmbiguityOption, ScopeProposal
from app.stages._stubs import StubBehavior
from app.stages.scoping.handler import ScopingHandler
from eval.scorecard import CheckResult
from eval.world import World, world
from tests.e2e.pipeline import SCOPE_AMBIGUITY, scope_proposal
from tests.llm_fakes import FakeLLM, llm_factory
from tests.orchestrator_utils import make_project, stub_registry

GATE = "escalation precision == 1.0 and recall == 1.0 on the fixture suite"

NON_MATERIAL_AMBIGUITY = Ambiguity(
    id="phrasing",
    question="Should the report say 'models' or 'architectures'?",
    material=False,
    options=[
        AmbiguityOption(id="models", label="models"),
        AmbiguityOption(id="architectures", label="architectures"),
    ],
)


@dataclass(slots=True)
class Scenario:
    name: str
    should_escalate: bool
    proposal: ScopeProposal | None = None  # None → pure-stub (loop-back) scenario
    loop_back_times: int | None = None  # for loop-back scenarios


SCENARIOS = [
    Scenario("clear, answerable scope", False, proposal=scope_proposal()),
    Scenario(
        "non-material ambiguity proceeds with a noted assumption",
        False,
        proposal=scope_proposal(ambiguities=[NON_MATERIAL_AMBIGUITY]),
    ),
    Scenario(
        "material ambiguity escalates",
        True,
        proposal=scope_proposal(ambiguities=[SCOPE_AMBIGUITY]),
    ),
    Scenario(
        "unanswerable question escalates (thin literature)",
        True,
        proposal=scope_proposal(
            answerable_from_literature=False,
            answerability_reasoning="No published work measures this.",
        ),
    ),
    Scenario("bounded loop-back resolves without asking", False, loop_back_times=1),
    Scenario("runaway loop-back escalates at the cap", True, loop_back_times=None),
]


async def _run_scenario(w: World, scenario: Scenario) -> bool:
    """True if the scenario's run raised an escalation."""
    behaviors = {}
    if scenario.proposal is None:
        # Loop-back scenario: analysis keeps sending the run back to search.
        behaviors[Stage.paper_analysis] = StubBehavior(
            loop_back_to=Stage.literature_search,
            loop_back_times=scenario.loop_back_times,
        )
    registry, _ = stub_registry(behaviors)
    fake = FakeLLM({ScopeProposal: [scenario.proposal]} if scenario.proposal else {})
    if scenario.proposal is not None:
        registry.register(ScopingHandler())
    engine = RunEngine(w.sessionmaker, registry=registry, bus=w.bus, llm_factory=llm_factory(fake))
    project = await make_project(w.sessionmaker)
    run_id = await engine.start(project.id)
    await engine.execute(run_id)
    async with w.sessionmaker() as session:
        raised = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .all()
        )
    return bool(raised)


async def check_escalation_precision_recall() -> CheckResult:
    outcomes = []
    false_escalations: list[str] = []
    missed_escalations: list[str] = []
    true_positives = 0
    for scenario in SCENARIOS:
        async with world() as w:
            escalated = await _run_scenario(w, scenario)
        outcomes.append(
            {
                "scenario": scenario.name,
                "expected_escalation": scenario.should_escalate,
                "escalated": escalated,
            }
        )
        if escalated and scenario.should_escalate:
            true_positives += 1
        elif escalated and not scenario.should_escalate:
            false_escalations.append(scenario.name)
        elif not escalated and scenario.should_escalate:
            missed_escalations.append(scenario.name)

    precision = (
        true_positives / (true_positives + len(false_escalations))
        if (true_positives + len(false_escalations))
        else 1.0
    )
    recall = (
        true_positives / (true_positives + len(missed_escalations))
        if (true_positives + len(missed_escalations))
        else 1.0
    )
    passed = not false_escalations and not missed_escalations
    return CheckResult(
        name="escalation_precision_recall",
        passed=passed,
        score=(precision + recall) / 2,
        gate=GATE,
        summary=(
            f"{len(SCENARIOS)} scenarios: precision {precision:.2f}, recall {recall:.2f}; "
            f"{len(false_escalations)} false, {len(missed_escalations)} missed."
        ),
        details={
            "precision": precision,
            "recall": recall,
            "false_escalations": false_escalations,
            "missed_escalations": missed_escalations,
            "scenarios": outcomes,
        },
    )
