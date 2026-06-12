"""Scorecard assembly: run every check, collect results, serialize the artifact."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    score: float  # 0.0–1.0
    gate: str  # the CI gate this check enforces, in words
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": round(self.score, 4),
            "gate": self.gate,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass(slots=True)
class Scorecard:
    results: list[CheckResult]
    generated_at: str

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "passed": self.passed,
            "checks": [r.to_dict() for r in self.results],
        }


async def run_all() -> Scorecard:
    # Imported here so `eval.scorecard` stays importable without the checks'
    # heavier dependencies (tests fixtures) resolved at module import time.
    from eval.checks.budget import check_budget_adherence
    from eval.checks.calibration import check_confidence_calibration
    from eval.checks.escalation import check_escalation_precision_recall
    from eval.checks.groundedness import check_groundedness
    from eval.checks.saturation import check_saturation_sanity
    from eval.checks.self_check import check_self_check_efficacy

    results = [
        await check_groundedness(),
        await check_confidence_calibration(),
        await check_escalation_precision_recall(),
        await check_saturation_sanity(),
        await check_self_check_efficacy(),
        await check_budget_adherence(),
    ]
    return Scorecard(
        results=results,
        generated_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )
