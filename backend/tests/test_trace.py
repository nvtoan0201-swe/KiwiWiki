"""Phase 7 part C: per-run tracing.

A full pipeline run (real handlers, fakes) must leave a durable trace — every
LLM call tagged with its prompt version and exact token usage, every source
call tagged with its adapter and operation — and `GET /runs/{id}/trace` must
assemble spans + metrics from it.
"""

from sqlalchemy import select

from app.core.constants import Stage
from app.db.models import TraceEvent
from tests.e2e.pipeline import e2e_engine, scripted_llm
from tests.orchestrator_utils import make_project
from tests.test_runner import RecordingBus, bus  # noqa: F401 — fixture reuse


async def _run_pipeline(sessionmaker, bus) -> str:  # noqa: F811
    engine = e2e_engine(sessionmaker, bus, scripted_llm())
    project = await make_project(sessionmaker)
    run_id = await engine.start(project.id)
    await engine.execute(run_id)
    return run_id


async def test_trace_events_thread_llm_and_source_calls(sessionmaker, bus):  # noqa: F811
    run_id = await _run_pipeline(sessionmaker, bus)

    async with sessionmaker() as session:
        events = (
            (await session.execute(select(TraceEvent).where(TraceEvent.run_id == run_id)))
            .scalars()
            .all()
        )

    llm_calls = [e for e in events if e.kind == "llm_call"]
    source_calls = [e for e in events if e.kind == "source_call"]
    assert llm_calls and source_calls

    # Every LLM call carries its prompt version, exact tokens, and duration.
    for event in llm_calls:
        payload = event.payload or {}
        assert payload["prompt_version"], payload
        assert payload["input_tokens"] == 500 and payload["output_tokens"] == 200
        assert payload["model"] == "fake-model"
        assert event.duration_ms is not None
        assert event.stage is not None

    # Source calls carry adapter + operation; search and fetch both traced.
    ops = {(e.payload or {}).get("op") for e in source_calls}
    assert {"search", "fetch"} <= ops
    search_ops = [e for e in source_calls if (e.payload or {}).get("op") == "search"]
    assert all((e.payload or {}).get("adapter") == "fake" for e in search_ops)

    # Stages from scoping through presentation appear in the trace.
    staged = {e.stage for e in llm_calls}
    assert Stage.scoping.value in staged
    assert Stage.report_writing.value in staged


async def test_trace_endpoint_assembles_spans_and_metrics(
    sessionmaker, bus, client, monkeypatch  # noqa: F811
):
    run_id = await _run_pipeline(sessionmaker, bus)

    response = await client.get(f"/runs/{run_id}/trace")
    assert response.status_code == 200
    trace = response.json()

    assert trace["trace_id"] == run_id
    assert trace["run"]["status"] == "complete"

    spans = trace["stages"]
    assert [s["stage"] for s in spans] == [s.value for s in Stage]
    assert all(s["status"] == "complete" for s in spans)
    search_span = next(s for s in spans if s["stage"] == Stage.literature_search.value)
    assert search_span["llm_calls"] > 0 and search_span["source_calls"] > 0
    report_span = next(s for s in spans if s["stage"] == Stage.report_writing.value)
    assert report_span["llm_tokens"] > 0

    metrics = trace["metrics"]
    assert metrics["llm_calls"] == sum(s["llm_calls"] for s in spans)
    assert metrics["llm_tokens_total"] == metrics["llm_calls"] * 700  # 500 in + 200 out per call
    assert metrics["papers_read"] == 3.0
    assert metrics["search_calls"] > 0
    assert metrics["escalations"] == 0 and metrics["loop_backs"] == 0 and metrics["errors"] == 0
    assert "scoping_v1" in metrics["llm_calls_by_prompt_version"]
    assert metrics["source_calls_by_adapter"].get("fake", 0) > 0
    # Tokens reported by the trace reconcile with the budget ledger snapshot.
    assert metrics["budget_consumed"]["llm_tokens"] == metrics["llm_tokens_total"]


async def test_trace_endpoint_404_for_unknown_run(client):
    response = await client.get("/runs/does-not-exist/trace")
    assert response.status_code == 404
