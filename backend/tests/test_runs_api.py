"""Run lifecycle + escalation API tests (engine injected with stub stages)."""

import pytest

from app.core.constants import Stage
from app.orchestrator.runner import set_run_engine
from app.stages._stubs import StubBehavior
from tests.orchestrator_utils import make_engine, stub_registry


@pytest.fixture
def run_engine(sessionmaker, event_bus):
    registry, handlers = stub_registry()
    eng = make_engine(sessionmaker, event_bus, registry)
    eng.stub_handlers = handlers  # type: ignore[attr-defined]
    set_run_engine(eng)
    yield eng
    set_run_engine(None)


@pytest.fixture
def escalating_engine(sessionmaker, event_bus):
    registry, handlers = stub_registry({Stage.literature_search: StubBehavior(escalate_once=True)})
    eng = make_engine(sessionmaker, event_bus, registry)
    set_run_engine(eng)
    yield eng
    set_run_engine(None)


async def _create_project(client) -> str:
    response = await client.post(
        "/projects", json={"original_request": "Survey of retrieval-augmented generation"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_start_run_drives_pipeline_to_complete(client, run_engine):
    project_id = await _create_project(client)

    response = await client.post(f"/projects/{project_id}/runs")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    await run_engine.join(run_id)

    response = await client.get(f"/runs/{run_id}")
    body = response.json()
    assert body["status"] == "complete"
    assert body["stopping_criterion"] == "coverage"

    response = await client.get(f"/projects/{project_id}/runs")
    assert [r["id"] for r in response.json()] == [run_id]

    response = await client.get(f"/projects/{project_id}")
    assert response.json()["status"] == "complete"


async def test_second_concurrent_run_rejected(client, escalating_engine):
    project_id = await _create_project(client)
    response = await client.post(f"/projects/{project_id}/runs")
    run_id = response.json()["run_id"]
    await escalating_engine.join(run_id)  # parks on the escalation (paused)

    response = await client.post(f"/projects/{project_id}/runs")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_escalation_flow_via_api(client, escalating_engine):
    project_id = await _create_project(client)
    run_id = (await client.post(f"/projects/{project_id}/runs")).json()["run_id"]
    await escalating_engine.join(run_id)

    response = await client.get(f"/projects/{project_id}/escalations?status=open")
    escalations = response.json()
    assert len(escalations) == 1
    escalation = escalations[0]
    assert escalation["status"] == "open"
    assert (await client.get(f"/projects/{project_id}")).json()["status"] == "awaiting_input"

    # An answer outside the offered options is rejected.
    response = await client.post(
        f"/escalations/{escalation['id']}/resolve",
        json={"user_response": {"selected_option": "nonsense"}},
    )
    assert response.status_code == 422

    response = await client.post(
        f"/escalations/{escalation['id']}/resolve",
        json={"user_response": {"selected_option": "option_a"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    await escalating_engine.join(run_id)
    assert (await client.get(f"/runs/{run_id}")).json()["status"] == "complete"

    # Re-resolving is rejected.
    response = await client.post(
        f"/escalations/{escalation['id']}/resolve",
        json={"user_response": {"selected_option": "option_a"}},
    )
    assert response.status_code == 422


async def test_stop_endpoint(client, escalating_engine):
    project_id = await _create_project(client)
    run_id = (await client.post(f"/projects/{project_id}/runs")).json()["run_id"]
    await escalating_engine.join(run_id)  # paused on escalation

    response = await client.post(f"/runs/{run_id}/stop", json={"reason": "changed my mind"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "stopped"
    assert body["stopping_criterion"] == "user_stopped"

    # Stopping again is rejected.
    response = await client.post(f"/runs/{run_id}/stop", json={})
    assert response.status_code == 422


async def test_budget_adjustment_midrun(client, escalating_engine):
    project_id = await _create_project(client)
    run_id = (await client.post(f"/projects/{project_id}/runs")).json()["run_id"]
    await escalating_engine.join(run_id)

    response = await client.post(f"/runs/{run_id}/budget", json={"search_calls": 42})
    assert response.status_code == 200
    project = (await client.get(f"/projects/{project_id}")).json()
    assert project["budget"]["search_calls"] == 42

    response = await client.post(f"/runs/{run_id}/budget", json={})
    assert response.status_code == 422


async def test_run_endpoints_404(client, run_engine):
    assert (await client.get("/runs/nope")).status_code == 404
    assert (await client.post("/projects/nope/runs")).status_code == 404
    assert (await client.get("/projects/nope/escalations")).status_code == 404
