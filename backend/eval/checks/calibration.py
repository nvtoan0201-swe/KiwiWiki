"""Confidence calibration on a labeled fixture set.

Ground-truth evidence strength is encoded in source credibility scores; the
deterministic guard under eval is the credibility cap (`capped_confidence`):
weak-evidence fixtures must never come out `well_established`, strong evidence
must not be spuriously downgraded, and unknown credibility must not be
invented. (The LLM's initial label assignment is exercised by the LLM-gated
suite, not by this CI gate.)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import ConfidenceLabel
from app.db.models import PaperAnalysis, Source
from app.stages.comparison.consensus import capped_confidence
from app.stages.comparison.roster import AnalyzedSource
from eval.scorecard import CheckResult

GATE = "every labeled fixture's final confidence label tracks its evidence strength"


@dataclass(slots=True)
class Fixture:
    name: str
    claimed: ConfidenceLabel
    credibilities: list[float | None]
    expected: ConfidenceLabel


FIXTURES = [
    Fixture(
        "weak evidence cannot stay well_established",
        ConfidenceLabel.well_established,
        [0.3, 0.35],
        ConfidenceLabel.emerging,
    ),
    Fixture(
        "borderline-weak evidence is downgraded",
        ConfidenceLabel.well_established,
        [0.55, 0.5],
        ConfidenceLabel.emerging,
    ),
    Fixture(
        "strong evidence keeps well_established",
        ConfidenceLabel.well_established,
        [0.85, 0.9],
        ConfidenceLabel.well_established,
    ),
    Fixture(
        "weak emerging claim stays emerging (no upgrade)",
        ConfidenceLabel.emerging,
        [0.3],
        ConfidenceLabel.emerging,
    ),
    Fixture(
        "contested stays contested regardless of credibility",
        ConfidenceLabel.contested,
        [0.95],
        ConfidenceLabel.contested,
    ),
    Fixture(
        "speculative stays speculative",
        ConfidenceLabel.speculative,
        [0.9],
        ConfidenceLabel.speculative,
    ),
    Fixture(
        "unknown credibility leaves the label honest",
        ConfidenceLabel.well_established,
        [None, None],
        ConfidenceLabel.well_established,
    ),
]


def _roster_for(credibilities: list[float | None]) -> list[AnalyzedSource]:
    roster = []
    for i, credibility in enumerate(credibilities):
        source = Source(
            id=f"cal-{i}",
            project_id="cal",
            title=f"Calibration fixture {i}",
            credibility_score=credibility,
        )
        analysis = PaperAnalysis(id=f"cal-a-{i}", source_id=source.id, core_claim="fixture")
        roster.append(AnalyzedSource(index=i, source=source, analysis=analysis))
    return roster


async def check_confidence_calibration() -> CheckResult:
    outcomes = []
    failures = []
    for fixture in FIXTURES:
        final, note = capped_confidence(fixture.claimed, _roster_for(fixture.credibilities))
        ok = final is fixture.expected
        outcomes.append(
            {
                "fixture": fixture.name,
                "claimed": fixture.claimed.value,
                "final": final.value,
                "expected": fixture.expected.value,
                "note": note,
                "ok": ok,
            }
        )
        if not ok:
            failures.append(fixture.name)

    score = (len(FIXTURES) - len(failures)) / len(FIXTURES)
    return CheckResult(
        name="confidence_calibration",
        passed=not failures,
        score=score,
        gate=GATE,
        summary=(
            f"{len(FIXTURES)} labeled fixtures; {len(failures)} miscalibrated. "
            "LLM label assignment itself is covered by the LLM-gated suite."
        ),
        details={"fixtures": outcomes, "failures": failures},
    )
