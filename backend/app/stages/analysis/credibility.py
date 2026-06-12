"""Method-based credibility scoring (phase 3).

The LLM assesses five signals (venue, sample/power, rigor, conflicts,
replication); the scalar `sources.credibility_score` is computed *in code* as
a fixed weighted average, dominated by methodology and statistical power, so
assertive framing cannot move the number — only the method signals can. The
full per-signal breakdown is stored on `paper_analyses.credibility_breakdown`
for the UI and for downstream weighting.
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.llm.prompt_loader import render_prompt
from app.db.models import Source
from app.orchestrator.handler import StageContext
from app.schemas.analysis import CredibilityAssessment

PROMPT_VERSION = "credibility_v1"

# Method carries the score; venue and the discoverability signals are minor.
WEIGHTS: dict[str, float] = {
    "methodology_rigor": 0.35,
    "sample_size_power": 0.25,
    "venue_quality": 0.15,
    "replication_status": 0.15,
    "conflicts_of_interest": 0.10,
}


def scalar_score(assessment: CredibilityAssessment) -> float:
    total = sum(WEIGHTS[name] * getattr(assessment, name).score for name in WEIGHTS)
    return round(total, 3)


def breakdown(assessment: CredibilityAssessment) -> dict[str, Any]:
    return {
        "components": {name: getattr(assessment, name).model_dump() for name in WEIGHTS},
        "weights": WEIGHTS,
        "summary": assessment.summary,
        "score": scalar_score(assessment),
    }


async def assess_credibility(
    ctx: StageContext,
    source: Source,
    *,
    core_claim: str | None,
    method: str | None,
    results: Any,
    limitations: Any,
) -> CredibilityAssessment:
    prompt = render_prompt(
        PROMPT_VERSION,
        title=source.title,
        venue=source.venue or "(unknown venue)",
        year=source.year or "year unknown",
        core_claim=core_claim or "(not extracted)",
        method=method or "(not extracted)",
        results=json.dumps(results) if results else "(none extracted)",
        limitations=json.dumps(limitations) if limitations else "(none stated)",
    )
    return await ctx.llm_json(
        [{"role": "user", "content": prompt}],
        CredibilityAssessment,
        prompt_version=PROMPT_VERSION,
        note=f"credibility: {source.title[:50]}",
    )
