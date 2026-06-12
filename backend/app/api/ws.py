"""WebSocket endpoint relaying a project's live event stream.

No producers exist yet in Phase 0; this verifies the transport: a client
connects and receives events published to the bus for its project. Stages and
the orchestrator become producers in later phases.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events.bus import get_event_bus

logger = logging.getLogger("app.ws")
router = APIRouter(tags=["ws"])


@router.websocket("/ws/projects/{project_id}")
async def project_events(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    bus = get_event_bus()
    try:
        async for event in bus.subscribe(project_id):
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        logger.info("ws disconnected", extra={"extra": {"project_id": project_id}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws relay error", extra={"extra": {"error": str(exc)}})
        await websocket.close(code=1011)
