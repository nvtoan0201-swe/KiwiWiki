"""OpenAlex adapter — https://docs.openalex.org/."""

from __future__ import annotations

from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit, SourceRecord
from app.adapters.sources.http import RateLimitedHTTP
from app.core.config import get_settings

_BASE = "https://api.openalex.org"
_PER_PAGE = 25


def _strip_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/").lower()


def _short_id(openalex_id: str) -> str:
    """`https://openalex.org/W123` → `W123`."""
    return openalex_id.rsplit("/", 1)[-1]


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        positions.extend((i, word) for i in indexes)
    positions.sort()
    return " ".join(word for _, word in positions) or None


class OpenAlexAdapter(SourceAdapter):
    name = "openalex"

    def __init__(self, http: RateLimitedHTTP | None = None) -> None:
        self._http = http or RateLimitedHTTP(self.name, min_interval=0.15)
        self._mailto = get_settings().openalex_mailto

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = dict(extra)
        if self._mailto:
            params["mailto"] = self._mailto
        return params

    def _to_hit(self, work: dict[str, Any]) -> SourceHit:
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        return SourceHit(
            external_id=_short_id(work.get("id", "")),
            title=work.get("display_name") or "(untitled)",
            authors=[
                (a.get("author") or {}).get("display_name", "")
                for a in work.get("authorships", [])
                if (a.get("author") or {}).get("display_name")
            ],
            venue=source.get("display_name"),
            year=work.get("publication_year"),
            doi=_strip_doi(work.get("doi")),
            url=location.get("landing_page_url") or work.get("id"),
            abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
            adapter=self.name,
            raw=work,
        )

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        params: dict[str, Any] = {"search": query, "per-page": _PER_PAGE}
        if filters:
            if filters.get("from_year"):
                params["filter"] = f"from_publication_date:{filters['from_year']}-01-01"
        data = await self._http.get_json(f"{_BASE}/works", self._params(params))
        return [self._to_hit(work) for work in data.get("results", [])]

    async def fetch(self, external_id: str) -> SourceRecord:
        work = await self._http.get_json(
            f"{_BASE}/works/{_short_id(external_id)}", self._params({})
        )
        hit = self._to_hit(work)
        return SourceRecord(
            external_id=hit.external_id,
            title=hit.title,
            authors=hit.authors,
            venue=hit.venue,
            year=hit.year,
            doi=hit.doi,
            url=hit.url,
            abstract=hit.abstract,
            references=[_short_id(r) for r in work.get("referenced_works", [])],
            citations=[],
            adapter=self.name,
            raw=work,
        )

    async def references(self, external_id: str) -> list[SourceHit]:
        work = await self._http.get_json(
            f"{_BASE}/works/{_short_id(external_id)}", self._params({})
        )
        referenced = [_short_id(r) for r in work.get("referenced_works", [])][:_PER_PAGE]
        if not referenced:
            return []
        data = await self._http.get_json(
            f"{_BASE}/works",
            self._params({"filter": f"openalex:{'|'.join(referenced)}", "per-page": _PER_PAGE}),
        )
        return [self._to_hit(w) for w in data.get("results", [])]

    async def citations(self, external_id: str) -> list[SourceHit]:
        data = await self._http.get_json(
            f"{_BASE}/works",
            self._params({"filter": f"cites:{_short_id(external_id)}", "per-page": _PER_PAGE}),
        )
        return [self._to_hit(w) for w in data.get("results", [])]
