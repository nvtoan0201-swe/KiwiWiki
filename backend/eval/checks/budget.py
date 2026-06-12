"""Budget adherence: a run that hits a ceiling stops gracefully — the ledger
never exceeds the ceiling, the stop is recorded as `budget`, partial coverage
is honestly summarized, and nothing crashes or keeps spending afterwards."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.constants import Stage
from app.db.models import BudgetLedgerEntry, PaperAnalysis, Run, StageExecution
from eval.scorecard import CheckResult
from eval.world import world
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project

GATE = "ceiling hit → graceful budget stop; ledger total never exceeds the ceiling"

PAPERS_CEILING = 2


async def check_budget_adherence() -> CheckResult:
    async with world() as w:
        engine = e2e_engine(w.sessionmaker, w.bus, scripted_llm())
        project = await make_project(w.sessionmaker, budget={"papers_read": PAPERS_CEILING})
        run_id = await engine.start(project.id)
        # Must not raise: hitting a ceiling is a graceful stop, never a crash.
        await engine.execute(run_id)

        async with w.sessionmaker() as session:
            run = await session.get(Run, run_id)
            papers_total = (
                await session.scalar(
                    select(func.sum(BudgetLedgerEntry.amount)).where(
                        BudgetLedgerEntry.run_id == run_id,
                        BudgetLedgerEntry.category == "papers_read",
                    )
                )
                or 0
            )
            analyses = (await session.execute(select(PaperAnalysis))).scalars().all()
            analysis_exec = (
                (
                    await session.execute(
                        select(StageExecution).where(
                            StageExecution.run_id == run_id,
                            StageExecution.stage == Stage.paper_analysis.value,
                        )
                    )
                )
                .scalars()
                .one()
            )

    summary = (analysis_exec.summary or {}).get("analysis") or {}
    finished = [e for e in w.bus.events if e.type == "run_finished"]
    checks = {
        "run stopped (not failed)": run.status == "stopped",
        "stopping criterion is budget": run.stopping_criterion == "budget",
        "ledger never exceeds ceiling": float(papers_total) <= PAPERS_CEILING,
        "partial work was kept": len(analyses) >= 1,
        "coverage summarized honestly": "budget" in str(summary.get("coverage", "")),
        "stop announced on the stream": bool(finished)
        and finished[-1].payload.get("stopping_criterion") == "budget",
    }
    failures = [name for name, ok in checks.items() if not ok]
    return CheckResult(
        name="budget_adherence",
        passed=not failures,
        score=(len(checks) - len(failures)) / len(checks),
        gate=GATE,
        summary=(
            f"papers_read ceiling {PAPERS_CEILING}: charged {papers_total:.0f}, "
            f"run ended '{run.status}/{run.stopping_criterion}'; "
            f"{len(failures)} assertion(s) failed."
        ),
        details={"checks": checks, "analysis_summary": summary},
    )
