"""Post-deploy smoke test (phase 7 part E).

Runs one tiny end-to-end project against a *running* deployment:

    API_URL=https://staging.example.com python -m scripts.smoke_test

Steps: health check → create a small-budget project → start a run → poll,
auto-resolving any escalation with its first offered option → require a
terminal state that is `complete` or a graceful budget stop → verify the audit
log and the run trace exist → if the run completed, verify the report exists
and download the export bundle.

Exit code 0 on success. Requires the deployment to have a working LLM key —
this exercises the real stack, unlike the fake-driven test suite.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
TIMEOUT_SECONDS = int(os.environ.get("SMOKE_TIMEOUT", "900"))
POLL_INTERVAL = float(os.environ.get("SMOKE_POLL_INTERVAL", "5"))

SMOKE_REQUEST = (
    "Smoke test: briefly, what does published literature say about whether "
    "spaced repetition improves long-term retention?"
)
# Tiny ceilings: the run should finish (or budget-stop gracefully) quickly.
SMOKE_BUDGET = {"llm_tokens": 200_000, "search_calls": 40, "papers_read": 6, "time": 600}


def fail(message: str) -> None:
    print(f"SMOKE FAIL: {message}")
    sys.exit(1)


def step(message: str) -> None:
    print(f"--- {message}")


def resolve_open_escalations(client: httpx.Client, project_id: str) -> None:
    escalations = client.get(
        f"{API_URL}/projects/{project_id}/escalations", params={"status": "open"}
    )
    escalations.raise_for_status()
    for escalation in escalations.json():
        options = escalation.get("options") or []
        response: dict[str, Any]
        if options and isinstance(options[0].get("options"), list):
            response = {
                "resolutions": {
                    amb["id"]: amb["options"][0]["id"] for amb in options if amb.get("options")
                }
            }
        elif options:
            response = {"selected_option": options[0]["id"]}
        else:
            response = {"notes": "smoke test: proceed"}
        step(f"resolving escalation {escalation['id']} with {response}")
        client.post(
            f"{API_URL}/escalations/{escalation['id']}/resolve",
            json={"user_response": response},
        ).raise_for_status()


def main() -> None:
    client = httpx.Client(timeout=60)

    step(f"health check against {API_URL}")
    health = client.get(f"{API_URL}/health")
    if health.status_code != 200 or health.json().get("status") != "ok":
        fail(f"health: {health.status_code} {health.text}")
    print(health.json())

    step("creating smoke project")
    created = client.post(
        f"{API_URL}/projects",
        json={"original_request": SMOKE_REQUEST, "budget": SMOKE_BUDGET},
    )
    if created.status_code != 201:
        fail(f"project create: {created.status_code} {created.text}")
    project_id = created.json()["id"]
    print(f"project {project_id}")

    step("starting run")
    started = client.post(f"{API_URL}/projects/{project_id}/runs")
    if started.status_code != 202:
        fail(f"run start: {started.status_code} {started.text}")
    run_id = started.json()["run_id"]
    print(f"run {run_id}")

    step("polling (auto-resolving escalations)")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    status = "running"
    while time.monotonic() < deadline:
        run = client.get(f"{API_URL}/runs/{run_id}")
        run.raise_for_status()
        status = run.json()["status"]
        if status in {"complete", "failed", "stopped"}:
            break
        if status == "paused":
            resolve_open_escalations(client, project_id)
        time.sleep(POLL_INTERVAL)
    else:
        fail(f"run did not reach a terminal state within {TIMEOUT_SECONDS}s (last: {status})")

    run_body = client.get(f"{API_URL}/runs/{run_id}").json()
    criterion = run_body.get("stopping_criterion")
    print(f"terminal: {status} ({criterion})")
    if status == "failed":
        fail("run failed — check the audit log and run trace")
    if status == "stopped" and criterion != "budget":
        fail(f"run stopped for a non-graceful reason: {criterion}")

    step("verifying audit log")
    audit = client.get(f"{API_URL}/projects/{project_id}/audit", params={"limit": 200})
    if audit.status_code != 200:
        fail(f"audit log: {audit.status_code}")
    entries = audit.json()
    entry_list = entries.get("items", entries) if isinstance(entries, dict) else entries
    if not entry_list:
        fail("audit log is empty")
    print(f"{len(entry_list)} audit entries")

    step("pulling run trace")
    trace = client.get(f"{API_URL}/runs/{run_id}/trace")
    if trace.status_code != 200:
        fail(f"trace: {trace.status_code}")
    metrics = trace.json()["metrics"]
    print(
        f"trace: {metrics['llm_calls']} llm calls, {metrics['llm_tokens_total']} tokens, "
        f"{metrics['source_calls']} source calls, stages={len(trace.json()['stages'])}"
    )
    if status == "complete" and metrics["llm_calls"] == 0:
        fail("completed run has no traced LLM calls")

    if status == "complete":
        step("verifying report exists")
        reports = client.get(f"{API_URL}/projects/{project_id}/reports")
        if reports.status_code != 200 or not reports.json():
            fail("no report after a completed run")

    step("downloading export bundle")
    bundle = client.get(f"{API_URL}/projects/{project_id}/export")
    if bundle.status_code != 200 or bundle.headers.get("content-type") != "application/zip":
        fail(f"export bundle: {bundle.status_code}")
    print(f"bundle: {len(bundle.content)} bytes")

    print("\nSMOKE PASS")


if __name__ == "__main__":
    main()
