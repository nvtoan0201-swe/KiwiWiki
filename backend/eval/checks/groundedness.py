"""Groundedness check: every claim that reached an output carries resolvable
provenance (source + passage) or an explicit inference flag.

Runs the full pipeline against fakes, then audits the durable record: all
provenance rows in every context, plus the report's inline citations. This is
a correctness invariant, not a metric to optimize — the gate is 100%.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Provenance, Report, Source
from eval.scorecard import CheckResult
from eval.world import world
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project

GATE = "100% of output claims are sourced (resolvable source + passage) or inference-flagged"


async def check_groundedness() -> CheckResult:
    async with world() as w:
        engine = e2e_engine(w.sessionmaker, w.bus, scripted_llm())
        project = await make_project(w.sessionmaker)
        run_id = await engine.start(project.id)
        await engine.execute(run_id)

        async with w.sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(Provenance).where(Provenance.project_id == project.id)
                    )
                )
                .scalars()
                .all()
            )
            source_ids = {
                source_id
                for (source_id,) in (
                    await session.execute(select(Source.id).where(Source.project_id == project.id))
                ).all()
            }
            report = (
                (await session.execute(select(Report).where(Report.project_id == project.id)))
                .scalars()
                .one()
            )

    violations: list[dict[str, str]] = []
    for row in rows:
        sourced = (
            row.source_id is not None
            and row.source_id in source_ids
            and bool(row.passage and row.passage.strip())
        )
        if not sourced and not row.is_inference:
            violations.append(
                {"context": row.context, "claim": row.claim_text[:120], "reason": "unsourced"}
            )
        if row.source_id is not None and row.source_id not in source_ids:
            violations.append(
                {"context": row.context, "claim": row.claim_text[:120], "reason": "dangling source"}
            )

    from app.services.citations import cited_source_ids

    for cited in cited_source_ids(report.content_markdown or ""):
        if cited not in source_ids:
            violations.append(
                {"context": "report", "claim": f"citation {cited}", "reason": "dangling citation"}
            )

    total = len(rows)
    score = 1.0 if not violations else max(0.0, 1.0 - len(violations) / max(total, 1))
    by_context: dict[str, int] = {}
    for row in rows:
        by_context[row.context] = by_context.get(row.context, 0) + 1
    return CheckResult(
        name="groundedness",
        passed=not violations,
        score=score,
        gate=GATE,
        summary=(
            f"{total} provenance-carrying claims audited across {sorted(by_context)}; "
            f"{len(violations)} violation(s)."
        ),
        details={"claims_by_context": by_context, "violations": violations},
    )
