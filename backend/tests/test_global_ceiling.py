"""Phase 7 part D: the hard global LLM spend ceiling.

Independent of per-project budgets: once total tokens across ALL runs reach
the global ceiling, any run that tries to spend stops gracefully — including
brand-new runs on other projects whose own budgets are untouched.
"""

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuditLogEntry, Run
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


async def test_global_ceiling_halts_runs_across_projects(
    sessionmaker, bus, monkeypatch  # noqa: F811
):
    # Each scripted LLM call notes 700 tokens; the second flush crosses 1000.
    monkeypatch.setattr(get_settings(), "global_llm_token_ceiling", 1000)

    engine = e2e_engine(sessionmaker, bus, scripted_llm())
    project = await make_project(sessionmaker)
    run_id = await engine.start(project.id)
    await engine.execute(run_id)  # graceful, never a crash

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "stopped"
        assert run.stopping_criterion == "budget"
        warning = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.run_id == run_id,
                        AuditLogEntry.action_type == "budget_warning",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("Global LLM token ceiling" in (e.description or "") for e in warning)

    # A new project with a generous *per-project* budget is still halted by the
    # global guardrail on its first spend.
    engine2 = e2e_engine(sessionmaker, bus, scripted_llm())
    other = await make_project(
        sessionmaker, title="Other project", budget={"llm_tokens": 2_000_000}
    )
    run2 = await engine2.start(other.id)
    await engine2.execute(run2)

    async with sessionmaker() as session:
        run = await session.get(Run, run2)
        assert run.status == "stopped"
        assert run.stopping_criterion == "budget"
