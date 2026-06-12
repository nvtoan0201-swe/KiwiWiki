"""Comparison dimensions (phase 4 A.2): derived from what the papers actually
contest — never from a template.

The LLM proposes dimensions grounded in the analyses and contradiction flags;
code rejects any dimension that fewer than two papers actually vary on (or
that shows fewer than two distinct observed values). Rejections are audited
so the field map's shape stays explainable.
"""

from __future__ import annotations

from typing import Any

from app.adapters.llm.prompt_loader import render_prompt
from app.core.constants import AuditActionType
from app.db.models import Contradiction
from app.orchestrator.handler import StageContext
from app.schemas.comparison import DimensionSet
from app.stages.comparison.roster import AnalyzedSource, render_roster, valid_indexes

PROMPT_VERSION = "dimensions_v1"


def render_contradictions(rows: list[Contradiction]) -> str:
    if not rows:
        return "(none flagged)"
    return "\n".join(f"- {row.description}" for row in rows)


async def derive_dimensions(
    ctx: StageContext,
    research_question: str,
    roster: list[AnalyzedSource],
    contradictions: list[Contradiction],
) -> list[dict[str, Any]]:
    proposal = await ctx.llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    PROMPT_VERSION,
                    research_question=research_question,
                    roster=render_roster(roster),
                    contradictions=render_contradictions(contradictions),
                ),
            }
        ],
        DimensionSet,
        prompt_version=PROMPT_VERSION,
        note="comparison dimensions",
    )

    accepted: list[dict[str, Any]] = []
    for dimension in proposal.dimensions:
        cited = valid_indexes(dimension.source_indexes, roster)
        distinct_values = {v.strip().lower() for v in dimension.values_observed if v.strip()}
        if len(cited) < 2 or len(distinct_values) < 2:
            await ctx.audit.record(
                project_id=ctx.project.id,
                action_type=AuditActionType.comparison_updated,
                description=f"Rejected comparison dimension '{dimension.name}'",
                reasoning=(
                    "No actual variation: a dimension must cite at least two papers "
                    "taking at least two distinct positions."
                ),
                payload={"dimension": dimension.model_dump()},
                run_id=ctx.run.id,
                stage=ctx.stage.value,
                emit_activity=False,
            )
            continue
        accepted.append(
            {
                "name": dimension.name,
                "description": dimension.description,
                "why_contested": dimension.why_contested,
                "source_ids": [c.source.id for c in cited],
                "values_observed": dimension.values_observed,
            }
        )
    return accepted
