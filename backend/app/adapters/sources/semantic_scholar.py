"""Semantic Scholar adapter — https://api.semanticscholar.org/graph/v1."""

from __future__ import annotations

from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit, SourceRecord
from app.adapters.sources.http import RateLimitedHTTP
from app.core.config import get_settings

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "title,authors,venue,year,externalIds,url,abstract"
_LIMIT = 25


class SemanticScholarAdapter(SourceAdapter):
    name = "semantic_scholar"

    def __init__(self, http: RateLimitedHTTP | None = None) -> None:
        api_key = get_settings().semantic_scholar_api_key
        headers = {"x-api-key": api_key} if api_key else None
        # Unauthenticated S2 is throttled hard; stay polite.
        self._http = http or RateLimitedHTTP(self.name, min_interval=1.1, headers=headers)

    def _to_hit(self, paper: dict[str, Any]) -> SourceHit:
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        return SourceHit(
            external_id=paper.get("paperId", ""),
            title=paper.get("title") or "(untitled)",
            authors=[a.get("name", "") for a in paper.get("authors", []) if a.get("name")],
            venue=paper.get("venue") or None,
            year=paper.get("year"),
            doi=doi.lower() if doi else None,
            url=paper.get("url"),
            abstract=paper.get("abstract"),
            adapter=self.name,
            raw=paper,
        )

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        params: dict[str, Any] = {"query": query, "fields": _FIELDS, "limit": _LIMIT}
        if filters and filters.get("from_year"):
            params["year"] = f"{filters['from_year']}-"
        data = await self._http.get_json(f"{_BASE}/paper/search", params)
        return [self._to_hit(p) for p in data.get("data", [])]

    async def fetch(self, external_id: str) -> SourceRecord:
        paper = await self._http.get_json(f"{_BASE}/paper/{external_id}", {"fields": _FIELDS})
        hit = self._to_hit(paper)
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
            raw=paper,
        )

    async def references(self, external_id: str) -> list[SourceHit]:
        data = await self._http.get_json(
            f"{_BASE}/paper/{external_id}/references",
            {"fields": _FIELDS, "limit": _LIMIT},
        )
        return [
            self._to_hit(item["citedPaper"])
            for item in data.get("data", [])
            if item.get("citedPaper", {}).get("paperId")
        ]

    async def citations(self, external_id: str) -> list[SourceHit]:
        data = await self._http.get_json(
            f"{_BASE}/paper/{external_id}/citations",
            {"fields": _FIELDS, "limit": _LIMIT},
        )
        return [
            self._to_hit(item["citingPaper"])
            for item in data.get("data", [])
            if item.get("citingPaper", {}).get("paperId")
        ]
