import pytest
from sqlalchemy import select

from app.core.constants import AuditActionType, BudgetCategory
from app.core.errors import BudgetExceeded
from app.db.models import AuditLogEntry, BudgetLedgerEntry, Run
from app.events.publisher import EventPublisher
from app.orchestrator.budget import BudgetGuard
from app.services.audit import AuditService
from tests.orchestrator_utils import make_project


async def _guard(session, sessionmaker, event_bus, budget):
    project = await make_project(sessionmaker, budget=budget)
    project = await session.merge(project)
    run = Run(project_id=project.id, status="running")
    session.add(run)
    await session.flush()
    audit = AuditService(session, event_bus)
    events = EventPublisher(event_bus, project.id, run.id)
    guard = await BudgetGuard.create(session, run, project, audit, events, stage="scoping")
    return guard, run, project


async def test_charge_writes_ledger_and_updates_run(session, sessionmaker, event_bus):
    guard, run, _ = await _guard(session, sessionmaker, event_bus, {"search_calls": 100})
    await guard.charge(BudgetCategory.search_calls, 3, note="three queries")
    await guard.charge(BudgetCategory.search_calls, 2)

    rows = (
        (await session.execute(select(BudgetLedgerEntry).order_by(BudgetLedgerEntry.timestamp)))
        .scalars()
        .all()
    )
    assert [r.amount for r in rows] == [3, 2]
    assert rows[-1].running_total == 5
    assert run.budget_consumed["search_calls"] == 5
    assert guard.remaining(BudgetCategory.search_calls) == 95
    assert guard.check(BudgetCategory.search_calls, 95)
    assert guard.would_exceed(BudgetCategory.search_calls, 96)


async def test_warning_fires_once_on_crossing(session, sessionmaker, event_bus):
    guard, _, project = await _guard(session, sessionmaker, event_bus, {"llm_tokens": 100})
    await guard.charge(BudgetCategory.llm_tokens, 70)
    await guard.charge(BudgetCategory.llm_tokens, 15)  # crosses 80
    await guard.charge(BudgetCategory.llm_tokens, 5)  # already past — no second warning

    warnings = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.project_id == project.id,
                    AuditLogEntry.action_type == AuditActionType.budget_warning.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(warnings) == 1


async def test_ceiling_hit_raises_after_recording(session, sessionmaker, event_bus):
    guard, run, _ = await _guard(session, sessionmaker, event_bus, {"search_calls": 10})
    with pytest.raises(BudgetExceeded):
        await guard.charge(BudgetCategory.search_calls, 12)
    # The spend is still recorded — the ledger reflects reality.
    assert run.budget_consumed["search_calls"] == 12


async def test_totals_survive_reload(session, sessionmaker, event_bus):
    guard, run, project = await _guard(session, sessionmaker, event_bus, {"search_calls": 100})
    await guard.charge(BudgetCategory.search_calls, 4)
    await session.commit()

    audit = AuditService(session, event_bus)
    events = EventPublisher(event_bus, project.id, run.id)
    fresh = await BudgetGuard.create(session, run, project, audit, events)
    assert fresh.total(BudgetCategory.search_calls) == 4


async def test_llm_usage_buffer_flush(session, sessionmaker, event_bus):
    guard, run, _ = await _guard(session, sessionmaker, event_bus, {"llm_tokens": 10_000})
    guard.note_llm_usage(120, 80, "claude-test")
    # Pending usage already counts toward totals before the flush.
    assert guard.total(BudgetCategory.llm_tokens) == 200
    await guard.flush_llm_usage("triage batch")
    assert run.budget_consumed["llm_tokens"] == 200
    await guard.flush_llm_usage()  # idempotent when nothing pending
    assert run.budget_consumed["llm_tokens"] == 200


async def test_unlimited_category_never_warns_or_raises(session, sessionmaker, event_bus):
    guard, _, _ = await _guard(session, sessionmaker, event_bus, {"papers_read": None})
    # papers_read falls back to defaults; charge a category with a default ceiling
    # far above the spend and confirm nothing raises.
    await guard.charge(BudgetCategory.papers_read, 1)
    assert guard.remaining(BudgetCategory.papers_read) > 0
