"""SourceRouter: fan-out, failure tolerance, dedup, origin tracking, charging."""

from app.adapters.sources.fake import FakeSourceAdapter, make_hit
from app.adapters.sources.router import SourceRouter, dedup_key


def _charge_recorder():
    charges = []

    async def charge(amount: int, note: str) -> None:
        charges.append((amount, note))

    return charges, charge


async def test_dedup_by_doi_merges_and_records_origins():
    poorer = make_hit("a1", "Attention Is All You Need", doi="10.1/abc", adapter="alpha")
    poorer.abstract = None  # missing field → the other record is richer
    a = FakeSourceAdapter("alpha", default_results=[poorer])
    b = FakeSourceAdapter(
        "beta",
        default_results=[
            make_hit(
                "b9",
                "Attention is all you need",  # different casing + id, same DOI
                doi="10.1/ABC",
                abstract="The richer abstract with detail.",
                adapter="beta",
            )
        ],
    )
    router = SourceRouter([a, b])
    outcome = await router.search("transformers")

    assert outcome.total_raw_hits == 2
    assert len(outcome.merged) == 1
    merged = outcome.merged[0]
    assert set(merged.origins) == {"alpha", "beta"}
    # The richer record's fields win.
    assert merged.hit.abstract == "The richer abstract with detail."


async def test_dedup_by_title_year_author_without_doi():
    hit_a = make_hit("x1", "A Survey of Things!", year=2020, authors=["Jane Doe"], adapter="a")
    hit_a.doi = None
    hit_b = make_hit("x2", "a survey of things", year=2020, authors=["J. Doe"], adapter="b")
    hit_b.doi = None
    # Same normalized title/year; author last names match ("Doe").
    assert dedup_key(hit_a) == dedup_key(hit_b)

    distinct = make_hit("x3", "A survey of things", year=2021, authors=["Jane Doe"])
    distinct.doi = None
    assert dedup_key(hit_a) != dedup_key(distinct)


async def test_one_adapter_down_does_not_kill_search():
    healthy = FakeSourceAdapter("healthy", default_results=[make_hit("h1", "Paper One")])
    broken = FakeSourceAdapter("broken", fail=True)
    router = SourceRouter([healthy, broken])

    outcome = await router.search("anything")
    assert [m.hit.external_id for m in outcome.merged] == ["h1"]
    assert "broken" in outcome.failed_adapters


async def test_search_charges_one_call_per_adapter():
    charges, charge = _charge_recorder()
    adapters = [
        FakeSourceAdapter("a", default_results=[]),
        FakeSourceAdapter("b", default_results=[]),
    ]
    router = SourceRouter(adapters, charge=charge)
    await router.search("q")
    assert len(charges) == 2
    assert all(amount == 1 for amount, _ in charges)


async def test_graph_ops_prefer_graph_capable_adapter_and_fall_through():
    no_graph = FakeSourceAdapter("arxiv")  # empty references
    graph = FakeSourceAdapter("openalex", references_map={"W1": [make_hit("W2", "Cited work")]})
    charges, charge = _charge_recorder()
    router = SourceRouter([no_graph, graph], charge=charge)

    hits = await router.references({"arxiv": "1234.5", "openalex": "W1"})
    assert [h.external_id for h in hits] == ["W2"]
    # openalex is preferred for graph ops, so only one charged call.
    assert len(charges) == 1

    assert await router.citations({"arxiv": "1234.5"}) == []
