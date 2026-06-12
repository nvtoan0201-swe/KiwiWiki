"""Presentation stage schemas (phase 5 part B).

The presentation is a re-authoring, not the report with bullets: a single
through-line is chosen first, 3–5 key messages serve it, and slides carry only
the evidence those messages need. Nuance lives in speaker notes. LLM outputs
cite papers by roster `index`, as in phases 4–5A.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

VisualType = Literal["comparison_table", "timeline", "trend", "bullet_set"]


class KeyMessage(BaseModel):
    message: str
    source_indexes: list[int] = Field(
        default_factory=list, description="Roster indexes of the papers behind this message."
    )


class ThroughLineResult(BaseModel):
    through_line: str = Field(..., description="The one synthesizing narrative of the deck.")
    key_messages: list[KeyMessage] = Field(..., min_length=3, max_length=5)


class VisualSpec(BaseModel):
    type: VisualType
    title: str | None = None
    columns: list[str] = Field(
        default_factory=list, description="Column headers (comparison_table / trend)."
    )
    rows: list[list[str]] = Field(
        default_factory=list,
        description="Table rows; for timeline each row is [when, what]; for trend [x, y].",
    )
    points: list[str] = Field(default_factory=list, description="Bullets for bullet_set.")


class EvidencePoint(BaseModel):
    text: str
    source_indexes: list[int] = Field(default_factory=list)
    passage: str | None = Field(
        None, description="≤15-word quote or paraphrase + locator from a cited paper, if any."
    )
    is_inference: bool = Field(False, description="True when this is the agent's own synthesis.")


class Slide(BaseModel):
    headline: str = Field(..., description="The slide's message as a full assertion, not a topic.")
    key_message_index: int | None = Field(
        None, description="Index of the key message this slide serves, if any."
    )
    evidence: list[EvidencePoint] = Field(default_factory=list)
    visual: VisualSpec | None = Field(
        None, description="Only when a visual communicates better than text."
    )
    speaker_notes: str | None = Field(
        None, description="The nuance moved out of the slide so it stays clean."
    )


class SlideDeck(BaseModel):
    slides: list[Slide] = Field(..., min_length=3)


# --- API schemas ---------------------------------------------------------------------


class PresentationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    project_id: str
    through_line: str | None = None
    key_messages: list[Any] | None = None
    slides: list[Any] | None = None
    speaker_notes: list[Any] | None = None
    version: int
