"""Self-check efficacy: inject unsupported claims into a draft and measure the
catch rate of the enforcement layer.

Two mechanisms are measured, both deterministic:
1. `normalize_claim` — the writer's structural guard: a claim citing nothing
   valid (bad roster index, missing passage, no citation) must be flagged as
   inference before it can ship.
2. `apply_findings` — the self-check's edit application: remove drops the
   claim, soften re-normalizes it, and a re-ground with an unresolvable
   citation degrades to removal.

The LLM's semantic catch (a fluent claim citing a real source that doesn't
say that) is exercised by the LLM-gated suite, not this CI gate.
"""

from __future__ import annotations

from app.core.constants import ConfidenceLabel
from app.db.models import PaperAnalysis, Source
from app.schemas.report import ReportSection, SectionClaim, SelfCheckFinding, SelfCheckResult
from app.stages.comparison.roster import AnalyzedSource
from app.stages.report.self_check import apply_findings
from app.stages.report.writer import normalize_claim
from eval.scorecard import CheckResult

GATE = "100% of injected structurally-unsupported claims are flagged, edited, or removed"


def _roster() -> list[AnalyzedSource]:
    roster = []
    for i in range(2):
        source = Source(
            id=f"sc-{i}",
            project_id="sc",
            title=f"Self-check fixture paper {i}",
            credibility_score=0.8,
        )
        analysis = PaperAnalysis(id=f"sc-a-{i}", source_id=source.id, core_claim="fixture claim")
        roster.append(AnalyzedSource(index=i, source=source, analysis=analysis))
    return roster


def _claim(**overrides) -> SectionClaim:
    fields = {
        "text": "A claim.",
        "source_indexes": [0],
        "passage": "supported passage (Sec. 2)",
        "confidence_label": ConfidenceLabel.emerging,
        "is_inference": False,
    }
    fields.update(overrides)
    return SectionClaim(**fields)


async def check_self_check_efficacy() -> CheckResult:
    roster = _roster()
    outcomes: list[dict[str, object]] = []

    # --- layer 1: structural normalization at draft time -------------------------
    injected = {
        "invalid roster index": _claim(
            text="Cites a paper that does not exist.", source_indexes=[99]
        ),
        "citation without passage": _claim(text="Cites but quotes nothing.", passage=None),
        "no citation at all": _claim(text="Free-floating assertion.", source_indexes=[]),
    }
    for name, claim in injected.items():
        normalized = normalize_claim(claim, roster)
        outcomes.append({"injected": name, "caught": normalized.is_inference, "via": "normalize"})

    # Controls: a healthy sourced claim survives unflagged; an inference stays flagged.
    sourced_control = normalize_claim(_claim(text="Properly grounded."), roster)
    inference_control = normalize_claim(
        _claim(text="Own synthesis.", source_indexes=[], passage=None, is_inference=True), roster
    )
    controls_ok = not sourced_control.is_inference and inference_control.is_inference
    outcomes.append({"injected": "controls", "caught": controls_ok, "via": "normalize"})

    # --- layer 2: the self-check's findings force edits ---------------------------
    sections = [
        ReportSection(
            title="Findings",
            claims=[
                _claim(text="Overstated; must be removed."),
                _claim(text="Overstated; must be softened."),
                _claim(text="Wrongly grounded; re-ground will not resolve."),
                _claim(text="Healthy claim."),
            ],
        )
    ]
    findings = SelfCheckResult(
        summary="Three problems found.",
        findings=[
            SelfCheckFinding(
                section_index=0,
                claim_index=0,
                issue="unsupported",
                action="remove",
                note="No source supports this.",
            ),
            SelfCheckFinding(
                section_index=0,
                claim_index=1,
                issue="overstated",
                action="soften",
                note="Stronger than the evidence.",
                revised_text="The evidence weakly suggests this.",
                revised_confidence=ConfidenceLabel.speculative,
            ),
            SelfCheckFinding(
                section_index=0,
                claim_index=2,
                issue="unsupported",
                action="re_ground",
                note="Claims support that does not exist.",
                source_indexes=[99],
                passage=None,
            ),
        ],
    )
    revised, log = apply_findings(sections, findings, roster)
    revised_claims = revised[0].claims
    texts = [c.text for c in revised_claims]
    removed_ok = "Overstated; must be removed." not in texts
    softened = next((c for c in revised_claims if "weakly suggests" in c.text), None)
    softened_ok = softened is not None and softened.confidence_label is ConfidenceLabel.speculative
    reground_removed_ok = "Wrongly grounded; re-ground will not resolve." not in texts
    healthy_ok = "Healthy claim." in texts
    applied = {entry.get("applied") for entry in log}
    forced_edits_ok = {"removed", "softened", "removed_unresolvable_re_ground"} <= applied
    outcomes.extend(
        [
            {"injected": "remove finding", "caught": removed_ok, "via": "apply_findings"},
            {"injected": "soften finding", "caught": softened_ok, "via": "apply_findings"},
            {
                "injected": "unresolvable re-ground degrades to removal",
                "caught": reground_removed_ok,
                "via": "apply_findings",
            },
            {"injected": "healthy claim survives", "caught": healthy_ok, "via": "apply_findings"},
            {"injected": "edits are on the record", "caught": forced_edits_ok, "via": "log"},
        ]
    )

    caught = sum(1 for o in outcomes if o["caught"])
    score = caught / len(outcomes)
    return CheckResult(
        name="self_check_efficacy",
        passed=caught == len(outcomes),
        score=score,
        gate=GATE,
        summary=(
            f"{caught}/{len(outcomes)} injected/control cases handled correctly. "
            "Semantic (LLM-judged) catches are covered by the LLM-gated suite."
        ),
        details={"cases": outcomes},
    )
