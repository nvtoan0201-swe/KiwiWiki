"""The literature-source adapter contract.

Concrete adapters (OpenAlex, arXiv, Semantic Scholar, Crossref) land in Phase 2;
this defines the ABC and the normalized record shapes they all return so the
rest of the system never sees provider-specific payloads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceHit:
    """A lightweight search result — enough to triage on (title + abstract)."""

    external_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    adapter: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceRecord:
    """A fully-resolved record for a single source, post-fetch."""

    external_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    full_text: str | None = None
    references: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    adapter: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """One external literature provider. Implementations must normalize into the
    shapes above and map provider failures to `SourceUnavailable`."""

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[SourceHit]:
        raise NotImplementedError

    @abstractmethod
    async def fetch(self, external_id: str) -> SourceRecord:
        raise NotImplementedError

    @abstractmethod
    async def references(self, external_id: str) -> list[SourceHit]:
        raise NotImplementedError

    @abstractmethod
    async def citations(self, external_id: str) -> list[SourceHit]:
        raise NotImplementedError
