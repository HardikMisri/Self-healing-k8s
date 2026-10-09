from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from healer.config import Settings
from healer.main import create_app

PAYLOAD = {"status": "firing", "alerts": [
    {"status": "firing", "labels": {"alertname": "PodCrashLooping", "namespace": "demo", "pod": "p"}},
    {"status": "resolved", "labels": {"alertname": "PodCrashLooping", "namespace": "demo", "pod": "p"}}]}


def test_only_firing_alerts_are_submitted():
    orch = MagicMock()
    c = TestClient(create_app(Settings(), orchestrator=orch))
    r = c.post("/alerts", json=PAYLOAD)
    assert r.status_code == 202 and r.json() == {"accepted": 1} and orch.submit.call_count == 1


def test_token_required_when_configured():
    orch = MagicMock()
    c = TestClient(create_app(Settings(webhook_token="s3cret"), orchestrator=orch))
    assert c.post("/alerts", json=PAYLOAD).status_code == 401
    ok = c.post("/alerts", json=PAYLOAD, headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202


def test_health_and_metrics():
    c = TestClient(create_app(Settings(), orchestrator=MagicMock()))
    assert c.get("/healthz").json()["status"] == "ok"
    assert "healer_incidents_total" in c.get("/metrics/").text or c.get("/metrics").status_code in (200, 307)
