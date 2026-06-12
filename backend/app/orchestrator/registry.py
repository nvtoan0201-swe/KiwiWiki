"""Stage handler registry. The engine looks handlers up here; an unregistered
stage is a controlled failure (the runner turns it into a failed run, not a
crash)."""

from __future__ import annotations

from app.core.constants import Stage
from app.core.errors import AppError
from app.orchestrator.handler import StageHandler


class UnregisteredStage(AppError):
    code = "unregistered_stage"
    status = 500


class StageRegistry:
    def __init__(self) -> None:
        self._handlers: dict[Stage, StageHandler] = {}

    def register(self, handler: StageHandler) -> None:
        """Register (or replace — tests swap stubs in and out) the handler for a stage."""
        self._handlers[handler.stage] = handler

    def get(self, stage: Stage) -> StageHandler:
        handler = self._handlers.get(stage)
        if handler is None:
            raise UnregisteredStage(f"No handler registered for stage '{stage.value}'")
        return handler

    def registered_stages(self) -> list[Stage]:
        return list(self._handlers)
