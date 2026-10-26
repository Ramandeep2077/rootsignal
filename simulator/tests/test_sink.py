from datetime import UTC, datetime, timedelta

import httpx
import pytest

from oncall_sim.model import SimAlert
from oncall_sim.sink import alert_payload, post_alerts

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _alerts(n):
    return [
        SimAlert(T0 + timedelta(minutes=i), "prometheus", "checkout", "HIGH", f"m{i}", {"alertname": "X"})
        for i in range(n)
    ]


def test_payload_adds_opaque_run_label_and_iso_timestamp():
    payload = alert_payload(_alerts(1)[0], "abc123")
    assert payload["labels"] == {"alertname": "X", "sim_run": "abc123"}
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_post_alerts_compresses_timeline_into_burst():
    received, sleeps = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(202, json={"id": f"id-{len(received)}"})

    client = httpx.Client(base_url="http://alerts", transport=httpx.MockTransport(handler))
    posted = post_alerts(client, _alerts(5), "run1", burst_seconds=8, sleep=sleeps.append)

    assert [p.id for p in posted] == ["id-1", "id-2", "id-3", "id-4", "id-5"]
    assert all(r.url.path == "/api/alerts" for r in received)
    assert sum(sleeps) == pytest.approx(8.0)
