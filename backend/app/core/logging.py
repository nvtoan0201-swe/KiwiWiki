"""Structured JSON logging + a request-id middleware.

Logs are emitted as one JSON object per line so they are greppable and
ingestible by log aggregators. A per-request id is generated and bound to the
log record and the `X-Request-ID` response header so a request can be traced
end to end.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
# Per-run trace context: bound by the run engine around each stage step so
# every log line emitted inside a stage carries its run id and stage.
_run_context: ContextVar[dict[str, str] | None] = ContextVar("run_context", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = _request_id.get()
        if rid is not None:
            payload["request_id"] = rid
        run_ctx = _run_context.get()
        if run_ctx is not None:
            payload.update(run_ctx)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Allow callers to attach structured fields via logger.info(..., extra={"extra": {...}}).
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def current_request_id() -> str | None:
    return _request_id.get()


def bind_run_context(run_id: str, stage: str) -> object:
    """Bind a run/stage to all log lines until `reset_run_context(token)`."""
    return _run_context.set({"run_id": run_id, "stage": stage})


def reset_run_context(token: object) -> None:
    _run_context.reset(token)  # type: ignore[arg-type]


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid4().hex
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        return response
