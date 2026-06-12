"""WebSocket endpoint accepts a connection and delivers a published event.

Covers Phase 0 acceptance criterion 7. Uses Starlette's TestClient so the WS
upgrade is real; the test event is published through the app's own event loop
(via the test portal) so it lands in the subscriber queue created by the
endpoint. A bounded publisher retries to avoid racing the subscribe.
"""

from __future__ import annotations

import anyio
from starlette.testclient import TestClient

from app.events.bus import InMemoryEventBus, set_event_bus
from app.events.types import make_event


def test_ws_delivers_published_event() -> None:
    bus = InMemoryEventBus()
    set_event_bus(bus)

    from app.main import app

    event = make_event(
        project_id="p1", type="activity", payload={"description": "hello from a test"}
    )

    with TestClient(app) as tc:
        with tc.websocket_connect("/ws/projects/p1") as ws:

            async def publisher() -> None:
                # Retry briefly so we don't publish before the endpoint subscribes.
                for _ in range(50):
                    await bus.publish(event)
                    await anyio.sleep(0.02)

            tc.portal.start_task_soon(publisher)
            received = ws.receive_json()

    assert received["type"] == "activity"
    assert received["project_id"] == "p1"
    assert received["payload"]["description"] == "hello from a test"
