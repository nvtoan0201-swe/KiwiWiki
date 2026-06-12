"""Fan a query across enabled adapters and merge the results.

Deduplication: first by DOI, then by normalized title + year + first author's
last name. Duplicates merge into one record that keeps the richest field values
and remembers every origin adapter (and its external id) so snowballing can
pick whichever provider has a citation graph.

Every external call charges `search_calls` through the injected async `charge`
callback before it is made. One adapter failing (`SourceUnavailable`) is logged
and reported in the result; it never kills the search.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.sources.base import SourceAdapter, SourceHit
from app.core.errors import SourceUnavailable

logger = logging.getLogger("app.sources")

ChargeCallback = Callable[[int, str], Awaitable[None]]

# Preferred order for graph operations (references/citations).
_GRAPH_PREFERENCE = ["openalex", "semantic_scholar", "crossref", "arxiv", "fake"]

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalized_title(title: str) -> str:
    return _NON_ALNUM.sub("", title.lower())


def _first_author_key(authors: list[str]) -> str:
    if not authors:
        return ""
    # Last token of the first author ≈ family name; robust to "First Last".
    return authors[0].split()[-1].lower() if authors[0].split() else ""


def dedup_key(hit: SourceHit) -> str:
    if hit.doi:
        return f"doi:{hit.doi.lower()}"
    return f"meta:{normalized_title(hit.title)}:{hit.year or ''}:{_first_author_key(hit.authors)}"


_RICHNESS_FIELDS = ("title", "abstract", "venue", "year", "doi", "url", "authors")


def _richness(hit: SourceHit) -> int:
    return sum(1 for f in _RICHNESS_FIELDS if getattr(hit, f))


@dataclass(slots=True)
class MergedHit:
    """One deduplicated search result: the richest hit plus every origin."""

    hit: SourceHit
    origins: dict[str, str] = field(default_factory=dict)  # adapter name -> external id

    def absorb(self, other: SourceHit) -> None:
        self.origins.setdefault(other.adapter, other.external_id)
        if _richness(other) > _richness(self.hit):
            richer, poorer = other, self.hit
        else:
            richer, poorer = self.hit, other
        # Keep the richer record, fill its gaps from the poorer one.
        for field_name in _RICHNESS_FIELDS:
            if not getattr(richer, field_name) and getattr(poorer, field_name):
                setattr(richer, field_name, getattr(poorer, field_name))
        self.hit = richer


@dataclass(slots=True)
class SearchOutcome:
    merged: list[MergedHit]
    total_raw_hits: int
    failed_adapters: dict[str, str]  # adapter name -> error message


class SourceRouter:
    def __init__(self, adapters: list[SourceAdapter], *, charge: ChargeCallback | None = None):
        self._adapters = adapters
        self._charge = charge

    async def _charged(self, note: str) -> None:
        if self._charge is not None:
            await self._charge(1, note)

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> SearchOutcome:
        # Sequential on purpose: the charge callback writes through a DB session,
        # and AsyncSession is not safe under concurrent use. Adapters are
        # rate-limited anyway, so parallel fan-out buys little.
        results: list[list[SourceHit] | Exception] = []
        for adapter in self._adapters:
            try:
                await self._charged(f"search[{adapter.name}]: {query[:80]}")
                results.append(await adapter.search(query, filters))
            except SourceUnavailable as exc:
                results.append(exc)

        failed: dict[str, str] = {}
        merged: dict[str, MergedHit] = {}
        total = 0
        for adapter, result in zip(self._adapters, results, strict=True):
            if isinstance(result, Exception):
                failed[adapter.name] = str(result)
                logger.warning(
                    "adapter failed during search",
                    extra={"extra": {"adapter": adapter.name, "error": str(result)}},
                )
                continue
            total += len(result)
            for hit in result:
                key = dedup_key(hit)
                if key in merged:
                    merged[key].absorb(hit)
                else:
                    merged[key] = MergedHit(hit=hit, origins={hit.adapter: hit.external_id})
        return SearchOutcome(
            merged=list(merged.values()), total_raw_hits=total, failed_adapters=failed
        )

    async def references(self, origins: dict[str, str]) -> list[SourceHit]:
        return await self._graph_op("references", origins)

    async def citations(self, origins: dict[str, str]) -> list[SourceHit]:
        return await self._graph_op("citations", origins)

    async def _graph_op(self, op: str, origins: dict[str, str]) -> list[SourceHit]:
        """Try origin adapters in graph-capability order until one delivers."""
        by_name = {a.name: a for a in self._adapters}
        candidates = [
            name
            for name in sorted(
                origins,
                key=lambda n: (
                    _GRAPH_PREFERENCE.index(n) if n in _GRAPH_PREFERENCE else len(_GRAPH_PREFERENCE)
                ),
            )
            if name in by_name
        ]
        for name in candidates:
            adapter = by_name[name]
            try:
                await self._charged(f"{op}[{name}]")
                hits = await getattr(adapter, op)(origins[name])
            except SourceUnavailable as exc:
                logger.warning(
                    "adapter failed during graph op",
                    extra={"extra": {"adapter": name, "op": op, "error": str(exc)}},
                )
                continue
            if hits:
                return hits
        return []
