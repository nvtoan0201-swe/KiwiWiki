"""Trivial stage handlers so the full pipeline runs before real stages exist.

The plain stub audits, emits an activity line, and advances. The configurable
behaviors exercise the engine's other paths in tests:
- `escalate_once=True` → escalates on first entry, advances once a user
  response is available;
- `loop_back_to` → loops back (every time by default, or `loop_back_times`);
- `spend` → charges the budget before advancing (budget-stop tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.constants import BudgetCategory, EscalationTrigger, Stage, StoppingCriterion
from app.orchestrator.handler import (
    Advance,
    Complete,
    Escalate,
    LoopBack,
    StageContext,
    StageHandler,
    StageResult,
)


@dataclass
class StubBehavior:
    escalate_once: bool = False
    loop_back_to: Stage | None = None
    loop_back_times: int | None = None  # None with loop_back_to = loop forever
    spend: list[tuple[BudgetCategory, float]] = field(default_factory=list)
    complete_with: StoppingCriterion | None = None  # end the run early


class StubStageHandler(StageHandler):
    def __init__(self, stage: Stage, behavior: StubBehavior | None = None) -> None:
        self.stage = stage
        self.behavior = behavior or StubBehavior()
        self.calls = 0
        self._loop_backs_done = 0

    async def run(self, ctx: StageContext) -> StageResult:
        self.calls += 1
        await ctx.events.emit(
            "activity",
            stage=self.stage.value,
            payload={"description": f"[stub] {self.stage.value} ran (call {self.calls})"},
        )

        for category, amount in self.behavior.spend:
            await ctx.budget.charge(category, amount, note=f"[stub] {self.stage.value}")

        if self.behavior.escalate_once and ctx.escalation_response is None:
            return Escalate(
                trigger=EscalationTrigger.high_stakes,
                question=f"[stub] {self.stage.value} needs input",
                context={"stub": True},
                options=[
                    {"id": "option_a", "label": "Option A"},
                    {"id": "option_b", "label": "Option B"},
                ],
            )

        if self.behavior.complete_with is not None:
            return Complete(
                stopping_criterion=self.behavior.complete_with,
                summary={"stub": True, "completed_early": True},
            )

        if self.behavior.loop_back_to is not None:
            allowed = self.behavior.loop_back_times
            if allowed is None or self._loop_backs_done < allowed:
                self._loop_backs_done += 1
                return LoopBack(
                    to_stage=self.behavior.loop_back_to,
                    reason=f"[stub] {self.stage.value} requested re-work",
                    context={"stub_loop": self._loop_backs_done},
                )

        return Advance(summary={"stub": True, "calls": self.calls})
