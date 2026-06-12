"""The one and only gateway to the Anthropic SDK.

Stage code must call this wrapper, never the SDK directly. It centralizes:
- retry/backoff on transient errors,
- token accounting (via an injectable `on_usage` callback feeding the budget
  ledger in Phase 1),
- structured-output parsing with exactly one repair retry,
- prompt-version tagging,
- mapping every failure to the typed `LLMError`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.config import get_settings
from app.core.errors import LLMError

logger = logging.getLogger("app.llm")

T = TypeVar("T", bound=BaseModel)

Message = dict[str, Any]
UsageCallback = Callable[[int, int, str], None]

# SDK exception types that are safe to retry.
_TRANSIENT: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _extract_text(response: Any) -> str:
    """Concatenate the text blocks of an Anthropic Message response."""
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
    return "".join(parts)


def _strip_code_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        end = s.rfind("```")
        if end != -1:
            s = s[:end]
    return s.strip()


class LLMClient:
    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        on_usage: UsageCallback | None = None,
        max_retries: int | None = None,
        backoff_base: float = 0.5,
    ) -> None:
        settings = get_settings()
        self._client = client if client is not None else self._build_client(settings)
        self._model = model or settings.agent_model
        self._on_usage = on_usage
        self._max_retries = max_retries if max_retries is not None else settings.llm_max_retries
        self._backoff_base = backoff_base

    @staticmethod
    def _build_client(settings: Any) -> anthropic.Anthropic:
        if settings.anthropic_api_key:
            return anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return anthropic.Anthropic()

    def set_usage_callback(self, on_usage: UsageCallback | None) -> None:
        """Wire token accounting after construction (the orchestrator does this per run)."""
        self._on_usage = on_usage

    # --- core call -----------------------------------------------------------

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        prompt_version: str | None = None,
    ) -> str:
        """One completion with retry/backoff and token accounting. Returns text."""
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self._max_retries:
            try:
                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "messages": list(messages),
                }
                if system is not None:
                    kwargs["system"] = system
                response = self._client.messages.create(**kwargs)
                self._account(response, prompt_version)
                return _extract_text(response)
            except Exception as exc:  # noqa: BLE001 — classified below
                last_exc = exc
                if _is_transient(exc) and attempt < self._max_retries:
                    delay = self._backoff_base * (2**attempt)
                    logger.warning(
                        "llm transient error, retrying",
                        extra={"extra": {"attempt": attempt, "error": str(exc)}},
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise LLMError(f"LLM call failed: {exc}") from exc
        # Unreachable, but keeps the type checker happy.
        raise LLMError(f"LLM call failed: {last_exc}")

    def complete_json(
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        prompt_version: str | None = None,
    ) -> T:
        """Completion constrained to a Pydantic schema, with one repair retry.

        The model is told to emit JSON only. We strip code fences, parse, and
        validate. On failure we make exactly one repair call quoting the error,
        then give up with an `LLMError`.
        """
        sys_prompt = self._json_system(system, schema)
        text = self.complete(
            messages, system=sys_prompt, max_tokens=max_tokens, prompt_version=prompt_version
        )
        parsed, error = self._try_parse(text, schema)
        if parsed is not None:
            return parsed

        repair_messages: list[Message] = [
            *messages,
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"Your previous output failed validation: {error}. "
                    "Return valid JSON only, with no prose and no code fences."
                ),
            },
        ]
        repaired = self.complete(
            repair_messages,
            system=sys_prompt,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
        )
        parsed, error = self._try_parse(repaired, schema)
        if parsed is not None:
            return parsed
        raise LLMError(
            f"LLM returned invalid JSON for {schema.__name__} after one repair", {"error": error}
        )

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _json_system(system: str | None, schema: type[T]) -> str:
        instructions = (
            "Respond with a single JSON object only — no prose, no markdown, no code fences. "
            f"It must validate against this JSON schema:\n{json.dumps(schema.model_json_schema())}"
        )
        return f"{system}\n\n{instructions}" if system else instructions

    @staticmethod
    def _try_parse(text: str, schema: type[T]) -> tuple[T | None, str | None]:
        cleaned = _strip_code_fences(text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON: {exc}"
        try:
            return schema.model_validate(data), None
        except PydanticValidationError as exc:
            return None, f"schema validation failed: {exc}"

    def _account(self, response: Any, prompt_version: str | None) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        logger.info(
            "llm usage",
            extra={
                "extra": {
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "model": self._model,
                    "prompt_version": prompt_version,
                }
            },
        )
        if self._on_usage is not None:
            self._on_usage(in_tok, out_tok, self._model)
