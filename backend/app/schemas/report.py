"""Report-writing stage schemas (phase 5 part A).

The report is drafted as *structured claims*, not free prose: each non-obvious
claim carries its roster citations, a short supporting passage, and a
confidence label. Markdown is rendered from this structure, which is what
makes citation markers and confidence labels deterministic — and lets the
self-check act on individual claims (soften / remove / re-ground) before the
report row is finalized.

LLM outputs reference papers by their `index` in the numbered roster the
prompt presents (never raw ids — models invent ids).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.constants import ConfidenceLabel

SectionDepth = Literal["deep", "standard", "brief"]


class OutlineSection(BaseModel):
    title: str
    purpose: str = Field(..., description="What this section must convey to the audience.")
    depth: SectionDepth = "standard"


class ReportOutline(BaseModel):
    title: str = Field(..., description="Report title, pitched at the audience.")
    sections: list[OutlineSection] = Field(default_factory=list)
    tone_note: str = Field(
        "", description="One line on vocabulary/hedging choices made for this audience."
    )


class SectionClaim(BaseModel):
    text: str = Field(..., description="One claim or finding, phrased for the audience.")
    source_indexes: list[int] = Field(
        default_factory=list, description="Roster indexes of the papers this claim rests on."
    )
    passage: str | None = Field(
        None, description="≤15-word quote or paraphrase + locator from a cited paper, if any."
    )
    confidence_label: ConfidenceLabel
    is_inference: bool = Field(
        False, description="True when this is the agent's own synthesis, not a sourced fact."
    )


class ReportSection(BaseModel):
    title: str
    lead_in: str | None = Field(
        None, description="Optional connective prose. No factual claims allowed here."
    )
    claims: list[SectionClaim] = Field(default_factory=list)


SelfCheckIssue = Literal[
    "unsupported",
    "overstated",
    "unfair_disagreement",
    "unflagged_assertion",
]
SelfCheckAction = Literal["soften", "remove", "re_ground"]


class SelfCheckFinding(BaseModel):
    section_index: int
    claim_index: int
    issue: SelfCheckIssue
    action: SelfCheckAction
    note: str = Field(..., description="Why this claim fails review against the sources.")
    revised_text: str | None = Field(
        None, description="Replacement wording (required for soften/re_ground)."
    )
    revised_confidence: ConfidenceLabel | None = None
    source_indexes: list[int] = Field(
        default_factory=list, description="For re_ground: roster indexes that do support it."
    )
    passage: str | None = Field(
        None, description="For re_ground: the supporting passage from the cited paper."
    )


class SelfCheckResult(BaseModel):
    findings: list[SelfCheckFinding] = Field(default_factory=list)
    summary: str = Field(
        ..., description="Overall verdict: support, calibration, fairness of disagreements."
    )


# --- API schemas (viewer/editing support, consumed in Phase 6) ----------------------


class ReportRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    project_id: str
    audience: str | None = None
    content_markdown: str | None = None
    self_check_result: dict[str, Any] | None = None
    stopping_criterion: str | None = None
    version: int


class ReportPatch(BaseModel):
    content_markdown: str


class ReportRewriteRequest(BaseModel):
    audience: str | None = Field(None, description="Regenerate for this audience.")
    length: Literal["brief", "standard", "comprehensive"] | None = None
    expand_section: str | None = Field(
        None, description="Title of a section to expand with more depth."
    )
