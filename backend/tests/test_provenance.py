"""ProvenanceService enforces the sourced-or-flagged invariant (criterion 6)."""

from __future__ import annotations

import pytest

from app.core.constants import ConfidenceLabel, ProvenanceContext
from app.core.errors import ValidationError
from app.db.models import Project, Source
from app.services.provenance import ProvenanceService


async def _make_project(session) -> Project:
    project = Project(title="t", original_request="r", status="draft")
    session.add(project)
    await session.flush()
    return project


async def test_rejects_claim_without_source_or_inference(session) -> None:
    project = await _make_project(session)
    svc = ProvenanceService(session)
    with pytest.raises(ValidationError):
        await svc.attach(
            project_id=project.id,
            claim_text="An unsourced, un-flagged assertion.",
            context=ProvenanceContext.report,
        )


async def test_accepts_inference_flag(session) -> None:
    project = await _make_project(session)
    svc = ProvenanceService(session)
    row = await svc.attach(
        project_id=project.id,
        claim_text="This is the agent's own inference.",
        context=ProvenanceContext.analysis,
        is_inference=True,
        confidence_label=ConfidenceLabel.speculative,
    )
    assert row.is_inference is True
    assert row.source_id is None


async def test_accepts_source_passage_and_traces(session) -> None:
    project = await _make_project(session)
    source = Source(project_id=project.id, title="A cited paper")
    session.add(source)
    await session.flush()

    svc = ProvenanceService(session)
    await svc.attach(
        project_id=project.id,
        claim_text="Backed by a real passage.",
        context=ProvenanceContext.report,
        source_id=source.id,
        passage="quoted text from the paper",
        ref_id="ref-1",
    )
    traced = await svc.trace("ref-1")
    assert len(traced) == 1
    assert traced[0].claim_text == "Backed by a real passage."
    assert traced[0].source_id == source.id
    assert traced[0].is_inference is False
