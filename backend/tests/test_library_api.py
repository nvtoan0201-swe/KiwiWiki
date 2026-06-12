"""Tests for the source library + insights read endpoints (Phase 6 backend gap).

Covers: source listing/filtering, manual add, promote/exclude overrides (with
audit entries), analysis detail, field map, gaps, and provenance lookup.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Cluster,
    Comparison,
    Contradiction,
    Gap,
    PaperAnalysis,
    Provenance,
    Source,
)


async def _make_project(client: AsyncClient) -> str:
    resp = await client.post("/projects", json={"original_request": "Survey RAG methods."})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _seed_source(session: AsyncSession, project_id: str, **overrides) -> Source:
    fields = {
        "project_id": project_id,
        "title": "Retrieval-augmented generation for QA",
        "authors": ["A. Author"],
        "venue": "NeurIPS",
        "year": 2023,
        "discovery_channel": "keyword_search",
        "relevance_score": 0.9,
        "credibility_score": 0.7,
        "triage_status": "skimmed",
        "triage_reason": "Relevant but secondary.",
    }
    fields.update(overrides)
    source = Source(**fields)
    session.add(source)
    await session.commit()
    return source


@pytest.mark.asyncio
async def test_list_sources_filters_and_pages(client: AsyncClient, sessionmaker) -> None:
    pid = await _make_project(client)
    async with sessionmaker() as session:
        await _seed_source(session, pid)
        await _seed_source(
            session, pid, title="Echo chamber paper", triage_status="excluded", relevance_score=0.2
        )

    listing = (await client.get(f"/projects/{pid}/sources")).json()
    assert listing["total"] == 2
    assert listing["items"][0]["relevance_score"] >= listing["items"][1]["relevance_score"]

    filtered = (await client.get(f"/projects/{pid}/sources?triage_status=excluded")).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["title"] == "Echo chamber paper"

    searched = (await client.get(f"/projects/{pid}/sources?q=echo")).json()
    assert searched["total"] == 1

    missing = await client.get("/projects/nope/sources")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_manual_add_and_overrides_write_audit(client: AsyncClient, sessionmaker) -> None:
    pid = await _make_project(client)

    created = await client.post(
        f"/projects/{pid}/sources",
        json={"title": "A user-supplied preprint", "year": 2026, "doi": "10.1/abc"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["discovery_channel"] == "user_supplied"
    assert body["triage_status"] == "deep_read"

    async with sessionmaker() as session:
        source = await _seed_source(session, pid)

    promoted = await client.post(
        f"/sources/{source.id}/override", json={"action": "promote", "reason": "Looks central."}
    )
    assert promoted.status_code == 200
    assert promoted.json()["triage_status"] == "deep_read"
    assert promoted.json()["triage_reason"] == "Looks central."

    excluded = await client.post(f"/sources/{source.id}/override", json={"action": "exclude"})
    assert excluded.status_code == 200
    assert excluded.json()["triage_status"] == "excluded"

    audit = (await client.get(f"/projects/{pid}/audit")).json()
    descriptions = [e["description"] for e in audit["items"]]
    assert any("added source manually" in d for d in descriptions)
    assert any("promoted source" in d for d in descriptions)
    assert any("excluded source" in d for d in descriptions)
    override_entries = [e for e in audit["items"] if e["payload"] and "override" in e["payload"]]
    assert all(e["reasoning"] for e in override_entries)

    assert (
        await client.post("/sources/nope/override", json={"action": "promote"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_analysis_detail_includes_contradictions(client: AsyncClient, sessionmaker) -> None:
    pid = await _make_project(client)
    async with sessionmaker() as session:
        source = await _seed_source(session, pid, triage_status="deep_read")
        other = await _seed_source(session, pid, title="A conflicting paper")
        session.add(
            PaperAnalysis(
                source_id=source.id,
                core_claim="RAG improves factuality.",
                method="Benchmark comparison",
                results=[{"finding": "12% gain", "numbers": "12%", "passage": "Table 2 shows..."}],
                agent_critique="Sample is small; the gain may not generalize.",
                credibility_breakdown={"venue_quality": {"score": 0.8, "note": "Top venue"}},
                confidence_label="emerging",
            )
        )
        session.add(
            Contradiction(
                project_id=pid,
                source_a_id=source.id,
                source_b_id=other.id,
                description="Disagree on factuality gains.",
                resolved=False,
            )
        )
        await session.commit()
        source_id = source.id

    detail = (await client.get(f"/sources/{source_id}/analysis")).json()
    assert detail["source"]["id"] == source_id
    assert detail["analysis"]["core_claim"] == "RAG improves factuality."
    assert detail["analysis"]["confidence_label"] == "emerging"
    assert len(detail["contradictions"]) == 1

    # A source with no analysis yet returns the source with analysis: null.
    async with sessionmaker() as session:
        bare = await _seed_source(session, pid, title="Unanalyzed paper")
    bare_detail = (await client.get(f"/sources/{bare.id}/analysis")).json()
    assert bare_detail["analysis"] is None


@pytest.mark.asyncio
async def test_field_map_gaps_and_provenance(client: AsyncClient, sessionmaker) -> None:
    pid = await _make_project(client)
    async with sessionmaker() as session:
        source = await _seed_source(session, pid)
        cluster = Cluster(project_id=pid, label="Retrieval-first", description="RAG-centric work")
        session.add(cluster)
        session.add(
            Comparison(
                project_id=pid,
                dimensions=[{"name": "evaluation", "description": "How factuality is measured"}],
                matrix=[{"cells": []}],
                consensus_points=[
                    {"statement": "Retrieval helps", "confidence_label": "well_established"}
                ],
                contested_points=[{"statement": "How much it helps", "source_indexes": [0]}],
            )
        )
        gap = Gap(
            project_id=pid,
            description="No studies on multilingual corpora.",
            supporting_evidence={"type": "gap"},
            importance="high",
            confidence_label="emerging",
        )
        session.add(gap)
        await session.commit()
        session.add(
            Provenance(
                project_id=pid,
                claim_text="No studies on multilingual corpora.",
                source_id=source.id,
                passage="We only evaluate on English…",
                is_inference=False,
                confidence_label="emerging",
                context="gap",
                ref_id=gap.id,
            )
        )
        await session.commit()
        gap_id = gap.id

    field_map = (await client.get(f"/projects/{pid}/comparison")).json()
    assert len(field_map["clusters"]) == 1
    assert field_map["comparison"]["consensus_points"][0]["statement"] == "Retrieval helps"

    gaps = (await client.get(f"/projects/{pid}/gaps")).json()
    assert len(gaps) == 1
    assert gaps[0]["importance"] == "high"

    trace = (await client.get(f"/projects/{pid}/provenance", params={"ref_id": gap_id})).json()
    assert len(trace) == 1
    assert trace[0]["passage"].startswith("We only evaluate")
    assert trace[0]["is_inference"] is False

    empty = (await client.get(f"/projects/{pid}/provenance", params={"ref_id": "nothing"})).json()
    assert empty == []
