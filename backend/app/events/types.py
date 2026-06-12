"""The live-event envelope and type vocabulary (overview §6).

The event stream is the *live view*; the audit log is the *durable record*. The
frontend Activity Monitor and Notifications consume these over WebSocket. Keep
the envelope stable across phases.
"""

from __future__ import annotations

import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

EventType = Literal[
    "stage_changed",
    "activity",
    "counter_update",
    "loop_back",
    "saturation_update",
    "escalation_raised",
    "escalation_resolved",
    "output_ready",
    "run_finished",
    "error",
]


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str | None = None
    type: EventType
    stage: str | None = None
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    payload: dict[str, Any] = Field(default_factory=dict)


def make_event(
    *,
    project_id: str,
    type: EventType,
    run_id: str | None = None,
    stage: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    return Event(
        project_id=project_id,
        run_id=run_id,
        type=type,
        stage=stage,
        payload=payload or {},
    )
