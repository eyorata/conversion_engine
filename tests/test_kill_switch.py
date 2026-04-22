"""Kill-switch tests for both channels. Policy: default MUST be unset."""
from __future__ import annotations

import importlib
import sys


def _reload():
    for m in ("agent.config", "agent.sms_gateway", "agent.email_handler"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from agent import config
    config.get_settings.cache_clear()


def test_sms_default_env_routes_to_sink(monkeypatch):
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.setenv("STAFF_SINK_NUMBER", "+15550000000")
    monkeypatch.delenv("AT_API_KEY", raising=False)
    _reload()
    from agent.sms_gateway import SMSGateway
    r = SMSGateway().send("+12025551212", "should route")
    assert r.routed_to_sink is True
    assert r.to == "+15550000000"


def test_sms_no_sink_drops(monkeypatch):
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.delenv("STAFF_SINK_NUMBER", raising=False)
    monkeypatch.delenv("AT_API_KEY", raising=False)
    _reload()
    from agent.sms_gateway import SMSGateway
    r = SMSGateway().send("+12025551212", "drop")
    assert r.status == "dropped_no_sink"


def test_email_default_routes_to_sink(monkeypatch):
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.setenv("STAFF_SINK_EMAIL", "sink@staff.test")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    _reload()
    from agent.email_handler import EmailHandler
    r = EmailHandler().send(to="prospect@example.com", subject="test", html="<p>hi</p>", text="hi")
    assert r.routed_to_sink is True
    assert r.to == "sink@staff.test"


def test_email_no_sink_drops(monkeypatch):
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.delenv("STAFF_SINK_EMAIL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    _reload()
    from agent.email_handler import EmailHandler
    r = EmailHandler().send(to="prospect@example.com", subject="test", html="<p>hi</p>", text="hi")
    assert r.status == "dropped_no_sink"


def test_live_outbound_reaches_actual(monkeypatch):
    monkeypatch.setenv("LIVE_OUTBOUND", "1")
    monkeypatch.delenv("AT_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    _reload()
    from agent.sms_gateway import SMSGateway
    from agent.email_handler import EmailHandler
    s = SMSGateway().send("+12025551212", "live")
    e = EmailHandler().send(to="p@x.com", subject="s", html="<p>b</p>", text="b")
    assert s.to == "+12025551212"
    assert s.routed_to_sink is False
    assert e.to == "p@x.com"
    assert e.routed_to_sink is False
