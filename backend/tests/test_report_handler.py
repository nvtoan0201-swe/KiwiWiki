"""Report-writing handler (phase 5 part A): grounded audience-pitched drafting,
the blocking self-check, the markdown output contract, and resumability."""

import pytest
from sqlalchemy import select

from app.core.constants import AuditActionType, ConfidenceLabel, Stage
from app.core.errors import BudgetExceeded
from app.db.models import AuditLogEntry, Provenance, Report
from app.orchestrator.handler import Advance
from app.schemas.report import (
    ReportOutline,
    ReportSection,
    SelfCheckFinding,
    SelfCheckResult,
)
from app.stages.report.handler import ReportWritingHandler
from tests.llm_fakes import FakeLLM
from tests.orchestrator_utils import make_project
from tests.report_utils import (
    QUESTION,
    clean_self_check,
    executive_outline,
    expert_outline,
    outline_responder,
    section_responder,
    seed_corpus,
)
from tests.stage_utils import make_ctx, new_execution
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


def report_llm(self_check: SelfCheckResult | None = None) -> FakeLLM:
    return FakeLLM(
        {
            ReportOutline: outline_responder,
            ReportSection: section_responder,
            SelfCheckResult: [self_check or clean_self_check()],
        }
    )


async def run_report(session, bus, project, llm):  # noqa: F811
    ctx = await make_ctx(session, bus, project, Stage.report_writing, llm)
    result = await ReportWritingHandler().run(ctx)
    report = (
        (await session.execute(select(Report).where(Report.project_id == project.id)))
        .scalars()
        .one()
    )
    return ctx, result, report


