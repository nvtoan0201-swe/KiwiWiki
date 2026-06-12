"""arXiv adapter — Atom API, http://export.arxiv.org/api/query.

arXiv has no citation graph, so `references`/`citations` return empty lists;
snowballing relies on the graph-bearing providers (OpenAlex, Semantic Scholar).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit, SourceRecord
from app.adapters.sources.http import RateLimitedHTTP
from app.core.errors import NotFound, SourceUnavailable

_BASE = "http://export.arxiv.org/api/query"
_MAX_RESULTS = 25
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _short_id(entry_id: str) -> str:
    """`http://arxiv.org/abs/2401.01234v2` → `2401.01234v2`."""
    return entry_id.rsplit("/abs/", 1)[-1]


class ArxivAdapter(SourceAdapter):
    name = "arxiv"

    def __init__(self, http: RateLimitedHTTP | None = None) -> None:
        # arXiv asks for no more than one request every 3 seconds.
        self._http = http or RateLimitedHTTP(self.name, min_interval=3.0)

    def _to_hit(self, entry: ET.Element) -> SourceHit:
        def text(path: str) -> str | None:
            node = entry.find(path, _NS)
            return node.text.strip() if node is not None and node.text else None

        entry_id = text("atom:id") or ""
        published = text("atom:published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        journal = text("arxiv:journal_ref")
        doi = text("arxiv:doi")
        return SourceHit(
            external_id=_short_id(entry_id),
            title=" ".join((text("atom:title") or "(untitled)").split()),
            authors=[
                node.text.strip()
                for node in entry.findall("atom:author/atom:name", _NS)
                if node.text
            ],
            venue=journal or "arXiv",
            year=year,
            doi=doi.lower() if doi else None,
            url=entry_id,
            abstract=" ".join((text("atom:summary") or "").split()) or None,
            adapter=self.name,
            raw={"atom_id": entry_id, "published": published, "journal_ref": journal},
        )

    def _parse_feed(self, xml_text: str) -> list[SourceHit]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise SourceUnavailable("arxiv returned malformed XML", {"adapter": self.name}) from exc
        return [self._to_hit(entry) for entry in root.findall("atom:entry", _NS)]

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        params = {
            "search_query": f"all:{query}",
            "max_results": _MAX_RESULTS,
            "sortBy": "relevance",
        }
        return self._parse_feed(await self._http.get_text(_BASE, params))

    async def fetch(self, external_id: str) -> SourceRecord:
        hits = self._parse_feed(
            await self._http.get_text(_BASE, {"id_list": external_id, "max_results": 1})
        )
        if not hits:
            raise NotFound(f"arXiv paper {external_id} not found")
        hit = hits[0]
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
            raw=hit.raw,
        )

    async def references(self, external_id: str) -> list[SourceHit]:
        return []  # no citation graph in the arXiv API

    async def citations(self, external_id: str) -> list[SourceHit]:
        return []  # no citation graph in the arXiv API
