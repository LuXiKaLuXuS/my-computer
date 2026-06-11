
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_run_goal(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/goals/run",
        headers=auth_headers,
        json={"goal": "Explain what an API is in one sentence", "mode": "ensemble"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["tokens_used"] > 0
    assert data["result"]["synthesis"]


@pytest.mark.asyncio
async def test_memory_timeline(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post(
        "/api/goals/run",
        headers=auth_headers,
        json={"goal": "Quick memory test", "mode": "single"},
    )
    timeline = await client.get("/api/memory/timeline", headers=auth_headers)
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["total"] >= 1
    assert len(body["items"]) >= 1