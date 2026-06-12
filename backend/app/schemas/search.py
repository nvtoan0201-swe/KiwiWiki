"""Literature-search stage schemas: LLM structured outputs and the iteration /
saturation reporting shapes persisted in the stage summary."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SeedQueries(BaseModel):
    queries: list[str] = Field(..., min_length=2, max_length=8)
    rationale: str | None = None


class RelevanceScore(BaseModel):
    index: int = Field(..., description="Index of the paper in the presented batch.")
    relevance: float = Field(..., ge=0.0, le=1.0)
    reason: str


class RelevanceBatch(BaseModel):
    scores: list[RelevanceScore]


class ReformulatedQueries(BaseModel):
    strategy: str = Field(..., description="What is being changed and why.")
    queries: list[str] = Field(..., min_length=1, max_length=8)


class SaturationJudgment(BaseModel):
    new_ideas: bool = Field(
        ..., description="Did the latest batch introduce new methods/claims/framings?"
    )
    reasoning: str


class DiversityJudgment(BaseModel):
    homogeneous: bool = Field(
        ..., description="Does the collected set cluster around a single viewpoint?"
    )
    dominant_viewpoint: str | None = None
    counter_viewpoint_queries: list[str] = Field(default_factory=list, max_length=6)
    reasoning: str


class SearchIteration(BaseModel):
    """One pass of the search loop, persisted into the stage summary."""

    iteration: int
    queries: list[str]
    raw_hits: int
    new_sources: int
    duplicates: int
    low_relevance: int
    snowballed: int = 0
    novelty_share: float | None = None
    judge_new_ideas: bool | None = None
    saturation_state: str = "still finding new ideas"
    reformulated: bool = False
    reformulation_reason: str | None = None
    failed_adapters: dict[str, str] = Field(default_factory=dict)


class SaturationReport(BaseModel):
    saturated: bool
    consecutive_saturated: int
    last_novelty_share: float | None
    state: str  # "still finding new ideas" | "approaching saturation" | "saturated"
    coverage: str  # "thorough" | "thin"
    note: str
