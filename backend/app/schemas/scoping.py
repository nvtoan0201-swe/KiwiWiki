"""Scoping stage schemas: the LLM's scope proposal and its ambiguities."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AmbiguityOption(BaseModel):
    id: str = Field(..., description="Stable id the user's resolution refers to.")
    label: str
    description: str | None = None


class Ambiguity(BaseModel):
    id: str
    question: str
    why_it_matters: str | None = None
    material: bool = Field(
        True,
        description="True if resolving this differently would change what gets searched "
        "or how results are framed.",
    )
    options: list[AmbiguityOption] = Field(..., min_length=2, max_length=4)


class ProposedScope(BaseModel):
    time_window: str | None = Field(None, description="e.g. '2015–present'")
    included_subfields: list[str] = Field(default_factory=list)
    excluded_subfields: list[str] = Field(default_factory=list)
    depth: str | None = Field(None, description="e.g. 'survey' or 'deep dive'")


class ScopeProposal(BaseModel):
    research_question: str
    scope: ProposedScope
    audience: str | None = None
    outputs: list[str] = Field(default_factory=lambda: ["report"])
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    answerable_from_literature: bool
    answerability_reasoning: str
