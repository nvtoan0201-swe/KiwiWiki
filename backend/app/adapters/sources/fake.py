"""A canned source adapter for deterministic tests (no network).

Search results can be a static mapping of query → hits, or a callable for
scripted scenarios (saturating corpora, echo chambers, per-iteration batches).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit, SourceRecord
from app.core.errors import NotFound, SourceUnavailable

SearchFn = Callable[[str], list[SourceHit]]


def make_hit(
    external_id: str,
    title: str,
    *,
    abstract: str | None = None,
    authors: list[str] | None = None,
    year: int | None = 2023,
    doi: str | None = None,
    venue: str | None = "Fake Journal",
    adapter: str = "fake",
) -> SourceHit:
    return SourceHit(
        external_id=external_id,
        title=title,
        authors=authors or ["Ada Lovelace"],
        venue=venue,
        year=year,
        doi=doi,
        url=f"https://example.org/{external_id}",
        abstract=abstract or f"Abstract of {title}.",
        adapter=adapter,
    )


class FakeSourceAdapter(SourceAdapter):
    def __init__(
        self,
        name: str = "fake",
        *,
        search_results: dict[str, list[SourceHit]] | SearchFn | None = None,
        default_results: list[SourceHit] | None = None,
        references_map: dict[str, list[SourceHit]] | None = None,
        citations_map: dict[str, list[SourceHit]] | None = None,
        fail: bool = False,
    ) -> None:
        self.name = name
        self._search_results = search_results
        self._default_results = default_results or []
        self._references_map = references_map or {}
        self._citations_map = citations_map or {}
        self._fail = fail
        self.search_calls: list[str] = []
        self.reference_calls: list[str] = []
        self.citation_calls: list[str] = []

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        if self._fail:
            raise SourceUnavailable(f"{self.name} is down", {"adapter": self.name})
        self.search_calls.append(query)
        if callable(self._search_results):
            return self._search_results(query)
        if isinstance(self._search_results, dict):
            return self._search_results.get(query, self._default_results)
        return self._default_results

    async def fetch(self, external_id: str) -> SourceRecord:
        if self._fail:
            raise SourceUnavailable(f"{self.name} is down", {"adapter": self.name})
        for hits in self._all_known():
            for hit in hits:
                if hit.external_id == external_id:
                    return SourceRecord(
                        external_id=hit.external_id,
                        title=hit.title,
                        authors=hit.authors,
                        venue=hit.venue,
                        year=hit.year,
                        doi=hit.doi,
                        url=hit.url,
                        abstract=hit.abstract,
                        adapter=self.name,
                    )
        raise NotFound(f"{external_id} not in fake corpus")

    def _all_known(self) -> list[list[SourceHit]]:
        known = [self._default_results]
        if isinstance(self._search_results, dict):
            known.extend(self._search_results.values())
        known.extend(self._references_map.values())
        known.extend(self._citations_map.values())
        return known

    async def references(self, external_id: str) -> list[SourceHit]:
        if self._fail:
            raise SourceUnavailable(f"{self.name} is down", {"adapter": self.name})
        self.reference_calls.append(external_id)
        return self._references_map.get(external_id, [])

    async def citations(self, external_id: str) -> list[SourceHit]:
        if self._fail:
            raise SourceUnavailable(f"{self.name} is down", {"adapter": self.name})
        self.citation_calls.append(external_id)
        return self._citations_map.get(external_id, [])
