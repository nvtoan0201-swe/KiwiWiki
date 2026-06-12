"""Shared helpers for the phase-5 tests: a grounded project corpus (sources,
analyses, comparison map, gaps, search-stopping record) and deterministic
responders for the report and presentation pipelines."""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ConfidenceLabel
from app.db.models import Comparison, Gap, Run, Source, StageExecution
from app.schemas.report import (
    OutlineSection,
    ReportOutline,
    ReportSection,
    SectionClaim,
    SelfCheckResult,
)
from tests.stage_utils import add_analysis, add_source

QUESTION = "Do transformers beat RNNs for time-series forecasting?"

# Matches both prompt styles: "## Audience: expert" and "Audience: expert."
_AUDIENCE_LINE = re.compile(r"Audience: (\w+)")
_SECTION_LINE = re.compile(r"Draft the section \*\*(.+?)\*\*")


def audience_from_prompt(messages: Sequence[dict[str, Any]]) -> str:
    match = _AUDIENCE_LINE.search(messages[-1]["content"])
    return match.group(1) if match else ""


def section_title_from_prompt(messages: Sequence[dict[str, Any]]) -> str:
    match = _SECTION_LINE.search(messages[-1]["content"])
    return match.group(1) if match else ""


async def seed_corpus(session: AsyncSession, project_id: str) -> list[Source]:
    """Two analyzed sources (roster indexes 0 and 1, pinned by relevance), a
    comparison with one contested point, one grounded gap, one future
    direction, and a completed literature-search execution that recorded the
    stopping condition."""
    first = await add_source(
        session, project_id, "Paper A", status="deep_read", topic="topic1", relevance=0.95
    )
    await add_analysis(session, first)
    second = await add_source(
        session, project_id, "Paper B", status="deep_read", topic="topic2", relevance=0.9
    )
    await add_analysis(session, second)

    session.add(
        Comparison(
            project_id=project_id,
            dimensions=[{"name": "horizon"}],
            matrix={"cells": []},
            consensus_points=[{"statement": "Attention helps long contexts."}],
            contested_points=[
                {
                    "statement": "Transformers beat RNNs on short horizons.",
                    "source_ids": [first.id, second.id],
                    "investigation": "The papers use different benchmark horizons.",
                    "resolution_type": "conditional",
                    "resolution": "It depends on the forecast horizon.",
                }
            ],
        )
    )
    session.add(
        Gap(
            project_id=project_id,
            description="No analyzed paper evaluates horizons beyond 30 days.",
            supporting_evidence={"source_ids": [first.id], "gap_type": "unanswered_question"},
            importance="high",
            confidence_label=ConfidenceLabel.emerging.value,
        )
    )
    session.add(
        Gap(
            project_id=project_id,
            description="Run a long-horizon benchmark across both families.",
            supporting_evidence={"type": "future_direction"},
            importance="medium",
            confidence_label=ConfidenceLabel.speculative.value,
        )
    )

    search_run = Run(project_id=project_id, status="complete")
    session.add(search_run)
    await session.flush()
    session.add(
        StageExecution(
            run_id=search_run.id,
            stage="literature_search",
            status="complete",
            started_at=datetime.datetime.now(datetime.UTC),
            summary={
                "stopping": "saturation",
                "saturation": {
                    "note": "New papers stopped introducing new ideas.",
                    "coverage": "thorough",
                },
            },
        )
    )
    await session.flush()
    return [first, second]


# --- report responders ------------------------------------------------------------


def expert_outline() -> ReportOutline:
    return ReportOutline(
        title="Transformers vs. RNNs: the state of the evidence",
        sections=[
            OutlineSection(title="Methodological landscape", purpose="methods", depth="deep"),
            OutlineSection(title="Evidence by horizon", purpose="evidence", depth="deep"),
            OutlineSection(title="Evidence quality", purpose="credibility", depth="standard"),
            OutlineSection(title="Where approaches agree", purpose="consensus", depth="standard"),
        ],
        tone_note="Precise hedging, methodology first, full citations.",
    )


def executive_outline() -> ReportOutline:
    return ReportOutline(
        title="Forecasting models: what to bet on",
        sections=[
            OutlineSection(title="Bottom line", purpose="decision", depth="brief"),
            OutlineSection(title="What this means for us", purpose="implications", depth="brief"),
        ],
        tone_note="Bottom line first, light citations.",
    )


def outline_responder(messages: Sequence[dict[str, Any]]) -> ReportOutline:
    return (
        executive_outline() if audience_from_prompt(messages) == "executive" else (expert_outline())
    )


def sourced_claim(index: int = 0, text: str | None = None) -> SectionClaim:
    return SectionClaim(
        text=text or f"Claim grounded in roster paper {index}.",
        source_indexes=[index],
        passage="accuracy of 0.91 (Sec. 4)",
        confidence_label=ConfidenceLabel.well_established,
        is_inference=False,
    )


def inference_claim(text: str = "The agent's own synthesis across both papers.") -> SectionClaim:
    return SectionClaim(
        text=text,
        source_indexes=[],
        passage=None,
        confidence_label=ConfidenceLabel.speculative,
        is_inference=True,
    )


def section_responder(messages: Sequence[dict[str, Any]]) -> ReportSection:
    """Expert sections carry two cited claims each; executive sections carry
    one cited claim and one inference — measurably different citation
    density for the audience-differentiation test."""
    title = section_title_from_prompt(messages)
    if audience_from_prompt(messages) == "executive":
        claims = [sourced_claim(0, f"{title}: the short answer."), inference_claim()]
    else:
        claims = [
            sourced_claim(0, f"{title}: finding from paper A."),
            sourced_claim(1, f"{title}: finding from paper B."),
        ]
    return ReportSection(title=title, lead_in=f"About {title.lower()}.", claims=claims)


def clean_self_check() -> SelfCheckResult:
    return SelfCheckResult(findings=[], summary="All claims supported and calibrated.")
