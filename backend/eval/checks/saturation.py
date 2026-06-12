"""Saturation sanity: a saturating corpus stops the search on idea saturation
(before the iteration cap); a genuinely diverse corpus keeps searching to the
cap and says so. Guards against both "stop at N papers" regressions and
searches that never conclude.
"""

from __future__ import annotations

import itertools

from app.adapters.embeddings.client import EmbeddingsClient
from app.adapters.sources.fake import FakeSourceAdapter, make_hit
from app.core.constants import Stage
from app.orchestrator.handler import Advance
from app.schemas.search import (
    ReformulatedQueries,
    RelevanceBatch,
    SaturationJudgment,
    SeedQueries,
)
from app.stages.search.handler import LiteratureSearchHandler
from eval.scorecard import CheckResult
from eval.world import make_stage_ctx, override_settings, world
from tests.e2e.pipeline import corpus_adapter, relevance_responder
from tests.llm_fakes import FakeLLM, KeywordEmbeddings
from tests.orchestrator_utils import make_project
from tests.stage_utils import topic_embeddings

GATE = "saturating fixture stops on saturation before the cap; diverse fixture runs to the cap"


def _search_llm(judgments: list[SaturationJudgment]) -> FakeLLM:
    return FakeLLM(
        {
            SeedQueries: [SeedQueries(queries=["fixture query one", "fixture query two"])],
            ReformulatedQueries: [
                ReformulatedQueries(strategy="probe adjacent subtopics", queries=["fixture probe"])
            ],
            SaturationJudgment: judgments,
            RelevanceBatch: relevance_responder,
        }
    )


def _diverse_adapter() -> FakeSourceAdapter:
    counter = itertools.count(1)

    def results(query: str):
        i, j = next(counter), next(counter)
        return [
            make_hit(f"div-{i}", f"Divergent study {i}", abstract=f"A study of div{i} methods."),
            make_hit(f"div-{j}", f"Divergent study {j}", abstract=f"A study of div{j} methods."),
        ]

    return FakeSourceAdapter("fake", search_results=results)


async def _run_search(adapter: FakeSourceAdapter, fake, embeddings: EmbeddingsClient):
    async with world() as w:
        async with w.sessionmaker() as session:
            project = await session.merge(await make_project(w.sessionmaker))
            ctx = await make_stage_ctx(
                session, w.bus, project, Stage.literature_search, fake, embeddings=embeddings
            )
            result = await LiteratureSearchHandler(adapters=[adapter]).run(ctx)
            await session.commit()
    return result


async def check_saturation_sanity() -> CheckResult:
    checks: list[dict[str, object]] = []

    # Saturating fixture: every iteration returns the same papers.
    with override_settings(search_iteration_cap=4):
        judgments = [
            SaturationJudgment(new_ideas=True, reasoning="First batch brought new methods."),
            SaturationJudgment(new_ideas=False, reasoning="Only retreads."),
        ]
        result = await _run_search(corpus_adapter(), _search_llm(judgments), topic_embeddings())
    saturating_ok = (
        isinstance(result, Advance)
        and result.summary is not None
        and result.summary.get("stopping") == "saturation"
        and result.summary.get("iterations_run", 99) < 4
        and result.summary.get("saturation", {}).get("coverage") == "thorough"
    )
    checks.append(
        {
            "fixture": "saturating corpus",
            "ok": saturating_ok,
            "stopping": result.summary.get("stopping") if isinstance(result, Advance) else None,
            "iterations": (
                result.summary.get("iterations_run") if isinstance(result, Advance) else None
            ),
        }
    )

    # Diverse fixture: every query keeps surfacing genuinely new topics.
    with override_settings(search_iteration_cap=3):
        judgments = [SaturationJudgment(new_ideas=True, reasoning="Still new ideas.")]
        embeddings = EmbeddingsClient(provider=KeywordEmbeddings([f"div{i}" for i in range(1, 60)]))
        result = await _run_search(_diverse_adapter(), _search_llm(judgments), embeddings)
    diverse_ok = (
        isinstance(result, Advance)
        and result.summary is not None
        and result.summary.get("stopping") == "iteration_cap"
        and result.summary.get("iterations_run") == 3
        and "thin" in result.summary.get("saturation", {}).get("coverage", "")
    )
    checks.append(
        {
            "fixture": "diverse corpus",
            "ok": diverse_ok,
            "stopping": result.summary.get("stopping") if isinstance(result, Advance) else None,
            "iterations": (
                result.summary.get("iterations_run") if isinstance(result, Advance) else None
            ),
        }
    )

    passed = saturating_ok and diverse_ok
    return CheckResult(
        name="saturation_sanity",
        passed=passed,
        score=sum(1 for c in checks if c["ok"]) / len(checks),
        gate=GATE,
        summary=(
            "Saturating corpus "
            + ("stopped on saturation" if saturating_ok else "FAILED to stop on saturation")
            + "; diverse corpus "
            + ("ran to the cap and reported thin coverage" if diverse_ok else "FAILED")
            + "."
        ),
        details={"fixtures": checks},
    )
