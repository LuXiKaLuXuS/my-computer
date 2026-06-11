"""My Computer Python SDK."""

from __future__ import annotations

import os
from typing import Any

import httpx


class MyComputerClient:
    """Client for the My Computer API with JWT and API key authentication."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("MY_COMPUTER_URL", "http://localhost:8000")).rstrip("/")
        self._access_token = token
        self._refresh_token: str | None = None
        self._api_key = api_key
        self._timeout = timeout

    def set_token(self, access_token: str, refresh_token: str | None = None) -> None:
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token
        self._api_key = None

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
        self._access_token = None
        self._refresh_token = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        elif self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.request(
                method,
                url,
                headers=self._headers(),
                json=json,
                params=params,
            )
            if response.status_code == 401 and self._refresh_token:
                self.refresh()
                response = client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    params=params,
                )
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()

    def register(self, email: str, username: str, password: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/auth/register",
            json={"email": email, "username": username, "password": password},
        )
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        return data

    def login(self, email: str, password: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        return data

    def refresh(self) -> dict[str, Any]:
        if not self._refresh_token:
            raise ValueError("No refresh token available")
        data = self._request(
            "POST",
            "/api/auth/refresh",
            json={"refresh_token": self._refresh_token},
        )
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        return data

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/auth/me")

    def create_api_key(self, name: str, expires_in_days: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name}
        if expires_in_days:
            payload["expires_in_days"] = expires_in_days
        return self._request("POST", "/api/api-keys", json=payload)

    def list_api_keys(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/api-keys")

    def revoke_api_key(self, key_id: str) -> None:
        self._request("DELETE", f"/api/api-keys/{key_id}")

    def run_goal(
        self,
        goal: str,
        *,
        mode: str = "ensemble",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"goal": goal, "mode": mode}
        if project_id:
            payload["project_id"] = project_id
        return self._request("POST", "/api/goals/run", json=payload)

    def list_goals(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/goals")

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/goals/{goal_id}")

    def get_memory_timeline(
        self,
        *,
        goal_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if goal_id:
            params["goal_id"] = goal_id
        return self._request("GET", "/api/memory/timeline", params=params)

    def create_project(self, name: str, description: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/projects",
            json={"name": name, "description": description},
        )

    def list_projects(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/projects")

    def list_shared_projects(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/projects/shared")

    def share_project(
        self,
        project_id: str,
        user_id: str,
        permission: str = "view",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{project_id}/share",
            json={"user_id": user_id, "permission": permission},
        )

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")