"""The event bus: publish events and subscribe to a project's stream.

Two implementations behind one interface:
- `RedisEventBus` — production; pub/sub over Redis, one channel per project.
- `InMemoryEventBus` — tests and single-process dev; asyncio queues.

The module-level `get_event_bus()` picks Redis when a URL is configured and the
client constructs, else falls back to in-memory. `set_event_bus()` lets tests
inject a known instance.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.config import get_settings
from app.events.types import Event

logger = logging.getLogger("app.events")


def _channel(project_id: str) -> str:
    return f"events:{project_id}"


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abstractmethod
    def subscribe(self, project_id: str) -> AsyncIterator[Event]:
        """Async-iterate events for a project until the consumer stops."""
        ...

    async def close(self) -> None:  # pragma: no cover - overridden where needed
        return None


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {}

    async def publish(self, event: Event) -> None:
        for queue in list(self._subscribers.get(event.project_id, set())):
            queue.put_nowait(event)

    async def subscribe(self, project_id: str) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(project_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subs = self._subscribers.get(project_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(project_id, None)


class RedisEventBus(EventBus):
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)

    async def publish(self, event: Event) -> None:
        await self._redis.publish(_channel(event.project_id), event.model_dump_json())

    async def subscribe(self, project_id: str) -> AsyncIterator[Event]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_channel(project_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                yield Event.model_validate_json(message["data"])
        finally:
            await pubsub.unsubscribe(_channel(project_id))
            await pubsub.close()

    async def close(self) -> None:
        await self._redis.aclose()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        url = get_settings().redis_url
        try:
            _bus = RedisEventBus(url)
            logger.info("event bus: redis", extra={"extra": {"url": url}})
        except Exception as exc:  # noqa: BLE001 - degrade to in-memory
            logger.warning(
                "event bus: redis unavailable, using in-memory",
                extra={"extra": {"error": str(exc)}},
            )
            _bus = InMemoryEventBus()
    return _bus


def set_event_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus
