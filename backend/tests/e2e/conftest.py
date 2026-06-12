"""E2E fixtures: the recording event bus shared by all pipeline tests."""

from __future__ import annotations

import pytest

from app.events.bus import set_event_bus
from tests.test_runner import RecordingBus


@pytest.fixture
def bus() -> RecordingBus:
    recording = RecordingBus()
    set_event_bus(recording)
    return recording
