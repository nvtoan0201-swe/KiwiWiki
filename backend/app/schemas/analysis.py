"""Paper-analysis stage schemas (phase 3): structured LLM outputs for tiered
reading, credibility scoring, and contradiction flagging.

Every extracted point that can surface in an output carries a `passage` — a
short quote (≤15 words) or a paraphrase + locator — so provenance can be
written alongside it. The agent's own critique is a separate field, never
blended into sourced content.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.constants import ConfidenceLabel


class ResultFinding(BaseModel):
    finding: str = Field(..., description="One key finding, stated plainly.")
    numbers: str | None = Field(
        None, description="The numbers behind it (effect size, accuracy, n, CI) if present."
    )
    passage: str = Field(
        ..., description="Supporting passage: quote of ≤15 words, or paraphrase + locator."
    )


class AuthorLimitation(BaseModel):
    limitation: str
    passage: str = Field(..., description="Where the authors state it (short quote or locator).")


class MissingReference(BaseModel):
    """A seminal work or subfield this paper leans on that may be absent from
    the collected sources."""

    name: str = Field(..., description="The work or subfield as the paper names it.")
    why_important: str
    search_terms: list[str] = Field(default_factory=list, max_length=4)


class DeepReadExtraction(BaseModel):
    core_claim: str
    core_claim_passage: str = Field(..., description="≤15-word quote or paraphrase + locator.")
    method: str
    method_passage: str
    results: list[ResultFinding] = Field(default_factory=list)
    datasets: list[str] = Field(
        default_factory=list, description="Datasets / experimental conditions used."
    )
    author_limitations: list[AuthorLimitation] = Field(default_factory=list)
    agent_critique: str = Field(
        ...,
        description=(
            "Weaknesses the authors did NOT admit — the agent's own inference, "
            "kept separate from the paper's content."
        ),
    )
    confidence_label: ConfidenceLabel = Field(
        ..., description="Confidence in the paper's central finding."
    )
    referenced_missing_works: list[MissingReference] = Field(default_factory=list)


class SkimExtraction(BaseModel):
    core_claim: str
    core_claim_passage: str
    method: str
    headline_result: str
    headline_result_passage: str
    confidence_label: ConfidenceLabel
    more_central_than_triage: bool = Field(
        False,
        description="True if the skim shows this paper is central enough to deserve a deep read.",
    )
    upgrade_reason: str | None = None


class CredibilityComponent(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    note: str = Field(..., description="What the score is based on; 'unknown' is acceptable.")
    known: bool = Field(
        True, description="False when the signal could not be determined from available data."
    )


class CredibilityAssessment(BaseModel):
    """Per-signal assessment; the scalar score is computed in code from these."""

    venue_quality: CredibilityComponent
    sample_size_power: CredibilityComponent
    methodology_rigor: CredibilityComponent
    conflicts_of_interest: CredibilityComponent
    replication_status: CredibilityComponent
    summary: str


class ContradictionFlag(BaseModel):
    candidate_index: int = Field(..., description="Index of the conflicting prior paper.")
    description: str = Field(
        ..., description="What the two papers disagree about — no winner picked."
    )


class ContradictionJudgment(BaseModel):
    flags: list[ContradictionFlag] = Field(default_factory=list)
