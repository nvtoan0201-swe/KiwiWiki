"""Live source-adapter integration (phase 2 acceptance 8).

Network-gated: set RUN_LIVE_SOURCE_TESTS=1 to run. Skipped in CI by default.
"""

from __future__ import annotations

import os

import pytest

from app.adapters.sources.openalex import OpenAlexAdapter

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_SOURCE_TESTS"),
    reason="live network test; set RUN_LIVE_SOURCE_TESTS=1 to run",
)


async def test_openalex_returns_normalized_results():
    adapter = OpenAlexAdapter()
    hits = await adapter.search("transformer neural network attention")

    assert hits, "expected at least one live result"
    for hit in hits:
        assert hit.adapter == "openalex"
        assert hit.external_id.startswith("W")
        assert hit.title
        assert hit.raw  # raw payload preserved
    # The classic paper should surface with normalized metadata somewhere.
    assert any(h.year and h.year >= 2017 for h in hits)
    assert any(h.doi for h in hits)
    assert any(h.abstract for h in hits)


async def test_openalex_citation_graph():
    adapter = OpenAlexAdapter()
    hits = await adapter.search("Attention is all you need")
    assert hits
    seed = hits[0]
    citations = await adapter.citations(seed.external_id)
    references = await adapter.references(seed.external_id)
    assert citations or references  # a known paper has graph edges
