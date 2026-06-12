"""Report-writing stage (phase 5 part A).

Plans an audience-pitched outline, drafts section by section from the grounded
phase 0–4 data (every claim cited + confidence-labeled), then runs the
*required* self-check pass, which can force edits: unsupported claims are
softened, re-grounded, or removed before the `reports` row exists — never
shipped. The draft is checkpointed after every section, so a killed run
resumes mid-draft; a project that already has a report advances without
redrafting.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.constants import (
    AuditActionType,
    ProvenanceContext,
    Stage,
)
from app.core.errors import BudgetExceeded
from app.db.models import Project, Report
from app.orchestrator.handler import Advance, StageContext, StageHandler, StageResult
from app.schemas.report import ReportOutline, ReportSection
from app.services.provenance import ProvenanceService
from app.stages.comparison.roster import valid_indexes
from app.stages.report import self_check as self_check_mod
from app.stages.report import writer


class ReportWritingHandler(StageHandler):
    stage = Stage.report_writing

    async def run(self, ctx: StageContext) -> StageResult:
        existing = (
            (
                await ctx.session.execute(
                    select(Report)
                    .where(Report.project_id == ctx.project.id)
                    .order_by(Report.version.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return Advance(
                summary={"report_id": existing.id, "version": existing.version, "resumed": True}
            )

        audience = ctx.project.audience or "expert"
        inputs = await writer.gather_inputs(ctx.session, ctx.project, audience=audience)

        # Resume a partial draft if a prior execution checkpointed one.
        state = (ctx.stage_execution.summary or {}).get("report_draft") or {}
        outline = ReportOutline.model_validate(state["outline"]) if state.get("outline") else None
        sections = [ReportSection.model_validate(s) for s in state.get("sections", [])]

        try:
            if outline is None:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": f"Planning report structure for a {audience} audience"},
                )
                outline = await writer.plan_outline(ctx.llm_json, inputs)
                await self._checkpoint_draft(ctx, outline, sections)
            else:
                inputs.tone_note = outline.tone_note

            for planned in outline.sections[len(sections) :]:
                await ctx.events.emit(
                    "activity",
                    stage=self.stage.value,
                    payload={"description": f"Drafting section: {planned.title}"},
                )
                drafted = await writer.draft_section(ctx.llm_json, inputs, planned)
                drafted.claims = [writer.normalize_claim(c, inputs.roster) for c in drafted.claims]
                sections.append(drafted)
                await self._checkpoint_draft(ctx, outline, sections)

            await ctx.events.emit(
                "activity",
                stage=self.stage.value,
                payload={"description": "Self-check: reviewing the draft against the sources"},
            )
            check = await self_check_mod.run_self_check(ctx.llm_json, sections, inputs.roster)
        except BudgetExceeded:
            # The checkpointed draft survives; the run stops gracefully.
            raise

        claims_checked = sum(len(s.claims) for s in sections)
        revised, log = self_check_mod.apply_findings(sections, check, inputs.roster)
        payload = self_check_mod.result_payload(check, log, claims_checked)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.self_check_completed,
            description=(
                f"Report self-check: {claims_checked} claims reviewed, "
                f"{len(log)} finding(s) applied"
            ),
            reasoning=check.summary,
            payload={"findings": log},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )

        report = await persist_report(ctx.session, ctx.project, inputs, outline, revised, payload)
        await ctx.audit.record(
            project_id=ctx.project.id,
            action_type=AuditActionType.report_drafted,
            description=f"Report v{report.version} written for {audience} audience",
            reasoning=(
                "Drafted from the comparison map, gaps, and paper analyses; every claim "
                "carries provenance or an inference flag, and the self-check passed."
            ),
            payload={"report_id": report.id, "sections": len(revised)},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )
        await ctx.events.emit(
            "output_ready",
            stage=self.stage.value,
            payload={"output": "report", "report_id": report.id, "version": report.version},
        )
        return Advance(
            summary={
                "report_id": report.id,
                "version": report.version,
                "sections": len(revised),
                "claims": sum(len(s.claims) for s in revised),
                "self_check_findings": len(log),
            }
        )

    @staticmethod
    async def _checkpoint_draft(
        ctx: StageContext, outline: ReportOutline, sections: list[ReportSection]
    ) -> None:
        preserved = {
            k: v
            for k, v in (ctx.stage_execution.summary or {}).items()
            if k == "_loop_back_context"
        }
        await ctx.checkpoint(
            {
                **preserved,
                "report_draft": {
                    "outline": outline.model_dump(mode="json"),
                    "sections": [s.model_dump(mode="json") for s in sections],
                },
            }
        )


async def persist_report(
    session: Any,
    project: Project,
    inputs: writer.ReportInputs,
    outline: ReportOutline,
    sections: list[ReportSection],
    self_check_payload: dict[str, Any],
) -> Report:
    """Create the next-version `reports` row and attach per-claim provenance.

    Shared with the rewrite endpoint so a regenerated report keeps the same
    grounding guarantees as the original.
    """
    latest = (
        (
            await session.execute(
                select(Report.version)
                .where(Report.project_id == project.id)
                .order_by(Report.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    report = Report(
        project_id=project.id,
        audience=inputs.audience,
        content_markdown=writer.render_markdown(inputs, outline, sections),
        self_check_result=self_check_payload,
        stopping_criterion=inputs.stopping_criterion,
        version=(latest or 0) + 1,
    )
    session.add(report)
    await session.flush()

    provenance = ProvenanceService(session)
    for section in sections:
        for claim in section.claims:
            cited = valid_indexes(claim.source_indexes, inputs.roster)
            sourced = bool(cited and claim.passage and claim.passage.strip())
            await provenance.attach(
                project_id=project.id,
                claim_text=claim.text,
                context=ProvenanceContext.report,
                ref_id=report.id,
                source_id=cited[0].source.id if sourced else None,
                passage=claim.passage if sourced else None,
                is_inference=claim.is_inference or not sourced,
                confidence_label=claim.confidence_label,
            )
    return report
