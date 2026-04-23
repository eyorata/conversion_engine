"""Webhook event discrimination: bounces, complaints, and inbound replies."""
from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _reload():
    for m in ("agent.config", "agent.email_handler", "agent.sms_gateway",
              "agent.hubspot_client", "agent.orchestrator", "agent.app"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])


def _client(monkeypatch):
    # Keep every outbound kill-switched, no credentials needed
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    _reload()
    from agent.app import app
    return TestClient(app)


def test_email_bounce_marks_undeliverable(monkeypatch):
    tc = _client(monkeypatch)
    r = tc.post("/email/inbound", json={
        "type": "email.bounced",
        "data": {"to": ["prospect-bounce@example.test"]},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bounce"
    assert body["contact"] == "prospect-bounce@example.test"

    # Verify conversation state reflects it and future turns are ignored.
    from agent import state
    conv = state.load("prospect-bounce@example.test")
    assert conv.undeliverable is True
    assert conv.stage == "undeliverable"


def test_email_complaint_opts_out(monkeypatch):
    tc = _client(monkeypatch)
    r = tc.post("/email/inbound", json={
        "type": "email.complained",
        "data": {"to": ["prospect-complain@example.test"]},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "complaint"

    from agent import state
    conv = state.load("prospect-complain@example.test")
    assert conv.opted_out is True
    assert conv.stage == "opted_out"


def test_email_delivered_event_is_acked_not_orchestrated(monkeypatch):
    tc = _client(monkeypatch)
    r = tc.post("/email/inbound", json={
        "type": "email.delivered",
        "data": {"to": ["x@example.test"]},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "event"
    assert body["handled"] is True


def test_email_malformed_returns_400(monkeypatch):
    tc = _client(monkeypatch)
    r = tc.post("/email/inbound", data="not json",
                headers={"content-type": "application/json"})
    assert r.status_code == 400

    r2 = tc.post("/email/inbound", json={"type": "email.bounced", "data": {}})
    assert r2.status_code == 400  # bounce without recipient

    r3 = tc.post("/email/inbound", json={})
    assert r3.status_code == 400  # no from/text on an assumed-reply shape
