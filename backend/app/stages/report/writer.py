"""Report drafting: audience-shaped outline, section drafting, markdown render.

Shared by the report stage handler and the `/reports/{id}/rewrite` endpoint —
both go through the same pipeline (outline → sections → self-check) so a
rewrite is a real regeneration, never a paraphrase.

The LLM drafts *structured claims* (see `schemas/report.py`); markdown is
rendered here from that structure. That keeps citation markers and confidence
labels deterministic, and gives the self-check addressable claims to act on.
The contested-points, gaps and stopping-criterion sections are rendered from
the database rows directly — they are guaranteed present regardless of how the
model outlines the findings.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.prompt_loader import render_prompt
from app.core.constants import ConfidenceLabel, Stage, StoppingCriterion
from app.db.models import Comparison, Gap, Project, Run, StageExecution
from app.schemas.report import OutlineSection, ReportOutline, ReportSection, SectionClaim
from app.services import citations
from app.stages.comparison.roster import AnalyzedSource, render_roster, valid_indexes

OUTLINE_PROMPT = "report_outline_v1"
SECTION_PROMPT = "report_section_v1"

T = TypeVar("T", bound=BaseModel)

# Matches StageContext.llm_json; the rewrite service provides its own adapter.
LLMJson = Callable[..., Awaitable[Any]]

_LENGTH_NOTES = {
    "brief": "Keep the report brief: few sections, `brief` depth throughout.",
    "standard": "Standard length: a focused set of sections at standard depth.",
    "comprehensive": "Be comprehensive: cover every cluster and dimension, deeper sections.",
}


@dataclass(slots=True)
class ReportInputs:
    research_question: str
    audience: str
    scope: str
    field_map: str
    roster: list[AnalyzedSource]
    gaps: list[Gap]
    future_directions: list[Gap]
    contested_points: list[dict[str, Any]]
    stopping_criterion: str
    stopping_note: str
    length: str | None = None
    expand_section: str | None = None
    tone_note: str = ""
    extra_instructions: list[str] = field(default_factory=list)


def _is_future_direction(gap: Gap) -> bool:
    return (gap.supporting_evidence or {}).get("type") == "future_direction"


async def gather_inputs(
    session: AsyncSession,
    project: Project,
    *,
    audience: str,
    length: str | None = None,
    expand_section: str | None = None,
) -> ReportInputs:
    """Everything the writer needs, loaded from the grounded phase 0–4 data."""
    from app.stages.comparison.roster import load_project_roster

    roster = await load_project_roster(session, project.id)
    comparison = (
        await session.execute(
            select(Comparison)
            .where(Comparison.project_id == project.id)
            .order_by(Comparison.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    gap_rows = list(
        (
            await session.execute(
                select(Gap).where(Gap.project_id == project.id).order_by(Gap.created_at)
            )
        )
        .scalars()
        .all()
    )

    field_map = json.dumps(
        {
            "dimensions": comparison.dimensions if comparison else None,
            "matrix": comparison.matrix if comparison else None,
            "consensus_points": comparison.consensus_points if comparison else None,
            "contested_points": comparison.contested_points if comparison else None,
        },
        indent=2,
        default=str,
    )
    criterion, note = await _stopping_criterion(session, project.id)
    return ReportInputs(
        research_question=project.research_question or project.original_request,
        audience=audience,
        scope=json.dumps(project.scope or {}, default=str),
        field_map=field_map,
        roster=roster,
        gaps=[g for g in gap_rows if not _is_future_direction(g)],
        future_directions=[g for g in gap_rows if _is_future_direction(g)],
        contested_points=list((comparison.contested_points if comparison else None) or []),
        stopping_criterion=criterion,
        stopping_note=note,
        length=length,
        expand_section=expand_section,
    )


async def _stopping_criterion(session: AsyncSession, project_id: str) -> tuple[str, str]:
    """How the literature search ended — it signals output completeness."""
    execution = (
        (
            await session.execute(
                select(StageExecution)
                .join(Run, Run.id == StageExecution.run_id)
                .where(
                    Run.project_id == project_id,
                    StageExecution.stage == Stage.literature_search.value,
                    StageExecution.status == "complete",
                )
                .order_by(StageExecution.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    summary = (execution.summary or {}) if execution else {}
    stopped_on = summary.get("stopping")
    saturation = summary.get("saturation") or {}
    note = saturation.get("note") or "The search stopping condition was not recorded."
    coverage = saturation.get("coverage")

    valid = {c.value for c in StoppingCriterion}
    criterion = stopped_on if stopped_on in valid else StoppingCriterion.coverage.value
    detail = (
        f"The literature search stopped on **{stopped_on or 'an unrecorded condition'}**. "
        f"{note}"
    )
    if coverage:
        detail += f" Coverage was judged {coverage}."
    return criterion, detail


# --- LLM steps -------------------------------------------------------------------------


def _gaps_for_prompt(inputs: ReportInputs) -> str:
    lines = [f"- {g.description} (importance: {g.importance or 'n/a'})" for g in inputs.gaps]
    lines += [
        f"- (future direction, speculative) {g.description}" for g in inputs.future_directions
    ]
    return "\n".join(lines) or "(none recorded)"


async def plan_outline(llm_json: LLMJson, inputs: ReportInputs) -> ReportOutline:
    length_parts = []
    if inputs.length:
        length_parts.append(_LENGTH_NOTES.get(inputs.length, ""))
    if inputs.expand_section:
        length_parts.append(
            f"Expand the section titled '{inputs.expand_section}' with `deep` depth; "
            "keep the other sections as they are."
        )
    outline: ReportOutline = await llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    OUTLINE_PROMPT,
                    research_question=inputs.research_question,
                    audience=inputs.audience,
                    scope=inputs.scope,
                    length_note=" ".join(p for p in length_parts if p),
                    field_map=inputs.field_map,
                    gaps=_gaps_for_prompt(inputs),
                ),
            }
        ],
        ReportOutline,
        prompt_version=OUTLINE_PROMPT,
        note="report outline",
        max_tokens=4096,
    )
    inputs.tone_note = outline.tone_note
    return outline


async def draft_section(
    llm_json: LLMJson, inputs: ReportInputs, section: OutlineSection
) -> ReportSection:
    drafted: ReportSection = await llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    SECTION_PROMPT,
                    research_question=inputs.research_question,
                    audience=inputs.audience,
                    tone_note=inputs.tone_note,
                    section_title=section.title,
                    section_purpose=section.purpose,
                    section_depth=section.depth,
                    field_map=inputs.field_map,
                    roster=render_roster(inputs.roster),
                ),
            }
        ],
        ReportSection,
        prompt_version=SECTION_PROMPT,
        note=f"report section: {section.title}",
        max_tokens=8192,
    )
    drafted.title = drafted.title or section.title
    return drafted


# --- claim normalization & markdown render ----------------------------------------------


def normalize_claim(claim: SectionClaim, roster: list[AnalyzedSource]) -> SectionClaim:
    """Enforce the provenance invariant on one claim: a claim is *sourced* only
    with valid roster citations **and** a passage; anything else is flagged as
    inference rather than shipped unsourced."""
    cited = valid_indexes(claim.source_indexes, roster)
    sourced = bool(cited and claim.passage and claim.passage.strip())
    return claim.model_copy(
        update={
            "source_indexes": [c.index for c in cited],
            "is_inference": claim.is_inference or not sourced,
        }
    )


def claim_markdown(claim: SectionClaim, roster: list[AnalyzedSource]) -> str:
    cited = valid_indexes(claim.source_indexes, roster)
    markers = citations.citation_markers([c.source.id for c in cited])
    tag = citations.confidence_tag(claim.confidence_label, is_inference=claim.is_inference)
    return f"{claim.text}{markers} {tag}"


def render_markdown(
    inputs: ReportInputs, outline: ReportOutline, sections: list[ReportSection]
) -> str:
    parts: list[str] = [f"# {outline.title}", ""]
    parts.append(f"*Audience: {inputs.audience}.* {outline.tone_note}".rstrip())
    parts.append("")

    for section in sections:
        parts.append(f"## {section.title}")
        parts.append("")
        if section.lead_in:
            parts.append(citations.strip_markers(section.lead_in))
            parts.append("")
        for claim in section.claims:
            parts.append(claim_markdown(claim, inputs.roster))
            parts.append("")

    parts.extend(_contested_section(inputs))
    parts.extend(_gaps_section(inputs))
    parts.extend(
        [
            "## How this review was produced",
            "",
            inputs.stopping_note,
            "",
        ]
    )
    return "\n".join(parts).rstrip() + "\n"


def _contested_section(inputs: ReportInputs) -> list[str]:
    parts = [
        "## Contested points",
        "",
        "The literature disagrees on the points below. They are presented as open "
        "disagreements — the review does not resolve what the sources do not.",
        "",
    ]
    if not inputs.contested_points:
        parts.extend(["No contested points were recorded in the comparison.", ""])
        return parts
    tag = citations.confidence_tag(ConfidenceLabel.contested)
    for point in inputs.contested_points:
        markers = citations.citation_markers(list(point.get("source_ids") or []))
        line = f"- {point.get('statement', '')}{markers} {tag}"
        why = point.get("investigation")
        if why:
            line += f" Why they disagree: {why}"
        if point.get("resolution_type") == "conditional" and point.get("resolution"):
            line += f" Conditional reading: {point['resolution']}"
        else:
            line += " This disagreement is unresolved."
        parts.append(line)
    parts.append("")
    return parts


def _gaps_section(inputs: ReportInputs) -> list[str]:
    parts = ["## Gaps and future directions", ""]
    if inputs.gaps:
        parts.append("Gaps the analyzed literature leaves open:")
        parts.append("")
        for gap in inputs.gaps:
            evidence = gap.supporting_evidence or {}
            markers = citations.citation_markers(list(evidence.get("source_ids") or []))
            label = (
                ConfidenceLabel(gap.confidence_label)
                if gap.confidence_label
                else ConfidenceLabel.speculative
            )
            tag = citations.confidence_tag(label, is_inference=not evidence.get("source_ids"))
            importance = f" (importance: {gap.importance})" if gap.importance else ""
            parts.append(f"- {gap.description}{markers} {tag}{importance}")
        parts.append("")
    if inputs.future_directions:
        parts.append(
            "Future directions — these are the agent's own synthesis and are "
            "**speculative**, not established findings:"
        )
        parts.append("")
        tag = citations.confidence_tag(ConfidenceLabel.speculative, is_inference=True)
        for direction in inputs.future_directions:
            parts.append(f"- {direction.description} {tag}")
        parts.append("")
    if not inputs.gaps and not inputs.future_directions:
        parts.extend(["No gaps were recorded.", ""])
    return parts
