"""FastAPI app exposing email + SMS webhooks.

Email:
  - Resend sends two kinds of POSTs to /email/inbound:
    1. Event notifications (type = email.bounced | email.complained | email.delivered | ...)
    2. Inbound reply forwards (type = email.received or no type set)
  - Bounces and complaints update the conversation state (undeliverable / opted_out)
    without routing into the orchestrator.
  - Malformed payloads return HTTP 400.

SMS:
  - Africa's Talking sandbox POSTs form-encoded {from, to, text} to /sms/inbound.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Form, HTTPException, Request

from agent import state
from agent.logging_setup import setup_logging
from agent.orchestrator import Orchestrator

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(title="Tenacious SDR Agent", version="0.1.0")
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Resend event types we treat as non-deliverable -----------------------------
# https://resend.com/docs/dashboard/webhooks/event-types
_BOUNCE_EVENTS = {"email.bounced", "email.bounce"}
_COMPLAINT_EVENTS = {"email.complained", "email.complaint", "email.spam"}
_NON_REPLY_EVENTS = {
    "email.sent",
    "email.delivered",
    "email.opened",
    "email.clicked",
    "email.delivery_delayed",
}


def _extract_contact_from_event(payload: dict) -> str | None:
    """Resend event payloads carry the recipient under data.to[0] (list) or data.to (string)."""
    data = payload.get("data") or payload
    to = data.get("to") or data.get("email") or payload.get("from")
    if isinstance(to, list) and to:
        return to[0]
    if isinstance(to, str):
        return to
    return None


@app.post("/email/inbound")
async def email_inbound(request: Request) -> dict:
    """Email webhook. Handles Resend event types AND inbound reply forwards.

    Returns a structured status so the caller (Resend retry logic, tests) can
    distinguish bounce / complaint / reply / malformed.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="malformed JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    event_type = (payload.get("type") or payload.get("event") or "").lower()

    # Bounce — mark contact undeliverable, do not orchestrate.
    if event_type in _BOUNCE_EVENTS:
        contact = _extract_contact_from_event(payload)
        if not contact:
            raise HTTPException(status_code=400, detail="bounce event missing recipient")
        conv = state.load(contact)
        conv.undeliverable = True
        conv.stage = "undeliverable"
        state.save(conv)
        log.info("recorded bounce for %s", contact)
        return {"kind": "bounce", "contact": contact, "recorded": True}

    # Complaint / spam — treat as opt-out.
    if event_type in _COMPLAINT_EVENTS:
        contact = _extract_contact_from_event(payload)
        if not contact:
            raise HTTPException(status_code=400, detail="complaint event missing recipient")
        conv = state.load(contact)
        conv.opted_out = True
        conv.stage = "opted_out"
        state.save(conv)
        log.info("recorded complaint/spam for %s", contact)
        return {"kind": "complaint", "contact": contact, "recorded": True}

    # Non-reply delivery events (sent / delivered / opened / clicked / delayed) —
    # acknowledge, don't orchestrate.
    if event_type in _NON_REPLY_EVENTS:
        log.info("received non-reply event %s", event_type)
        return {"kind": "event", "event_type": event_type, "handled": True}

    # Inbound reply path (no event type OR event_type = email.received).
    from_addr = payload.get("from") or payload.get("email") or _safe_reply_from(payload)
    subject = payload.get("subject") or ""
    text = payload.get("text") or payload.get("body") or ""
    if not from_addr or not text:
        raise HTTPException(status_code=400, detail="inbound reply missing from/text")

    result = get_orchestrator().handle_turn(
        channel_in="email",
        inbound_text=f"Re: {subject}\n\n{text}" if subject else text,
        contact_key=from_addr,
        email=from_addr,
    )
    return result


def _safe_reply_from(payload: dict) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if data:
        return data.get("from") or data.get("email")
    return None


@app.post("/sms/inbound")
async def sms_inbound(request: Request) -> dict:
    """Africa's Talking webhook. Accepts form or JSON."""
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON payload")
    else:
        payload = dict(await request.form())
    phone = payload.get("from") or payload.get("phone")
    text = payload.get("text") or payload.get("message") or ""
    if not phone or not text:
        raise HTTPException(status_code=400, detail="missing from/text")
    result = get_orchestrator().handle_turn(
        channel_in="sms",
        inbound_text=text,
        contact_key=phone,
        phone=phone,
    )
    return result


@app.post("/synthetic/turn")
async def synthetic_turn(
    contact_key: str = Form(...),
    channel_in: str = Form(...),
    inbound_text: str = Form(...),
    email: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    company: str | None = Form(default=None),
    domain: str | None = Form(default=None),
) -> dict:
    return get_orchestrator().handle_turn(
        channel_in=channel_in,
        inbound_text=inbound_text,
        contact_key=contact_key,
        email=email,
        phone=phone,
        company_hint=company,
        domain_hint=domain,
    )
