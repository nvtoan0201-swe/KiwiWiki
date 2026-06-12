"""Test doubles for the LLM and embeddings, deterministic by construction.

`FakeLLM` mimics the `LLMClient` surface (`complete`, `complete_json`,
`set_usage_callback`). Responses are scripted per output schema: either a queue
of instances (the last one repeats when exhausted) or a callable receiving the
messages — useful for relevance triage, where the score must match the batch.

`KeywordEmbeddings` maps each text onto a one-hot axis per matched topic
keyword, so similarity is exactly 1.0 for same-topic texts and 0.0 across
topics — saturation and echo-chamber behavior become fully controllable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from app.adapters.embeddings.client import EmbeddingsProvider
from app.adapters.llm.client import UsageCallback
from app.schemas.search import RelevanceBatch, RelevanceScore

Responder = Callable[[Sequence[dict[str, Any]]], BaseModel]


class FakeLLM:
    def __init__(
        self,
        responses: dict[type[BaseModel], list[BaseModel] | Responder] | None = None,
        *,
        tokens_per_call: tuple[int, int] = (0, 0),
    ) -> None:
        self._responses: dict[type[BaseModel], list[BaseModel] | Responder] = responses or {}
        self._tokens = tokens_per_call
        self._on_usage: UsageCallback | None = None
        self.calls: list[type[BaseModel]] = []

    def set_usage_callback(self, on_usage: UsageCallback | None) -> None:
        self._on_usage = on_usage

    def complete(self, messages, **kwargs) -> str:
        self._account()
        return "ok"

    def complete_json(self, messages, schema, **kwargs):
        self._account()
        self.calls.append(schema)
        source = self._responses.get(schema)
        if source is None:
            raise AssertionError(f"FakeLLM has no scripted response for {schema.__name__}")
        if callable(source):
            return source(messages)
        if len(source) > 1:
            return source.pop(0)
        return source[0]

    def _account(self) -> None:
        if self._on_usage and (self._tokens[0] or self._tokens[1]):
            self._on_usage(self._tokens[0], self._tokens[1], "fake-model")


def llm_factory(fake: FakeLLM):
    """An engine/ctx `llm_factory` that wires the budget usage callback."""

    def factory(on_usage: UsageCallback | None) -> FakeLLM:
        fake.set_usage_callback(on_usage)
        return fake

    return factory


_PAPER_LINE = re.compile(r"^\[(\d+)\] (.+)$", re.MULTILINE)


def relevance_by_title(off_topic_marker: str = "Fringe") -> Responder:
    """Scores every presented paper 0.9 unless its title carries the marker."""

    def respond(messages: Sequence[dict[str, Any]]) -> RelevanceBatch:
        prompt = messages[-1]["content"]
        scores = []
        for match in _PAPER_LINE.finditer(prompt):
            index, title = int(match.group(1)), match.group(2)
            off = off_topic_marker in title
            scores.append(
                RelevanceScore(
                    index=index,
                    relevance=0.05 if off else 0.9,
                    reason="Off-topic by title marker." if off else "Directly relevant.",
                )
            )
        return RelevanceBatch(scores=scores)

    return respond


class KeywordEmbeddings(EmbeddingsProvider):
    def __init__(self, topics: list[str]) -> None:
        self._topics = topics

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * (len(self._topics) + 1)
            for i, topic in enumerate(self._topics):
                if topic in text:
                    vector[i] = 1.0
                    break
            else:
                vector[-1] = 1.0
            vectors.append(vector)
        return vectors
