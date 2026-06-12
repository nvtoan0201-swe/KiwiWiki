"""Audit log read schema."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_id: str | None
    timestamp: datetime.datetime
    action_type: str
    stage: str | None
    description: str
    reasoning: str | None
    payload: dict[str, Any] | None