async def test_report_output_contract(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 2 + 7: inline citation markers, confidence labels, contested
    points as disagreement, gaps + speculative future directions, the
    stopping-criterion note, per-claim provenance, and `output_ready`."""
    project = await session.merge(
        await make_project(sessionmaker, research_question=QUESTION, audience="expert")
    )
    first, second = await seed_corpus(session, project.id)

    _, result, report = await run_report(session, bus, project, report_llm())

    assert isinstance(result, Advance)
    assert result.summary["version"] == 1
    assert result.summary["sections"] == 4
    assert result.summary["claims"] == 8

    content = report.content_markdown
    # Inline citation markers resolve to real source ids.
    assert f"[^src:{first.id}]" in content
    assert f"[^src:{second.id}]" in content
    # Confidence labels survive into the prose.
    assert "*(confidence: well established)*" in content
    # Contested points are presented as disagreement, with the why.
    assert "## Contested points" in content
    assert "Why they disagree: The papers use different benchmark horizons." in content
    assert "Conditional reading: It depends on the forecast horizon." in content
    # Gaps and future directions, the latter marked speculative inference.
    assert "## Gaps and future directions" in content
    assert "No analyzed paper evaluates horizons beyond 30 days." in content
    assert "(importance: high)" in content
    assert "Run a long-horizon benchmark across both families." in content
    assert "*(confidence: speculative; inference)*" in content
    # The stopping-criterion note records how the search ended.
    assert "## How this review was produced" in content
    assert "stopped on **saturation**" in content
    assert "Coverage was judged thorough." in content
    assert report.stopping_criterion == "saturation"
    assert report.self_check_result["clean"] is True
    assert report.self_check_result["claims_checked"] == 8

    # Every claim carries provenance: all eight expert claims are sourced.
    provenance = (
        (await session.execute(select(Provenance).where(Provenance.ref_id == report.id)))
        .scalars()
        .all()
    )
    assert len(provenance) == 8
    assert all(p.context == "report" for p in provenance)
    assert all(p.source_id and p.passage for p in provenance)

    ready = bus.of_type("output_ready")
    assert len(ready) == 1
    assert ready[0].payload == {"output": "report", "report_id": report.id, "version": 1}

    drafted = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.report_drafted.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(drafted) == 1 and drafted[0].reasoning


async def test_audience_changes_structure_and_citation_density(
    sessionmaker, session, bus  # noqa: F811
):
    """Acceptance 1: expert vs. executive produce measurably different outline
    shapes and citation density."""
    reports = {}
    for audience in ("expert", "executive"):
        project = await session.merge(
            await make_project(sessionmaker, research_question=QUESTION, audience=audience)
        )
        await seed_corpus(session, project.id)
        _, _, report = await run_report(session, bus, project, report_llm())
        reports[audience] = report

    expert, executive = reports["expert"].content_markdown, reports["executive"].content_markdown
    # Outline shape: the expert report has the four deep sections, the
    # executive report leads with the bottom line in two brief sections.
    assert all(f"## {s.title}" in expert for s in expert_outline().sections)
    assert all(f"## {s.title}" in executive for s in executive_outline().sections)
    assert "## Bottom line" not in expert
    assert "## Methodological landscape" not in executive
    # Citation density: full per-claim citations vs. light citations.
    assert expert.count("[^src:") > executive.count("[^src:")
    # The executive synthesis claim is flagged inference, not silently sourced.
    assert "*(confidence: speculative; inference)*" in executive


async def test_self_check_blocks_unsupported_claims(sessionmaker, session, bus):  # noqa: F811
    """Acceptance 3: a planted unsupported claim is caught by the self-check
    and removed (and an overstated one softened) before the row is finalized;
    `self_check_result` records the catch."""
    project = await session.merge(
        await make_project(sessionmaker, research_question=QUESTION, audience="expert")
    )
    await seed_corpus(session, project.id)

    check = SelfCheckResult(
        findings=[
            SelfCheckFinding(
                section_index=0,
                claim_index=0,
                issue="unsupported",
                action="remove",
                note="No roster paper supports this claim.",
            ),
            SelfCheckFinding(
                section_index=0,
                claim_index=1,
                issue="overstated",
                action="soften",
                note="Stated as settled; the evidence is emerging.",
                revised_text="Early evidence suggests paper B's finding holds.",
                revised_confidence=ConfidenceLabel.emerging,
            ),
        ],
        summary="One unsupported claim removed, one overstated claim softened.",
    )
    _, result, report = await run_report(session, bus, project, report_llm(check))

    content = report.content_markdown
    assert "Methodological landscape: finding from paper A." not in content  # removed
    assert "Early evidence suggests paper B's finding holds." in content  # softened
    assert "*(confidence: emerging)*" in content

    findings = report.self_check_result["findings"]
    assert {f["applied"] for f in findings} == {"removed", "softened"}
    assert report.self_check_result["clean"] is False
    assert report.self_check_result["claims_checked"] == 8
    assert result.summary["claims"] == 7
    assert result.summary["self_check_findings"] == 2

    audited = (
        (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action_type == AuditActionType.self_check_completed.value
                )
            )
        )
        .scalars()
        .one()
    )
    assert audited.payload["findings"] == findings


async def test_budget_stop_checkpoints_and_resume_continues(
    sessionmaker, session, bus  # noqa: F811
):
    """Invariants 4 + 5: a budget ceiling stops the draft gracefully with the
    checkpoint intact; resuming continues mid-draft without re-planning the
    outline or redrafting completed sections."""
    project = await session.merge(
        await make_project(
            sessionmaker,
            research_question=QUESTION,
            audience="expert",
            budget={"llm_tokens": 25},
        )
    )
    await seed_corpus(session, project.id)
    llm = report_llm()
    llm._tokens = (5, 5)  # 10 tokens per call: outline + 1 section fit under 25

    ctx = await make_ctx(session, bus, project, Stage.report_writing, llm)
    handler = ReportWritingHandler()
    with pytest.raises(BudgetExceeded):
        await handler.run(ctx)

    draft = ctx.stage_execution.summary["report_draft"]
    assert len(draft["sections"]) == 1  # outline + first section survived
    assert (
        await session.execute(select(Report).where(Report.project_id == project.id))
    ).scalars().first() is None  # nothing half-shipped

    project.budget = {"llm_tokens": 10_000}
    resumed_ctx = await make_ctx(session, bus, project, Stage.report_writing, llm)
    resumed_ctx.stage_execution = ctx.stage_execution  # same execution, as on resume
    result = await handler.run(resumed_ctx)

    assert isinstance(result, Advance)
    assert result.summary["sections"] == 4
    assert llm.calls.count(ReportOutline) == 1  # never re-planned
    # 1 completed + the call interrupted by the ceiling, then the 3 remaining
    # sections on resume — the checkpointed first section is never redrafted.
    assert llm.calls.count(ReportSection) == 5


async def test_report_stage_is_idempotent_on_reentry(sessionmaker, session, bus):  # noqa: F811
    project = await session.merge(
        await make_project(sessionmaker, research_question=QUESTION, audience="expert")
    )
    await seed_corpus(session, project.id)
    llm = report_llm()
    ctx, _, report = await run_report(session, bus, project, llm)

    result = await ReportWritingHandler().run(await new_execution(ctx))
    assert isinstance(result, Advance)
    assert result.summary == {"report_id": report.id, "version": 1, "resumed": True}
    count = len(
        (await session.execute(select(Report).where(Report.project_id == project.id)))
        .scalars()
        .all()
    )
    assert count == 1
