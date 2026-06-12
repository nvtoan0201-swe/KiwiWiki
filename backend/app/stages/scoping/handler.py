"""Scoping stage (phase 2A): turn the raw request into a confirmed research
question, escalating on material ambiguity or unanswerable questions.

Re-entry behavior:
- research question already persisted → Advance immediately (idempotent);
- escalation resolved → merge the user's resolutions into the proposal,
  persist, Advance;
- otherwise propose a scope via the LLM (the proposal is checkpointed into the
  stage execution so a resume does not repeat the call), escalating if needed.
"""

from __future__ import annotations

from typing import Any

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.core.constants import AuditActionType, EscalationTrigger, Stage
from app.orchestrator.handler import (
    Advance,
    Escalate,
    Fail,
    StageContext,
    StageHandler,
    StageResult,
)
from app.schemas.scoping import Ambiguity, ScopeProposal

PROMPT_VERSION = "scoping_v1"


class ScopingHandler(StageHandler):
    stage = Stage.scoping

    async def run(self, ctx: StageContext) -> StageResult:
        project = ctx.project

        if project.research_question and ctx.escalation_response is None:
            # Already scoped (resume after the work was done, or user-supplied).
            return Advance(summary={"research_question": project.research_question})

        proposal = await self._get_or_propose(ctx)

        if ctx.escalation_response is not None:
            return await self._apply_resolution(ctx, proposal, ctx.escalation_response)

        material = self._material_ambiguities(proposal)
        if not proposal.answerable_from_literature:
            return Escalate(
                trigger=EscalationTrigger.thin_literature,
                question=(
                    "This question may not be answerable from published literature: "
                    f"{proposal.answerability_reasoning} How should the agent proceed?"
                ),
                context={"proposal": proposal.model_dump()},
                options=[
                    {"id": "proceed_anyway", "label": "Search anyway and report what exists"},
                    {"id": "revise_question", "label": "Let me revise the question"},
                    {"id": "stop", "label": "Stop the project"},
                ],
            )
        if material:
            return Escalate(
                trigger=EscalationTrigger.ambiguous_scope,
                question=(
                    f"The request is ambiguous in {len(material)} way(s) that change "
                    "what gets researched. Please resolve them."
                ),
                context={"proposal": proposal.model_dump()},
                options=[a.model_dump() for a in material],
            )

        return await self._persist_and_advance(ctx, proposal, resolutions=None)

    # --- steps -----------------------------------------------------------------

    async def _get_or_propose(self, ctx: StageContext) -> ScopeProposal:
        cached = (ctx.stage_execution.summary or {}).get("proposal")
        if cached:
            return ScopeProposal.model_validate(cached)

        settings = get_settings()
        prompt = render_prompt(
            PROMPT_VERSION,
            original_request=ctx.project.original_request,
            audience=ctx.project.audience or "(not specified)",
            outputs_requested=", ".join(ctx.project.outputs_requested or []) or "(default)",
            scope_hints=ctx.project.scope or "(none)",
            sensitivity=settings.escalation_sensitivity,
        )
        proposal = await ctx.llm_json(
            [{"role": "user", "content": prompt}],
            ScopeProposal,
            prompt_version=PROMPT_VERSION,
            note="scoping proposal",
        )
        await ctx.checkpoint(
            {**(ctx.stage_execution.summary or {}), "proposal": proposal.model_dump()}
        )
        return proposal

    def _material_ambiguities(self, proposal: ScopeProposal) -> list[Ambiguity]:
        sensitivity = get_settings().escalation_sensitivity
        if sensitivity == "high":
            return list(proposal.ambiguities)
        if sensitivity == "low":
            # Borderline cases proceed with a noted assumption; only clearly
            # material forks escalate.
            return [a for a in proposal.ambiguities if a.material]
        return [a for a in proposal.ambiguities if a.material]

    async def _apply_resolution(
        self, ctx: StageContext, proposal: ScopeProposal, response: dict[str, Any]
    ) -> StageResult:
        if response.get("selected_option") == "stop":
            # The user chose to stop at the answerability escalation; the run
            # pauses for them to revise or archive. Mark that explicitly.
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.stopped,
                description="User chose not to proceed after the scoping escalation.",
                reasoning="The question was judged not answerable from literature.",
                run_id=ctx.run.id,
                stage=self.stage.value,
            )
            return Fail("Stopped at user request during scoping")

        resolutions = response.get("resolutions") or {}
        return await self._persist_and_advance(ctx, proposal, resolutions=resolutions)

    async def _persist_and_advance(
        self,
        ctx: StageContext,
        proposal: ScopeProposal,
        resolutions: dict[str, Any] | None,
    ) -> StageResult:
        project = ctx.project
        scope: dict[str, Any] = proposal.scope.model_dump()

        assumptions: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        for ambiguity in proposal.ambiguities:
            choice = (resolutions or {}).get(ambiguity.id)
            if choice is not None:
                label = next(
                    (o.label for o in ambiguity.options if o.id == str(choice)), str(choice)
                )
                resolved.append(
                    {"ambiguity": ambiguity.question, "choice": str(choice), "label": label}
                )
            else:
                # Non-material (or below-sensitivity) fork: proceed with the
                # first option as a noted assumption, never silently.
                assumptions.append(
                    {"ambiguity": ambiguity.question, "assumed": ambiguity.options[0].label}
                )
        if resolved:
            scope["resolved_ambiguities"] = resolved
        if assumptions:
            scope["noted_assumptions"] = assumptions

        project.research_question = proposal.research_question
        project.scope = scope
        project.audience = project.audience or proposal.audience
        project.outputs_requested = project.outputs_requested or proposal.outputs
        await ctx.session.flush()

        await ctx.audit.record(
            project_id=project.id,
            action_type=AuditActionType.stage_complete,
            description=f"Research question confirmed: {proposal.research_question}",
            reasoning=(
                "Scope was unambiguous."
                if not resolved
                else "User resolutions were merged into the scope."
            ),
            payload={"scope": scope, "assumptions": assumptions},
            run_id=ctx.run.id,
            stage=self.stage.value,
        )
        return Advance(
            summary={
                "research_question": proposal.research_question,
                "scope": scope,
                "resolved_ambiguities": resolved,
                "noted_assumptions": assumptions,
            }
        )
