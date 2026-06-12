"""Centralized budget accounting (overview §4: stages never self-authorize).

A `BudgetGuard` is constructed per stage step from the project's ceilings and
the durable `budget_ledger`. Every charge writes a ledger row, updates the
run's `budget_consumed` snapshot, and emits a `counter_update`. Crossing 80%
of a ceiling audits a `budget_warning` (detected on the crossing, so it fires
exactly once even across resumes); hitting a ceiling raises `BudgetExceeded`,
which the runner converts into a graceful budget stop — never a crash.

LLM token usage arrives via the wrapper's synchronous `on_usage` callback, so
it is buffered in memory (`note_llm_usage`) and flushed to the ledger with
`flush_llm_usage` after each call.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import AuditActionType, BudgetCategory
from app.core.errors import BudgetExceeded
from app.db.models import BudgetLedgerEntry, Project, Run
from app.events.publisher import EventPublisher
from app.services.audit import AuditService
from app.services.trace import llm_call_sink

logger = logging.getLogger("app.budget")

WARNING_FRACTION = 0.8


class BudgetGuard:
    def __init__(
        self,
        session: AsyncSession,
        run: Run,
        project: Project,
        audit: AuditService,
        events: EventPublisher,
        *,
        stage: str | None = None,
    ) -> None:
        self._session = session
        self._run = run
        self._project = project
        self._audit = audit
        self._events = events
        self._stage = stage
        self._ceilings = self._resolve_ceilings(project)
        self._totals: dict[str, float] = {}
        self._pending_llm_tokens = 0

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        run: Run,
        project: Project,
        audit: AuditService,
        events: EventPublisher,
        *,
        stage: str | None = None,
    ) -> BudgetGuard:
        guard = cls(session, run, project, audit, events, stage=stage)
        await guard._load_totals()
        return guard

    @staticmethod
    def _resolve_ceilings(project: Project) -> dict[str, float]:
        defaults = {k: float(v) for k, v in get_settings().default_budget.items()}
        configured = project.budget or {}
        for key, value in configured.items():
            if key in {c.value for c in BudgetCategory} and value is not None:
                defaults[key] = float(value)
        return defaults

    async def _load_totals(self) -> None:
        rows = await self._session.execute(
            select(BudgetLedgerEntry.category, func.sum(BudgetLedgerEntry.amount))
            .where(BudgetLedgerEntry.run_id == self._run.id)
            .group_by(BudgetLedgerEntry.category)
        )
        self._totals = {category: float(total or 0) for category, total in rows.all()}

    def refresh_ceilings(self) -> None:
        """Re-read ceilings from the project row (after a mid-run budget adjustment)."""
        self._ceilings = self._resolve_ceilings(self._project)

    # --- queries ---------------------------------------------------------------

    def total(self, category: BudgetCategory) -> float:
        pending = self._pending_llm_tokens if category is BudgetCategory.llm_tokens else 0
        return self._totals.get(category.value, 0.0) + pending

    def ceiling(self, category: BudgetCategory) -> float | None:
        return self._ceilings.get(category.value)

    def remaining(self, category: BudgetCategory) -> float:
        ceiling = self.ceiling(category)
        if ceiling is None:
            return float("inf")
        return max(0.0, ceiling - self.total(category))

    def check(self, category: BudgetCategory, needed: float) -> bool:
        """True if `needed` more units fit under the ceiling."""
        return self.remaining(category) >= needed

    def would_exceed(self, category: BudgetCategory, needed: float) -> bool:
        return not self.check(category, needed)

    def snapshot(self) -> dict[str, Any]:
        return {
            category: {
                "consumed": self.total(BudgetCategory(category)),
                "ceiling": self._ceilings.get(category),
            }
            for category in (c.value for c in BudgetCategory)
        }

    # --- charging ----------------------------------------------------------------

    async def charge(
        self, category: BudgetCategory, amount: float, note: str | None = None
    ) -> None:
        """Record consumption. Raises `BudgetExceeded` once the ceiling is hit;
        the entry is written first so the ledger reflects what was actually spent."""
        previous = self._totals.get(category.value, 0.0)
        new_total = previous + amount
        self._totals[category.value] = new_total

        self._session.add(
            BudgetLedgerEntry(
                run_id=self._run.id,
                timestamp=datetime.datetime.now(datetime.UTC),
                category=category.value,
                amount=amount,
                running_total=new_total,
                note=note,
            )
        )
        self._run.budget_consumed = {
            cat: self._totals.get(cat, 0.0) for cat in (c.value for c in BudgetCategory)
        }
        await self._session.flush()

        if category is BudgetCategory.llm_tokens:
            await self._check_global_ceiling()

        ceiling = self._ceilings.get(category.value)
        await self._events.emit(
            "counter_update",
            stage=self._stage,
            payload={
                "category": category.value,
                "amount": amount,
                "running_total": new_total,
                "ceiling": ceiling,
                "remaining": None if ceiling is None else max(0.0, ceiling - new_total),
            },
        )

        if ceiling is None:
            return
        threshold = WARNING_FRACTION * ceiling
        if previous < threshold <= new_total < ceiling:
            await self._audit.record(
                project_id=self._project.id,
                action_type=AuditActionType.budget_warning,
                description=(
                    f"Budget for {category.value} at "
                    f"{new_total:.0f}/{ceiling:.0f} ({new_total / ceiling:.0%})"
                ),
                reasoning="Crossed 80% of the configured ceiling.",
                payload={"category": category.value, "total": new_total, "ceiling": ceiling},
                run_id=self._run.id,
                stage=self._stage,
            )
        if new_total >= ceiling:
            raise BudgetExceeded(
                f"Budget ceiling reached for {category.value}",
                {"category": category.value, "total": new_total, "ceiling": ceiling},
            )

    async def _check_global_ceiling(self) -> None:
        """Hard global LLM spend ceiling across ALL runs (phase 7 cost
        guardrail) — independent of any per-project budget. The crossing entry
        is already in the ledger, so the spend that happened stays recorded."""
        global_ceiling = float(get_settings().global_llm_token_ceiling)
        if global_ceiling <= 0:
            return
        global_total = float(
            await self._session.scalar(
                select(func.sum(BudgetLedgerEntry.amount)).where(
                    BudgetLedgerEntry.category == BudgetCategory.llm_tokens.value
                )
            )
            or 0
        )
        if global_total < global_ceiling:
            return
        await self._audit.record(
            project_id=self._project.id,
            action_type=AuditActionType.budget_warning,
            description=(
                f"Global LLM token ceiling reached: {global_total:.0f}/{global_ceiling:.0f} "
                "across all runs"
            ),
            reasoning=(
                "The system-wide spend guardrail was hit; this run stops gracefully "
                "regardless of its own project budget."
            ),
            payload={"scope": "global", "total": global_total, "ceiling": global_ceiling},
            run_id=self._run.id,
            stage=self._stage,
        )
        raise BudgetExceeded(
            "Global LLM token ceiling reached",
            {
                "category": BudgetCategory.llm_tokens.value,
                "scope": "global",
                "total": global_total,
                "ceiling": global_ceiling,
            },
        )

    # --- LLM token buffering -------------------------------------------------------

    def note_llm_usage(self, input_tokens: int, output_tokens: int, model: str) -> None:
        """Synchronous `on_usage` callback for the LLM wrapper."""
        self._pending_llm_tokens += input_tokens + output_tokens
        # Exact per-call attribution for the run trace: the sink is set by the
        # StageContext around each LLM call, in this call's own context.
        sink = llm_call_sink.get()
        if sink is not None:
            sink["input_tokens"] += input_tokens
            sink["output_tokens"] += output_tokens
            sink["model"] = model
            sink["sdk_calls"] += 1

    async def flush_llm_usage(self, note: str = "llm call") -> None:
        if self._pending_llm_tokens <= 0:
            return
        amount = self._pending_llm_tokens
        self._pending_llm_tokens = 0
        await self.charge(BudgetCategory.llm_tokens, float(amount), note)
