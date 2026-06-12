"""Phase 7 part B: the eval scorecard's deterministic gates, enforced in CI.

The scorecard measures the trust properties end to end (against fakes):
groundedness must be perfect — it is a correctness invariant — and the other
checks gate regressions in calibration, escalation judgment, saturation
behavior, self-check enforcement, and budget adherence.
"""

from eval.scorecard import run_all


async def test_eval_scorecard_gates():
    scorecard = await run_all()
    by_name = {r.name: r for r in scorecard.results}

    # Groundedness is an invariant: 100%, not a metric to optimize.
    groundedness = by_name["groundedness"]
    assert groundedness.score == 1.0, groundedness.details.get("violations")

    escalation = by_name["escalation_precision_recall"]
    assert escalation.details["precision"] == 1.0, escalation.details["false_escalations"]
    assert escalation.details["recall"] == 1.0, escalation.details["missed_escalations"]

    other_gates = (
        "confidence_calibration",
        "saturation_sanity",
        "self_check_efficacy",
        "budget_adherence",
    )
    for name in other_gates:
        result = by_name[name]
        assert result.passed, f"{name} failed its gate: {result.summary} {result.details}"

    assert scorecard.passed
    assert len(scorecard.results) == 6
