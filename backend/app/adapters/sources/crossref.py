"""Crossref adapter — https://api.crossref.org.

Crossref's `reference` lists are partial metadata (often DOI-only), so
`references` returns what exists without extra fetches; there is no reverse
citation endpoint, so `citations` returns empty.
"""

from __future__ import annotations

import re
from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit, SourceRecord
from app.adapters.sources.http import RateLimitedHTTP
from app.core.config import get_settings

_BASE = "https://api.crossref.org"
_ROWS = 25
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_jats(abstract: str | None) -> str | None:
    if not abstract:
        return None
    return " ".join(_TAG_RE.sub(" ", abstract).split()) or None


class CrossrefAdapter(SourceAdapter):
    name = "crossref"

    def __init__(self, http: RateLimitedHTTP | None = None) -> None:
        self._http = http or RateLimitedHTTP(self.name, min_interval=0.5)
        self._mailto = get_settings().crossref_mailto

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = dict(extra)
        if self._mailto:
            params["mailto"] = self._mailto
        return params

    def _to_hit(self, work: dict[str, Any]) -> SourceHit:
        title_list = work.get("title") or []
        authors = [
            " ".join(part for part in (a.get("given"), a.get("family")) if part)
            for a in work.get("author", [])
        ]
        year = None
        issued = (work.get("issued") or {}).get("date-parts") or []
        if issued and issued[0] and issued[0][0]:
            year = int(issued[0][0])
        doi = work.get("DOI")
        return SourceHit(
            external_id=doi or work.get("URL", ""),
            title=" ".join(title_list[0].split()) if title_list else "(untitled)",
            authors=[a for a in authors if a],
            venue=(work.get("container-title") or [None])[0],
            year=year,
            doi=doi.lower() if doi else None,
            url=work.get("URL"),
            abstract=_strip_jats(work.get("abstract")),
            adapter=self.name,
            raw=work,
        )

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        params: dict[str, Any] = {"query": query, "rows": _ROWS}
        if filters and filters.get("from_year"):
            params["filter"] = f"from-pub-date:{filters['from_year']}-01-01"
        data = await self._http.get_json(f"{_BASE}/works", self._params(params))
        items = (data.get("message") or {}).get("items", [])
        return [self._to_hit(work) for work in items]

    async def fetch(self, external_id: str) -> SourceRecord:
        data = await self._http.get_json(f"{_BASE}/works/{external_id}", self._params({}))
        work = data.get("message") or {}
        hit = self._to_hit(work)
        references = [ref["DOI"].lower() for ref in work.get("reference", []) if ref.get("DOI")]
        return SourceRecord(
            external_id=hit.external_id,
            title=hit.title,
            authors=hit.authors,
            venue=hit.venue,
            year=hit.year,
            doi=hit.doi,
            url=hit.url,
            abstract=hit.abstract,
            references=references,
            adapter=self.name,
            raw=work,
        )

    async def references(self, external_id: str) -> list[SourceHit]:
        data = await self._http.get_json(f"{_BASE}/works/{external_id}", self._params({}))
        work = data.get("message") or {}
        hits: list[SourceHit] = []
        for ref in work.get("reference", []):
            doi = ref.get("DOI")
            title = ref.get("article-title") or ref.get("volume-title")
            if not doi and not title:
                continue
            year = None
            if str(ref.get("year", "")).isdigit():
                year = int(ref["year"])
            hits.append(
                SourceHit(
                    external_id=(doi or title or "").lower(),
                    title=title or f"(reference {doi})",
                    authors=[ref["author"]] if ref.get("author") else [],
                    year=year,
                    doi=doi.lower() if doi else None,
                    adapter=self.name,
                    raw=ref,
                )
            )
        return hits[:_ROWS]

    async def citations(self, external_id: str) -> list[SourceHit]:
        return []  # Crossref has no cited-by endpoint in the public API
