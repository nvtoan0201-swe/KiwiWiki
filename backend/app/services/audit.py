"""The single entry point for audit writes.

Every state-changing operation records an `AuditLogEntry` here. The record is
the durable truth; where applicable a matching live `Event` is also published
(best-effort — a failed publish never blocks the audit write).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditActionType
from app.db.models import AuditLogEntry
from app.events.bus import EventBus, get_event_bus
from app.events.types import make_event

logger = logging.getLogger("app.audit")


class AuditService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus if bus is not None else get_event_bus()

    async def record(
        self,
        project_id: str,
        action_type: AuditActionType,
        description: str,
        *,
        reasoning: str | None = None,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        emit_activity: bool = True,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            project_id=project_id,
            run_id=run_id,
            timestamp=datetime.datetime.now(datetime.UTC),
            action_type=action_type.value,
            stage=stage,
            description=description,
            reasoning=reasoning,
            payload=payload,
        )
        self._session.add(entry)
        await self._session.flush()

        if emit_activity:
            await self._safe_publish(project_id, run_id, stage, action_type, description)
        return entry

    async def _safe_publish(
        self,
        project_id: str,
        run_id: str | None,
        stage: str | None,
        action_type: AuditActionType,
        description: str,
    ) -> None:
        try:
            event = make_event(
                project_id=project_id,
                type="activity",
                run_id=run_id,
                stage=stage,
                payload={"action_type": action_type.value, "description": description},
            )
            await self._bus.publish(event)
        except Exception as exc:  # noqa: BLE001 - publishing is best-effort
            logger.warning("audit event publish failed", extra={"extra": {"error": str(exc)}})
