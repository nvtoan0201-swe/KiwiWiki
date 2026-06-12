"""Phase 7 part A: a full run that escalates (ambiguous scope) and is resolved.

The engine pauses the run and flips the project to awaiting_input; resolving
the escalation re-queues the run, the scoping handler merges the resolution
into the persisted scope, and the rest of the pipeline runs to completion.
"""

from sqlalchemy import select

from app.core.constants import EscalationStatus, EscalationTrigger, ProjectStatus
from app.db.models import AuditLogEntry, Escalation, Presentation, Project, Report, Run
from app.orchestrator.escalation import resolve_escalation
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project


async def test_escalation_is_raised_and_resolution_completes_the_run(sessionmaker, bus):
    engine = e2e_engine(sessionmaker, bus, scripted_llm(ambiguous_scope=True))
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    # The run paused at the scoping escalation.
    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
        assert run.status == "paused"
        assert reloaded.status == ProjectStatus.awaiting_input.value
        assert escalation.status == EscalationStatus.open.value
        assert escalation.trigger == EscalationTrigger.ambiguous_scope.value
        escalation_id = escalation.id

    # The user answers; the run resumes and completes the whole pipeline.
    async with sessionmaker() as session:
        await resolve_escalation(session, escalation_id, {"resolutions": {"domain": "finance"}})
        await session.commit()
    await engine.resume(run_id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        reloaded = await session.get(Project, project.id)
        assert run.status == "complete"
        assert reloaded.status == ProjectStatus.complete.value

        # The resolution was merged into the persisted scope, not dropped.
        resolved = (reloaded.scope or {}).get("resolved_ambiguities") or []
        assert [r["choice"] for r in resolved] == ["finance"]

        # Both deliverables exist despite the mid-run pause.
        report = (
            (await session.execute(select(Report).where(Report.project_id == project.id)))
            .scalars()
            .one()
        )
        assert report.content_markdown
        (
            (
                await session.execute(
                    select(Presentation).where(Presentation.project_id == project.id)
                )
            )
            .scalars()
            .one()
        )

        # Raised and resolved are both on the durable audit record.
        actions = {
            action
            for (action,) in (
                await session.execute(
                    select(AuditLogEntry.action_type).where(AuditLogEntry.project_id == project.id)
                )
            ).all()
        }
        assert {"escalation_raised", "escalation_resolved"} <= actions

    raised = bus.of_type("escalation_raised")
    assert len(raised) == 1
    assert raised[0].payload["trigger"] == EscalationTrigger.ambiguous_scope.value
