"""The report self-check: a required review pass that can block completion.

The agent re-reads its own draft against the source records and reports every
claim that fails on support, calibration, fairness, or an un-flagged
assertion. Findings are *applied* — softened, removed, or re-grounded —
before the report row is persisted; an unsupported claim is never shipped.
Every decision is recorded in `reports.self_check_result` so the pass is
auditable.
"""

from __future__ import annotations

from typing import Any

from app.adapters.llm.prompt_loader import render_prompt
from app.schemas.report import ReportSection, SelfCheckFinding, SelfCheckResult
from app.stages.comparison.roster import AnalyzedSource, render_roster, valid_indexes
from app.stages.report.writer import LLMJson, normalize_claim

SELF_CHECK_PROMPT = "self_check_v1"


def render_draft(sections: list[ReportSection]) -> str:
    """The draft as numbered claims, so findings can address them exactly."""
    lines: list[str] = []
    for s_idx, section in enumerate(sections):
        lines.append(f"Section [{s_idx}]: {section.title}")
        for c_idx, claim in enumerate(section.claims):
            cited = ", ".join(str(i) for i in claim.source_indexes) or "none"
            passage = claim.passage or "none"
            lines.append(
                f"  Claim [{s_idx}.{c_idx}]: {claim.text}\n"
                f"    cites roster indexes: {cited}; passage: {passage}\n"
                f"    confidence: {claim.confidence_label.value}; "
                f"inference: {claim.is_inference}"
            )
    return "\n".join(lines)


async def run_self_check(
    llm_json: LLMJson, sections: list[ReportSection], roster: list[AnalyzedSource]
) -> SelfCheckResult:
    result: SelfCheckResult = await llm_json(
        [
            {
                "role": "user",
                "content": render_prompt(
                    SELF_CHECK_PROMPT,
                    draft=render_draft(sections),
                    roster=render_roster(roster),
                ),
            }
        ],
        SelfCheckResult,
        prompt_version=SELF_CHECK_PROMPT,
        note="report self-check",
        max_tokens=8192,
    )
    return result


def apply_findings(
    sections: list[ReportSection],
    result: SelfCheckResult,
    roster: list[AnalyzedSource],
) -> tuple[list[ReportSection], list[dict[str, Any]]]:
    """Apply the self-check's decisions and return (revised sections, action log).

    Rules:
    - `remove` drops the claim.
    - `soften` replaces the wording (and optionally downgrades the label); the
      claim is re-normalized, so a soften that leaves it unsourced flags it as
      inference rather than letting it ship bare.
    - `re_ground` re-cites the claim; if the supplied citation is invalid it
      degrades to `remove` — a claim that cannot be grounded does not ship.
    Findings addressing nonexistent claims are logged as `ignored`.
    """
    by_claim: dict[tuple[int, int], SelfCheckFinding] = {}
    log: list[dict[str, Any]] = []
    for raised in result.findings:
        key = (raised.section_index, raised.claim_index)
        if not (0 <= raised.section_index < len(sections)) or not (
            0 <= raised.claim_index < len(sections[raised.section_index].claims)
        ):
            log.append({**raised.model_dump(), "applied": "ignored_invalid_address"})
            continue
        by_claim[key] = raised  # last finding per claim wins

    revised: list[ReportSection] = []
    for s_idx, section in enumerate(sections):
        kept: list = []
        for c_idx, claim in enumerate(section.claims):
            finding = by_claim.get((s_idx, c_idx))
            if finding is None:
                kept.append(claim)
                continue
            entry = finding.model_dump()
            if finding.action == "remove":
                entry["applied"] = "removed"
                log.append(entry)
                continue
            if finding.action == "soften":
                updated = claim.model_copy(
                    update={
                        "text": finding.revised_text or claim.text,
                        "confidence_label": finding.revised_confidence or claim.confidence_label,
                    }
                )
                kept.append(normalize_claim(updated, roster))
                entry["applied"] = "softened"
                log.append(entry)
                continue
            # re_ground: only valid if the new citation actually resolves.
            cited = valid_indexes(finding.source_indexes, roster)
            if cited and finding.passage and finding.passage.strip():
                updated = claim.model_copy(
                    update={
                        "text": finding.revised_text or claim.text,
                        "source_indexes": [c.index for c in cited],
                        "passage": finding.passage,
                        "is_inference": False,
                        "confidence_label": finding.revised_confidence or claim.confidence_label,
                    }
                )
                kept.append(updated)
                entry["applied"] = "re_grounded"
            else:
                entry["applied"] = "removed_unresolvable_re_ground"
            log.append(entry)
        revised.append(section.model_copy(update={"claims": kept}))
    return revised, log


def result_payload(
    result: SelfCheckResult, log: list[dict[str, Any]], claims_checked: int
) -> dict[str, Any]:
    """The auditable `reports.self_check_result` jsonb."""
    return {
        "claims_checked": claims_checked,
        "findings": log,
        "clean": not log,
        "summary": result.summary,
        "prompt_version": SELF_CHECK_PROMPT,
    }
