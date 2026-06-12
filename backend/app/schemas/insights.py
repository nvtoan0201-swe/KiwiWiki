"""Read schemas for the comparison (field map), gap, and provenance views."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sources import ContradictionRead


class ClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    label: str
    description: str | None
    defining_characteristics: list[Any] | dict[str, Any] | None


class ComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    dimensions: list[Any] | None
    matrix: list[Any] | dict[str, Any] | None
    consensus_points: list[Any] | None
    contested_points: list[Any] | None


class FieldMapRead(BaseModel):
    """`GET /projects/{id}/comparison` — everything the Field Map screen needs."""

    clusters: list[ClusterRead] = Field(default_factory=list)
    comparison: ComparisonRead | None = None
    contradictions: list[ContradictionRead] = Field(default_factory=list)


class GapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    description: str
    supporting_evidence: dict[str, Any] | None
    importance: str | None
    confidence_label: str | None


class ProvenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    claim_text: str
    source_id: str | None
    passage: str | None
    is_inference: bool
    confidence_label: str | None
    context: str
    ref_id: str | None
