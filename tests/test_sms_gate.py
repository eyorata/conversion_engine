"""Hard channel-hierarchy gate: outbound SMS only after a prior email reply.

Drives the orchestrator directly (not the webhook) to avoid needing a live
LLM or Resend credential. The LLM call is stubbed by the orchestrator's
LLMClient when OPENROUTER_API_KEY is unset — it returns an email-channel
canned reply. To test the SMS gate, we force the stub to return SMS via
monkeypatch.
"""
from __future__ import annotations

import importlib
import sys
import uuid


def _reload():
    for m in ("agent.config", "agent.llm", "agent.email_handler",
              "agent.sms_gateway", "agent.hubspot_client", "agent.orchestrator"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])


def _stub_sms_llm(monkeypatch):
    """Force the orchestrator's LLM to return channel=sms."""
    def _stub(self, user_prompt):  # type: ignore[no-redef]
        return (
            {
                "channel": "sms",
                "subject": None,
                "body": "Thursday at 2pm UTC works.",
                "intent": "book",
                "segment_used": None,
                "book_slot": None,
                "confidence": 0.5,
                "reasoning": "stub",
            },
            "",
        )
    from agent.orchestrator import Orchestrator
    monkeypatch.setattr(Orchestrator, "_call_llm", _stub)


def test_cold_inbound_sms_does_not_escalate_to_sms(monkeypatch):
    # Env: kill switch active (no credentials needed)
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("STAFF_SINK_EMAIL", "sink@staff.test")
    monkeypatch.setenv("STAFF_SINK_NUMBER", "+15550000000")
    _reload()

    _stub_sms_llm(monkeypatch)

    from agent.orchestrator import Orchestrator
    contact = f"+1555777{uuid.uuid4().int % 10000:04d}"
    orch = Orchestrator()
    result = orch.handle_turn(
        channel_in="sms",
        inbound_text="hey who are you",
        contact_key=contact,
        phone=contact,
    )
    # Even though the LLM asked for sms, the prospect has no prior email reply,
    # so the gate must force email.
    assert result["channel_out"] == "email", (
        f"cold prospect should not receive SMS; got {result}"
    )


def test_warm_lead_with_prior_email_reply_can_get_sms(monkeypatch):
    monkeypatch.delenv("LIVE_OUTBOUND", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("STAFF_SINK_EMAIL", "sink@staff.test")
    monkeypatch.setenv("STAFF_SINK_NUMBER", "+15550000000")
    _reload()
    _stub_sms_llm(monkeypatch)

    from agent import state as state_mod
    from agent.orchestrator import Orchestrator
    from datetime import datetime, timezone

    contact = f"warm-{uuid.uuid4()}@example.test"
    phone = "+15558887777"

    # Seed a prior email exchange manually: prospect emailed, we replied.
    conv = state_mod.Conversation(phone=phone)
    conv.turns = [
        state_mod.Turn(role="user", text="interested", at=datetime.now(timezone.utc).isoformat(),
                       trace_id="t1", channel="email"),
        state_mod.Turn(role="agent", text="great, when works?", at=datetime.now(timezone.utc).isoformat(),
                       trace_id="t1", channel="email"),
    ]
    conv.stage = "enriched"
    conv.company = "WarmCo"
    # Save under the key the orchestrator will use (SMS inbound keys on phone)
    conv.phone = contact
    state_mod.save(conv)
    # Also save under phone since our inbound channel is sms
    conv2 = state_mod.Conversation(phone=phone)
    conv2.turns = list(conv.turns)
    conv2.stage = "enriched"
    conv2.company = "WarmCo"
    state_mod.save(conv2)

    orch = Orchestrator()
    result = orch.handle_turn(
        channel_in="sms",
        inbound_text="let's do thursday 2pm",
        contact_key=phone,
        phone=phone,
    )
    # Prospect replied via email previously, so LLM's SMS choice is permitted.
    assert result["channel_out"] == "sms", (
        f"warm prospect with prior email reply should permit sms; got {result}"
    )
