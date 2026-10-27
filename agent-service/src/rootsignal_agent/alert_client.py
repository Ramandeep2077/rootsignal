"""Async client for the alert service's internal (agent write-back) API."""

from __future__ import annotations

from typing import Any

import httpx


class AlertServiceError(Exception):
    pass


class AlertServiceClient:
    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=15)
        self._headers = {"X-Internal-Token": token}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, json: Any = None) -> dict[str, Any]:
        response = await self._client.request(method, path, json=json, headers=self._headers)
        if response.status_code >= 400:
            raise AlertServiceError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        return response.json()

    async def create_incident(
        self, title: str, severity: str, services: list[str], alert_ids: list[str]
    ) -> dict:
        return await self._request(
            "POST",
            "/api/internal/incidents",
            {"title": title[:300], "severity": severity, "affectedServices": services, "alertIds": alert_ids},
        )

    async def attach_alerts(self, incident_id: str, alert_ids: list[str]) -> dict:
        return await self._request(
            "POST", f"/api/internal/incidents/{incident_id}/alerts", {"alertIds": alert_ids}
        )

    async def set_status(self, incident_id: str, status: str) -> dict:
        return await self._request("PUT", f"/api/internal/incidents/{incident_id}/status", {"status": status})

    async def record_analysis(self, incident_id: str, analysis: dict[str, Any]) -> dict:
        return await self._request("PUT", f"/api/internal/incidents/{incident_id}/analysis", analysis)

    async def mark_notified(self, incident_id: str) -> dict:
        return await self._request("POST", f"/api/internal/incidents/{incident_id}/notified")

    async def record_execution(self, incident_id: str, execution: dict[str, Any]) -> dict:
        return await self._request(
            "PUT", f"/api/internal/incidents/{incident_id}/execution", {"execution": execution}
        )

    async def get_incident(self, incident_id: str) -> dict:
        return await self._request("GET", f"/api/incidents/{incident_id}")
