"""Typed application errors and the FastAPI exception handlers.

Every error the API surfaces is an `AppError` subclass with a stable `code` and
an HTTP `status`. Handlers serialize them into the consistent envelope
`{"error": {"code", "message", "details"}}`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all application errors."""

    code: str = "app_error"
    status: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFound(AppError):
    code = "not_found"
    status = 404


class ValidationError(AppError):
    code = "validation_error"
    status = 422


class BudgetExceeded(AppError):
    code = "budget_exceeded"
    status = 409


class LLMError(AppError):
    code = "llm_error"
    status = 502


class SourceUnavailable(AppError):
    code = "source_unavailable"
    status = 503


class EscalationRequired(AppError):
    code = "escalation_required"
    status = 409


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())
