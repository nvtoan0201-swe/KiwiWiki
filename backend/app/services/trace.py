"""Per-run tracing (phase 7 part C).

The trace id is the run id. Stage executions are the coarse spans; this
service records the fine-grained ones — every LLM call (model, prompt
version, exact token usage, duration) and every external source call
(adapter, operation) — as durable `trace_events` rows on the same session the
stage step commits.

Token attribution works through `llm_call_sink`, a contextvar holding a
per-call accumulator: `StageContext.llm_json/llm_text` set it around the
wrapper call, and `BudgetGuard.note_llm_usage` (invoked synchronously inside
the call, in the same context even across `asyncio.to_thread`) adds the exact
usage to it. Concurrent LLM calls therefore never cross-attribute tokens.
"""

from __future__ import annotations

import datetime
import re
from contextvars import ContextVar
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TraceEvent

KIND_LLM_CALL = "llm_call"
KIND_SOURCE_CALL = "source_call"


class LLMCallSink(TypedDict):
    input_tokens: int
    output_tokens: int
    model: str | None
    sdk_calls: int


llm_call_sink: ContextVar[LLMCallSink | None] = ContextVar("llm_call_sink", default=None)


def new_sink() -> LLMCallSink:
    return {"input_tokens": 0, "output_tokens": 0, "model": None, "sdk_calls": 0}


# Source-call notes are formatted `op[adapter]: detail` (router) by the call
# sites this service traces.
_SOURCE_NOTE = re.compile(r"^(?P<op>[a-z_]+)\[(?P<adapter>[^\]]+)\](?::\s*(?P<detail>.*))?$")


class TraceService:
    def __init__(self, session: AsyncSession, run_id: str) -> None:
        self._session = session
        self._run_id = run_id

    def _add(
        self,
        kind: str,
        stage: str | None,
        payload: dict[str, Any],
        duration_ms: float | None = None,
    ) -> None:
        # No flush here: events ride along with the step's commit, so a budget
        # stop (raised right after a charge) still keeps its trace.
        self._session.add(
            TraceEvent(
                run_id=self._run_id,
                timestamp=datetime.datetime.now(datetime.UTC),
                stage=stage,
                kind=kind,
                duration_ms=duration_ms,
                payload=payload,
            )
        )

    def record_llm_call(
        self,
        *,
        stage: str | None,
        prompt_version: str | None,
        note: str,
        sink: LLMCallSink,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "prompt_version": prompt_version,
            "note": note,
            "model": sink["model"],
            "input_tokens": sink["input_tokens"],
            "output_tokens": sink["output_tokens"],
            "sdk_calls": sink["sdk_calls"],
        }
        if error is not None:
            payload["error"] = error
        self._add(KIND_LLM_CALL, stage, payload, duration_ms)

    def record_source_note(self, *, stage: str | None, note: str) -> None:
        """Trace a source call from its charge note (`op[adapter]: detail`)."""
        match = _SOURCE_NOTE.match(note)
        payload: dict[str, Any] = {"note": note}
        if match:
            payload["op"] = match.group("op")
            payload["adapter"] = match.group("adapter")
            if match.group("detail"):
                payload["detail"] = match.group("detail")
        self._add(KIND_SOURCE_CALL, stage, payload)

    def record_fetch(self, *, stage: str | None, source_title: str, availability: str) -> None:
        self._add(
            KIND_SOURCE_CALL,
            stage,
            {"op": "fetch", "detail": source_title[:80], "availability": availability},
        )
