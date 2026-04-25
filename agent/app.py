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
from agent.config import get_settings
from agent.hubspot_client import HubSpotClient
from agent.logging_setup import setup_logging
from agent.orchestrator import Orchestrator

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(title="Tenacious SDR Agent", version="0.1.0")
_orchestrator: Orchestrator | None = None
_hubspot: HubSpotClient | None = None
_settings = get_settings()


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def get_hubspot() -> HubSpotClient:
    global _hubspot
    if _hubspot is None:
        _hubspot = HubSpotClient()
    return _hubspot


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
        hs = get_hubspot().upsert_contact(email=contact, stage="undeliverable")
        if hs.contact_id:
            get_hubspot().log_note(
                hs.contact_id,
                f"Email bounce webhook recorded: event_type={event_type}",
            )
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
        hs = get_hubspot().upsert_contact(email=contact, stage="opted_out")
        if hs.contact_id:
            get_hubspot().log_note(
                hs.contact_id,
                f"Email complaint/spam webhook recorded: event_type={event_type}",
            )
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


@app.post("/calcom/webhook")
async def calcom_webhook(request: Request) -> dict:
    """Cal.com booking status webhook.

    Cal.com sends booking lifecycle events here so the local state machine can
    reflect booking confirmations/cancellations even when they originate from
    the calendar system rather than the orchestrator's happy path.
    """
    secret = request.headers.get("x-cal-secret") or request.headers.get("x-calcom-signature-256")
    if _settings.CALCOM_WEBHOOK_SECRET and not secret:
        raise HTTPException(status_code=401, detail="missing Cal.com webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="malformed JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    trigger = str(payload.get("triggerEvent") or payload.get("type") or "").lower()
    data = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload.get("data")
    data = data if isinstance(data, dict) else payload

    attendees = data.get("attendees") if isinstance(data.get("attendees"), list) else []
    attendee = attendees[0] if attendees and isinstance(attendees[0], dict) else {}
    contact = attendee.get("email") or attendee.get("phoneNumber") or data.get("email") or data.get("phone")
    if not contact:
        raise HTTPException(status_code=400, detail="booking event missing attendee contact")
    attendee_email = attendee.get("email") or data.get("email")
    attendee_phone = attendee.get("phoneNumber") or data.get("phone")
    attendee_name = attendee.get("name") or data.get("name")

    conv = state.load(contact)
    if "cancel" in trigger:
        conv.booked = False
        conv.stage = "enriched" if conv.turns else "new"
        state.save(conv)
        hs = get_hubspot().upsert_contact(
            email=attendee_email if attendee_email else (contact if "@" in str(contact) else None),
            phone=attendee_phone if attendee_phone else (contact if "@" not in str(contact) else None),
            company=conv.company or attendee_name,
            stage=conv.stage,
        )
        if hs.contact_id:
            get_hubspot().log_note(
                hs.contact_id,
                f"Cal.com cancellation webhook recorded: trigger={trigger}",
            )
        log.info("recorded Cal.com cancellation for %s", contact)
        return {"kind": "booking_cancelled", "contact": contact, "recorded": True}

    booking_id = data.get("uid") or data.get("id")
    conv.booked = True
    conv.stage = "booked"
    state.save(conv)
    hs = get_hubspot().upsert_contact(
        email=attendee_email if attendee_email else (contact if "@" in str(contact) else None),
        phone=attendee_phone if attendee_phone else (contact if "@" not in str(contact) else None),
        company=conv.company or attendee_name,
        stage=conv.stage,
        booking_id=str(booking_id) if booking_id is not None else None,
    )
    if hs.contact_id:
        get_hubspot().log_note(
            hs.contact_id,
            f"Cal.com booking webhook recorded: trigger={trigger}, booking_id={booking_id}",
        )
    log.info("recorded Cal.com booking for %s (%s)", contact, booking_id)
    return {"kind": "booking_confirmed", "contact": contact, "booking_id": booking_id, "recorded": True}


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
