"""LLMClient wrapper: transient retry, JSON parse + schema validation, repair retry.

Covers Phase 0 acceptance criterion 5 against a mocked SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from app.adapters.llm.client import LLMClient
from app.core.errors import LLMError


class Scope(BaseModel):
    question: str
    answerable: bool


def _response(text: str, in_tok: int = 10, out_tok: int = 5) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok)
    return SimpleNamespace(content=[block], usage=usage)


class FakeMessages:
    """Scripted .create — each call runs the next behavior in the queue."""

    def __init__(self, behaviors: list[Callable[[], object]]) -> None:
        self._behaviors = behaviors
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        behavior = self._behaviors[self.calls]
        self.calls += 1
        return behavior()


class FakeClient:
    def __init__(self, behaviors: list[Callable[[], object]]) -> None:
        self.messages = FakeMessages(behaviors)


def _transient_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))


def test_retries_on_transient_error_then_succeeds() -> None:
    usages: list[tuple[int, int, str]] = []

    def fail() -> object:
        raise _transient_error()

    fake = FakeClient([fail, lambda: _response("hello")])
    llm = LLMClient(
        fake, model="m", on_usage=lambda i, o, m: usages.append((i, o, m)), backoff_base=0.0
    )

    out = llm.complete([{"role": "user", "content": "hi"}])

    assert out == "hello"
    assert fake.messages.calls == 2  # one failure + one success
    assert usages == [(10, 5, "m")]  # token accounting fired once, on success


def test_non_transient_error_maps_to_llm_error() -> None:
    def boom() -> object:
        raise ValueError("nope")

    llm = LLMClient(FakeClient([boom]), model="m", backoff_base=0.0)
    with pytest.raises(LLMError):
        llm.complete([{"role": "user", "content": "hi"}])


def test_complete_json_parses_and_validates() -> None:
    fake = FakeClient([lambda: _response('{"question": "Q?", "answerable": true}')])
    llm = LLMClient(fake, model="m", backoff_base=0.0)

    scope = llm.complete_json([{"role": "user", "content": "scope it"}], Scope)

    assert isinstance(scope, Scope)
    assert scope.question == "Q?" and scope.answerable is True


def test_complete_json_strips_code_fences() -> None:
    fenced = '```json\n{"question": "Q?", "answerable": false}\n```'
    llm = LLMClient(FakeClient([lambda: _response(fenced)]), model="m", backoff_base=0.0)
    scope = llm.complete_json([{"role": "user", "content": "x"}], Scope)
    assert scope.answerable is False


def test_complete_json_does_one_repair_retry() -> None:
    fake = FakeClient(
        [
            lambda: _response("not json at all"),
            lambda: _response('{"question": "Q?", "answerable": true}'),
        ]
    )
    llm = LLMClient(fake, model="m", backoff_base=0.0)

    scope = llm.complete_json([{"role": "user", "content": "x"}], Scope)

    assert scope.question == "Q?"
    assert fake.messages.calls == 2  # original + exactly one repair


def test_complete_json_raises_after_failed_repair() -> None:
    fake = FakeClient([lambda: _response("garbage"), lambda: _response("still garbage")])
    llm = LLMClient(fake, model="m", backoff_base=0.0)

    with pytest.raises(LLMError):
        llm.complete_json([{"role": "user", "content": "x"}], Scope)
    assert fake.messages.calls == 2  # original + one repair, then give up
