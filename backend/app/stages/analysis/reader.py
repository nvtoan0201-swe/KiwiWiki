"""Tiered reading (phase 3): skim vs deep read, with bounded-concurrency
extraction.

Depths:
- skim (`TriageStatus.skimmed`) — core claim, method, headline result,
  confidence; cheap.
- deep read (`TriageStatus.deep_read`) — full structured extraction.

A skim that reports `more_central_than_triage` upgrades the paper to a deep
read (the upgrade is the caller's to record/audit).

Concurrency: extraction LLM calls for a batch run together via
`asyncio.to_thread` on the wrapper client. Token usage buffers in the budget
guard and is flushed once per batch — DB writes never happen off the handler
task, so the shared session stays safe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel

from app.adapters.llm.prompt_loader import render_prompt
from app.core.config import get_settings
from app.db.models import Source
from app.orchestrator.handler import StageContext
from app.schemas.analysis import DeepReadExtraction, SkimExtraction
from app.stages.analysis.fetch import FetchedText

DEEP_READ_PROMPT = "deep_read_v1"
SKIM_PROMPT = "skim_v1"

DEPTH_DEEP = "deep_read"
DEPTH_SKIM = "skim"


@dataclass(slots=True)
class ReadJob:
    source: Source
    fetched: FetchedText
    depth: str  # DEPTH_DEEP | DEPTH_SKIM


def _prompt(research_question: str, job: ReadJob) -> tuple[str, type[BaseModel], str]:
    settings = get_settings()
    name = DEEP_READ_PROMPT if job.depth == DEPTH_DEEP else SKIM_PROMPT
    schema: type[BaseModel] = DeepReadExtraction if job.depth == DEPTH_DEEP else SkimExtraction
    rendered = render_prompt(
        name,
        research_question=research_question,
        title=job.source.title,
        authors=", ".join(job.source.authors or []) or "(unknown)",
        venue=job.source.venue or "(unknown venue)",
        year=job.source.year or "year unknown",
        text_available=job.fetched.text_available,
        text=job.fetched.text[: settings.analysis_max_text_chars],
    )
    return rendered, schema, name


async def extract_batch(
    ctx: StageContext, research_question: str, jobs: list[ReadJob]
) -> list[DeepReadExtraction | SkimExtraction]:
    """Run a batch of extractions concurrently; one usage flush for the batch.

    Returns one extraction per job, in job order. Raises `BudgetExceeded` from
    the flush if the batch's tokens hit the ceiling (after the work is logged).
    """
    if not jobs:
        return []
    llm = ctx.llm  # built once, on the handler task

    async def one(job: ReadJob) -> DeepReadExtraction | SkimExtraction:
        prompt, schema, version = _prompt(research_question, job)

        def call() -> BaseModel:
            return llm.complete_json(
                [{"role": "user", "content": prompt}], schema, prompt_version=version
            )

        return cast(DeepReadExtraction | SkimExtraction, await asyncio.to_thread(call))

    try:
        return list(await asyncio.gather(*(one(job) for job in jobs)))
    finally:
        await ctx.budget.flush_llm_usage(f"extraction batch ({len(jobs)} papers)")
