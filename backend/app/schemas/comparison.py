"""Comparative-analysis stage schemas (phase 4 part A).

LLM outputs reference papers by their `index` in the numbered roster the
prompt presents (never raw ids — models invent ids). Code maps indexes back
to source rows and rejects out-of-range references.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.constants import ConfidenceLabel


class ClusterCharacterization(BaseModel):
    cluster_index: int = Field(..., description="Index of the presented candidate group.")
    label: str = Field(..., description="A short name for the school of thought / approach.")
    description: str
    defining_characteristics: list[str] = Field(default_factory=list)
    bridging_source_indexes: list[int] = Field(
        default_factory=list,
        description="Roster indexes of members that also bridge to other clusters.",
    )


class ClusterNaming(BaseModel):
    clusters: list[ClusterCharacterization]


class Dimension(BaseModel):
    name: str
    description: str
    why_contested: str = Field(
        ..., description="What in the analyses/contradictions shows the field varies on this."
    )
    source_indexes: list[int] = Field(
        default_factory=list,
        description="Roster indexes of papers that actually take different positions on it.",
    )
    values_observed: list[str] = Field(
        default_factory=list,
        description="The distinct positions/values papers take on this dimension.",
    )


class DimensionSet(BaseModel):
    dimensions: list[Dimension] = Field(default_factory=list)


class MatrixCell(BaseModel):
    dimension_index: int
    summary: str = Field(..., description="How this cluster sits on this dimension.")
    source_indexes: list[int] = Field(default_factory=list)
    passage: str | None = Field(
        None, description="≤15-word quote or paraphrase + locator from a cited paper."
    )
    confidence_label: ConfidenceLabel
    empty: bool = Field(
        False, description="True when the cluster's papers simply don't speak to this dimension."
    )


class MatrixRow(BaseModel):
    cells: list[MatrixCell]


class ConsensusPoint(BaseModel):
    statement: str
    source_indexes: list[int] = Field(default_factory=list)
    passage: str | None = None
    confidence_label: ConfidenceLabel


class ContestedPoint(BaseModel):
    statement: str
    source_indexes: list[int] = Field(default_factory=list)
    contradiction_index: int | None = Field(
        None, description="Index of the listed open contradiction this corresponds to, if any."
    )


class ConsensusPartition(BaseModel):
    consensus_points: list[ConsensusPoint] = Field(default_factory=list)
    contested_points: list[ContestedPoint] = Field(default_factory=list)


class Investigation(BaseModel):
    why: str = Field(
        ..., description="Why the sources disagree: datasets, metrics, populations, periods…"
    )
    resolution_type: Literal["conditional", "unresolved"]
    resolution: str | None = Field(
        None,
        description=(
            "For 'conditional': the honest conditional answer "
            "('A wins when X; B when Y'). None when unresolved."
        ),
    )
    confidence_label: ConfidenceLabel
