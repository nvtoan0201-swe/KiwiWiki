"""Phase 7 part D: rate limiting & backpressure.

- The engine queues launched runs behind a concurrency cap, so one project
  cannot starve others.
- The LLM wrapper bounds in-flight SDK calls with a thread-level semaphore.
"""

import asyncio
import threading
import time

from app.adapters.llm.client import LLMClient
from app.core.constants import Stage
from app.db.models import Run
from app.orchestrator.handler import Advance, StageContext, StageHandler, StageResult
from tests.orchestrator_utils import make_engine, make_project, stub_registry
from tests.test_llm_client import FakeClient, _response
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


class GatedScoping(StageHandler):
    """Scoping that blocks on an event, recording who got to run."""

    stage = Stage.scoping

    def __init__(self, gate: asyncio.Event, started: list[str]) -> None:
        self._gate = gate
        self._started = started

    async def run(self, ctx: StageContext) -> StageResult:
        self._started.append(ctx.project.id)
        await self._gate.wait()
        return Advance(summary={"gated": True})


async def test_run_queue_caps_concurrency(sessionmaker, bus):  # noqa: F811
    gate = asyncio.Event()
    started: list[str] = []
    registry, _ = stub_registry()
    registry.register(GatedScoping(gate, started))
    engine = make_engine(sessionmaker, bus, registry, max_concurrent_runs=1)

    first = await make_project(sessionmaker)
    second = await make_project(sessionmaker, title="Second project")
    run1 = await engine.start(first.id)
    run2 = await engine.start(second.id)
    task1 = engine.launch(run1)
    task2 = engine.launch(run2)

    # The first run reaches its handler; the second stays queued behind the cap.
    for _ in range(100):
        if started:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # give the queued run every chance to misbehave
    assert started == [first.id]

    gate.set()
    await task1
    await task2
    assert started == [first.id, second.id]

    async with sessionmaker() as session:
        assert (await session.get(Run, run1)).status == "complete"
        assert (await session.get(Run, run2)).status == "complete"


def test_llm_client_bounds_inflight_calls() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_response() -> object:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return _response("ok")

    stub = FakeClient([slow_response] * 8)
    client = LLMClient(client=stub, model="m", max_concurrent=2, max_retries=0)

    threads = [
        threading.Thread(target=lambda: client.complete([{"role": "user", "content": "x"}]))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert stub.messages.calls == 8
    assert peak <= 2
