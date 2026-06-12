"""A bus wrapper bound to one project/run so producers don't repeat themselves.

Publishing is best-effort: a failed publish is logged and never interrupts the
run. The audit log remains the durable record.
"""

from __future__ import annotations

import logging
from typing import Any

from app.events.bus import EventBus
from app.events.types import EventType, make_event

logger = logging.getLogger("app.events")


class EventPublisher:
    def __init__(self, bus: EventBus, project_id: str, run_id: str | None = None) -> None:
        self._bus = bus
        self._project_id = project_id
        self._run_id = run_id

    async def emit(
        self,
        type: EventType,
        *,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self._bus.publish(
                make_event(
                    project_id=self._project_id,
                    type=type,
                    run_id=self._run_id,
                    stage=stage,
                    payload=payload,
                )
            )
        except Exception as exc:  # noqa: BLE001 - events are the view, never block the run
            logger.warning("event publish failed", extra={"extra": {"error": str(exc)}})
