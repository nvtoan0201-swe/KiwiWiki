"""Project CRUD round-trips and writes an audit entry (criterion 4)."""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_lists_gets_updates_deletes_and_audits(client: AsyncClient) -> None:
    # Create
    resp = await client.post("/projects", json={"original_request": "Survey RAG methods."})
    assert resp.status_code == 201, resp.text
    project = resp.json()
    pid = project["id"]
    assert project["status"] == "draft"
    assert project["title"] == "Survey RAG methods."
    assert project["budget"] is not None  # defaults applied

    # Creating a project wrote an audit_log row via AuditService.
    audit = (await client.get(f"/projects/{pid}/audit")).json()
    assert audit["total"] >= 1
    assert any("created" in e["description"].lower() for e in audit["items"])

    # List
    listing = (await client.get("/projects")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == pid

    # Get
    got = (await client.get(f"/projects/{pid}")).json()
    assert got["id"] == pid

    # Patch
    patched = await client.patch(
        f"/projects/{pid}", json={"research_question": "Which RAG method wins on long-context QA?"}
    )
    assert patched.status_code == 200
    assert patched.json()["research_question"].startswith("Which RAG")

    # Delete
    deleted = await client.delete(f"/projects/{pid}")
    assert deleted.status_code == 204
    assert (await client.get(f"/projects/{pid}")).status_code == 404


async def test_get_missing_project_returns_error_envelope(client: AsyncClient) -> None:
    resp = await client.get("/projects/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]
