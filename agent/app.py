"""FastAPI app exposing email + SMS webhooks.

Email webhook: Resend sends inbound reply forwards via webhooks. For the challenge
we accept a generic POST with {from, subject, text}.
SMS webhook: Africa's Talking sandbox POSTs form-encoded {from, to, text}.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Form, HTTPException, Request

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


@app.post("/email/inbound")
async def email_inbound(request: Request) -> dict:
    """Generic email reply webhook. Accepts JSON."""
    payload = await request.json()
    from_addr = payload.get("from") or payload.get("email")
    subject = payload.get("subject") or ""
    text = payload.get("text") or payload.get("body") or ""
    if not from_addr or not text:
        raise HTTPException(status_code=400, detail="missing from/text")
    result = get_orchestrator().handle_turn(
        channel_in="email",
        inbound_text=f"Re: {subject}\n\n{text}" if subject else text,
        contact_key=from_addr,
        email=from_addr,
    )
    return result


@app.post("/sms/inbound")
async def sms_inbound(request: Request) -> dict:
    """Africa's Talking webhook. Accepts form or JSON."""
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        payload = await request.json()
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
