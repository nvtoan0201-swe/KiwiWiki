"""Gap & future-directions stage schemas (phase 4 part B)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.constants import ConfidenceLabel, GapImportance

GapType = Literal[
    "unanswered_question",
    "untested_assumption",
    "method_combination",
    "unstudied_context",
]


class GapItem(BaseModel):
    description: str
    gap_type: GapType
    importance: GapImportance
    confidence_label: ConfidenceLabel
    evidence: str = Field(
        ..., description="The cluster/paper facts from the map that reveal this gap."
    )
    source_indexes: list[int] = Field(
        default_factory=list, description="Roster indexes of the papers the evidence rests on."
    )
    passage: str | None = Field(
        None, description="≤15-word quote or paraphrase + locator from a cited paper, if any."
    )


class FutureDirection(BaseModel):
    description: str
    rationale: str = Field(..., description="Which gap(s) this would address and how.")


class GapSynthesis(BaseModel):
    gaps: list[GapItem] = Field(default_factory=list)
    future_directions: list[FutureDirection] = Field(default_factory=list)
