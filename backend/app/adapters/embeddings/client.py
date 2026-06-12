"""Embeddings behind a provider-agnostic interface.

Phase 0 ships only a deterministic stub provider so dependent code has a stable
contract; real providers (Voyage, OpenAI, …) land in Phase 2 by implementing
`EmbeddingsProvider` and registering here.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

from app.core.config import get_settings

Vector = list[float]


class EmbeddingsProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[Vector]:
        """Return one unit-norm vector per input text."""
        raise NotImplementedError


class StubEmbeddingsProvider(EmbeddingsProvider):
    """Deterministic hash-based pseudo-embeddings — same text → same vector.

    Not semantically meaningful; it exists so Phase 0 code paths run end to end
    without a network embedding service. Phase 2 swaps in a real provider.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[Vector]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Vector:
        values: list[float] = []
        counter = 0
        while len(values) < self._dim:
            digest = hashlib.sha256(f"{text}:{counter}".encode()).digest()
            values.extend(b / 255.0 for b in digest)
            counter += 1
        vec = values[: self._dim]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _build_provider() -> EmbeddingsProvider:
    settings = get_settings()
    # Only the stub exists today; the switch is where real providers attach.
    return StubEmbeddingsProvider(dim=settings.embedding_dim)


class EmbeddingsClient:
    def __init__(self, provider: EmbeddingsProvider | None = None) -> None:
        self._provider = provider or _build_provider()

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        return self._provider.embed(texts)
