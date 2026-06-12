"""Phase 7 part D: source-adapter outages.

One adapter down → the search continues on the others and the outage is
audited. All adapters down → the agent does not fabricate a "saturated"
conclusion from empty results; it escalates, and the user's answer (retry once
the source is back, or stop) is honored.
"""

from sqlalchemy import select

from app.adapters.sources.fake import FakeSourceAdapter
from app.core.constants import EscalationTrigger, Stage
from app.db.models import AuditLogEntry, Escalation, Run, Source, StageExecution
from app.orchestrator.escalation import resolve_escalation
from tests.e2e.pipeline import corpus_adapter, e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project


async def test_one_adapter_down_search_continues_and_audits(sessionmaker, bus):
    adapters = [corpus_adapter(), FakeSourceAdapter("flaky", fail=True)]
    engine = e2e_engine(sessionmaker, bus, scripted_llm(), adapters=adapters)
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "complete"
        # The healthy adapter still produced the corpus.
        sources = (
            (await session.execute(select(Source).where(Source.project_id == project.id)))
            .scalars()
            .all()
        )
        assert len(sources) == 4
        # The outage is on the durable record.
        outage_audits = (
            (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.project_id == project.id,
                        AuditLogEntry.action_type == "error",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("flaky" in (e.description or "") for e in outage_audits)
        # No escalation: one adapter down is not a reason to interrupt the user.
        escalations = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .all()
        )
        assert escalations == []


async def test_all_adapters_down_escalates_then_retry_completes(sessionmaker, bus):
    down = corpus_adapter()
    down._fail = True
    engine = e2e_engine(sessionmaker, bus, scripted_llm(), adapters=[down])
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
        assert run.status == "paused"
        assert escalation.trigger == EscalationTrigger.thin_literature.value
        assert "unreachable" in escalation.question
        # No sources were invented from the outage.
        sources = (
            (await session.execute(select(Source).where(Source.project_id == project.id)))
            .scalars()
            .all()
        )
        assert sources == []
        escalation_id = escalation.id

    # The source comes back; the user says retry; the run completes fully.
    down._fail = False
    async with sessionmaker() as session:
        await resolve_escalation(session, escalation_id, {"selected_option": "retry"})
        await session.commit()
    await engine.resume(run_id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        assert run.status == "complete"
        searches = (
            (await session.execute(select(Source).where(Source.project_id == project.id)))
            .scalars()
            .all()
        )
        assert len(searches) == 4


async def test_all_adapters_down_user_stop_is_graceful(sessionmaker, bus):
    down = corpus_adapter()
    down._fail = True
    engine = e2e_engine(sessionmaker, bus, scripted_llm(), adapters=[down])
    project = await make_project(sessionmaker)

    run_id = await engine.start(project.id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        escalation = (
            (await session.execute(select(Escalation).where(Escalation.run_id == run_id)))
            .scalars()
            .one()
        )
        await resolve_escalation(session, escalation.id, {"selected_option": "stop"})
        await session.commit()

    await engine.resume(run_id)
    await engine.execute(run_id)

    async with sessionmaker() as session:
        run = await session.get(Run, run_id)
        # Graceful: a recorded user stop, not a crash or a failed run.
        assert run.status == "complete"
        assert run.stopping_criterion == "user_stopped"
        search_exec = (
            (
                await session.execute(
                    select(StageExecution).where(
                        StageExecution.run_id == run_id,
                        StageExecution.stage == Stage.literature_search.value,
                    )
                )
            )
            .scalars()
            .one()
        )
        assert search_exec.status == "complete"
        assert (search_exec.summary or {}).get("search_state", {}).get("stopped_on") == (
            "source_outage"
        )

    finished = bus.of_type("run_finished")
    assert finished[-1].payload["stopping_criterion"] == "user_stopped"
