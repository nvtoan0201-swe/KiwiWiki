"""Phase 7 part D: input safety on the project-creation surface.

User text flows into prompts and exports, so it is length-capped and stripped
of control characters at the API boundary.
"""


async def test_oversized_request_is_rejected(client):
    response = await client.post("/projects", json={"original_request": "x" * 10_001})
    assert response.status_code == 422


async def test_control_characters_are_stripped(client):
    response = await client.post(
        "/projects",
        json={
            "original_request": "Compare A\x00 and\x1b B for forecasting",
            "title": "A vs\x07 B",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_request"] == "Compare A and B for forecasting"
    assert body["title"] == "A vs B"


async def test_too_long_title_and_audience_rejected(client):
    response = await client.post(
        "/projects",
        json={"original_request": "Valid request", "title": "t" * 201},
    )
    assert response.status_code == 422
    response = await client.post(
        "/projects",
        json={"original_request": "Valid request", "audience": "a" * 65},
    )
    assert response.status_code == 422


async def test_manual_source_add_is_size_checked(client):
    created = await client.post("/projects", json={"original_request": "Valid request"})
    project_id = created.json()["id"]

    too_big = await client.post(
        f"/projects/{project_id}/sources",
        json={"title": "Seed paper", "abstract": "a" * 20_001},
    )
    assert too_big.status_code == 422

    bad_year = await client.post(
        f"/projects/{project_id}/sources",
        json={"title": "Seed paper", "year": 99999},
    )
    assert bad_year.status_code == 422
