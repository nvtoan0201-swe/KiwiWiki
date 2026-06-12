"""Report rewrite: regenerate for a different audience/length or expand a
section (the `/reports/{id}/rewrite` endpoint).

A rewrite is a real regeneration through the same pipeline as the stage
handler — outline → sections → mandatory self-check → `persist_report` — so
the new version keeps every grounding guarantee: claims re-cite the stored
roster, provenance rows are attached, and unsupported claims are softened or
removed before the row exists. It never paraphrases the old markdown.

Rewrites run outside a run, so there is no run budget ledger to charge; the
LLM calls still go through the `adapters/llm` wrapper. If an expansion needs
*more evidence* than the project holds, that is a new run (loop-back), not a
rewrite — this module only re-authors what is already grounded.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditActionType, Stage
from app.core.errors import NotFound
from app.db.models import Project, Report
from app.events.bus import EventBus
from app.events.publisher import EventPublisher
from app.schemas.report import ReportRewriteRequest, ReportSection
from app.services.audit import AuditService
from app.stages.report import self_check as self_check_mod
from app.stages.report import writer
from app.stages.report.handler import persist_report


async def rewrite_report(
    session: AsyncSession,
    bus: EventBus,
    llm_json: writer.LLMJson,
    report: Report,
    request: ReportRewriteRequest,
) -> Report:
    project = await session.get(Project, report.project_id)
    if project is None:
        raise NotFound(f"Project {report.project_id} not found")

    audience = request.audience or report.audience or project.audience or "expert"
    inputs = await writer.gather_inputs(
        session,
        project,
        audience=audience,
        length=request.length,
        expand_section=request.expand_section,
    )

    outline = await writer.plan_outline(llm_json, inputs)
    sections: list[ReportSection] = []
    for planned in outline.sections:
        drafted = await writer.draft_section(llm_json, inputs, planned)
        drafted.claims = [writer.normalize_claim(c, inputs.roster) for c in drafted.claims]
        sections.append(drafted)

    check = await self_check_mod.run_self_check(llm_json, sections, inputs.roster)
    claims_checked = sum(len(s.claims) for s in sections)
    revised, log = self_check_mod.apply_findings(sections, check, inputs.roster)
    payload = self_check_mod.result_payload(check, log, claims_checked)

    new_report = await persist_report(session, project, inputs, outline, revised, payload)

    audit = AuditService(session, bus)
    await audit.record(
        project_id=project.id,
        action_type=AuditActionType.self_check_completed,
        description=(
            f"Rewrite self-check: {claims_checked} claims reviewed, "
            f"{len(log)} finding(s) applied"
        ),
        reasoning=check.summary,
        payload={"findings": log, "report_id": new_report.id},
        stage=Stage.report_writing.value,
    )
    await audit.record(
        project_id=project.id,
        action_type=AuditActionType.report_revised,
        description=f"Report rewritten as v{new_report.version} for {audience} audience",
        reasoning=(
            "User requested a rewrite; the report was regenerated through the full "
            "outline → draft → self-check pipeline, so provenance and confidence "
            "labels are preserved, not paraphrased."
        ),
        payload={
            "report_id": new_report.id,
            "from_report_id": report.id,
            "audience": audience,
            "length": request.length,
            "expand_section": request.expand_section,
        },
        stage=Stage.report_writing.value,
    )
    await EventPublisher(bus, project.id).emit(
        "output_ready",
        stage=Stage.report_writing.value,
        payload={"output": "report", "report_id": new_report.id, "version": new_report.version},
    )
    return new_report
