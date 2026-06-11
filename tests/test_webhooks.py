import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_list_webhook(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/webhooks",
        headers=auth_headers,
        json={"url": "https://example.com/hook", "events": ["goal.completed"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com/hook"
    assert "goal.completed" in data["events"]
    assert data["secret"]

    listed = await client.get("/api/webhooks", headers=auth_headers)
    assert listed.status_code == 200
    webhooks = listed.json()
    assert len(webhooks) >= 1
    assert any(w["url"] == "https://example.com/hook" for w in webhooks)


@pytest.mark.asyncio
async def test_delete_webhook(client: AsyncClient, auth_headers: dict[str, str]):
    create = await client.post(
        "/api/webhooks",
        headers=auth_headers,
        json={"url": "https://example.com/delete-me"},
    )
    webhook_id = create.json()["id"]

    delete = await client.delete(f"/api/webhooks/{webhook_id}", headers=auth_headers)
    assert delete.status_code == 204

    listed = await client.get("/api/webhooks", headers=auth_headers)
    assert not any(w["id"] == webhook_id for w in listed.json())