"""The stage handler contract: what the engine gives a stage and what it gets back.

Handlers receive a `StageContext` (DB session, budget guard, audit, events, LLM,
embeddings, prior-stage outputs, and — on resume after an escalation — the
user's response) and return one `StageResult` telling the engine what happens
next. Handlers must tolerate re-entry after a resume: check for already-produced
output before redoing work, and call `checkpoint()` after durable steps.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embeddings.client import EmbeddingsClient
from app.adapters.llm.client import LLMClient, Message, UsageCallback
from app.core.constants import EscalationTrigger, Stage, StoppingCriterion
from app.db.models import Escalation, Project, Run, StageExecution
from app.events.publisher import EventPublisher
from app.orchestrator.budget import BudgetGuard
from app.services.audit import AuditService
from app.services.trace import TraceService, llm_call_sink, new_sink

T = TypeVar("T", bound=BaseModel)

LLMFactory = Callable[[UsageCallback | None], LLMClient]


# --- StageResult discriminated union ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Advance:
    summary: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LoopBack:
    to_stage: Stage
    reason: str
    summary: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Escalate:
    trigger: EscalationTrigger
    question: str
    context: dict[str, Any] = field(default_factory=dict)
    options: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Complete:
    stopping_criterion: StoppingCriterion = StoppingCriterion.coverage
    summary: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Fail:
    error: str


StageResult = Advance | LoopBack | Escalate | Complete | Fail


# --- StageContext -----------------------------------------------------------------


class StageContext:
    def __init__(
        self,
        *,
        session: AsyncSession,
        project: Project,
        run: Run,
        stage_execution: StageExecution,
        budget: BudgetGuard,
        audit: AuditService,
        events: EventPublisher,
        embeddings: EmbeddingsClient,
        llm_factory: LLMFactory,
        escalation_response: dict[str, Any] | None = None,
        loop_back_context: dict[str, Any] | None = None,
        trace: TraceService | None = None,
    ) -> None:
        self.session = session
        self.project = project
        self.run = run
        self.stage_execution = stage_execution
        self.budget = budget
        self.audit = audit
        self.events = events
        self.embeddings = embeddings
        self.escalation_response = escalation_response
        self.loop_back_context = loop_back_context or {}
        self.trace = trace
        self._llm_factory = llm_factory
        self._llm: LLMClient | None = None

    @property
    def stage(self) -> Stage:
        return Stage(self.stage_execution.stage)

    @property
    def llm(self) -> LLMClient:
        """Built lazily so stub-only runs never construct an SDK client. Token
        usage flows into the budget buffer; call `budget.flush_llm_usage()` (or
        use `llm_json`/`llm_text`, which do it for you)."""
        if self._llm is None:
            self._llm = self._llm_factory(self.budget.note_llm_usage)
        return self._llm

    async def llm_json(
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        prompt_version: str | None = None,
        note: str = "llm call",
    ) -> T:
        """Structured LLM call off the event loop, with usage charged to the budget."""
        llm = self.llm
        sink = new_sink()
        token = llm_call_sink.set(sink)
        started = time.monotonic()
        error: str | None = None
        try:
            return await asyncio.to_thread(
                llm.complete_json,
                messages,
                schema,
                system=system,
                max_tokens=max_tokens,
                prompt_version=prompt_version,
            )
        except BaseException as exc:
            error = str(exc)
            raise
        finally:
            llm_call_sink.reset(token)
            self._trace_llm(prompt_version, note, sink, started, error)
            await self.budget.flush_llm_usage(note)

    async def llm_text(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        prompt_version: str | None = None,
        note: str = "llm call",
    ) -> str:
        llm = self.llm
        sink = new_sink()
        token = llm_call_sink.set(sink)
        started = time.monotonic()
        error: str | None = None
        try:
            return await asyncio.to_thread(
                llm.complete,
                messages,
                system=system,
                max_tokens=max_tokens,
                prompt_version=prompt_version,
            )
        except BaseException as exc:
            error = str(exc)
            raise
        finally:
            llm_call_sink.reset(token)
            self._trace_llm(prompt_version, note, sink, started, error)
            await self.budget.flush_llm_usage(note)

    def _trace_llm(
        self,
        prompt_version: str | None,
        note: str,
        sink: Any,
        started: float,
        error: str | None,
    ) -> None:
        if self.trace is None:
            return
        self.trace.record_llm_call(
            stage=self.stage_execution.stage,
            prompt_version=prompt_version,
            note=note,
            sink=sink,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error=error,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embeddings.embed, texts)

    async def get_stage_output(self, stage: Stage) -> dict[str, Any] | None:
        """Summary of the most recent completed execution of `stage` in this run."""
        result = await self.session.execute(
            select(StageExecution)
            .where(
                StageExecution.run_id == self.run.id,
                StageExecution.stage == stage.value,
                StageExecution.status == "complete",
            )
            .order_by(StageExecution.started_at.desc())
            .limit(1)
        )
        execution = result.scalars().first()
        return execution.summary if execution else None

    async def checkpoint(self, summary: dict[str, Any] | None = None) -> None:
        """Persist progress mid-stage so a killed run resumes here, not at the
        stage start. Optionally records partial state on the stage execution."""
        if summary is not None:
            self.stage_execution.summary = summary
        await self.session.commit()

    async def latest_escalation(self) -> Escalation | None:
        result = await self.session.execute(
            select(Escalation)
            .where(Escalation.run_id == self.run.id)
            .order_by(Escalation.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()


# --- StageHandler -------------------------------------------------------------------


class StageHandler(ABC):
    stage: Stage

    @abstractmethod
    async def run(self, ctx: StageContext) -> StageResult:
        """Execute the stage. Must be idempotent enough to be re-entered after a
        resume: detect prior partial output and continue rather than duplicate."""
        raise NotImplementedError
