"""FastAPI app exposing the SMS webhook endpoint + health + synthetic trigger.

Africa's Talking sandbox POSTs form-encoded fields to the inbound URL:
  from=+2517xxxxxxxx  to=<shortcode>  text=<message>  date=...  id=...  linkId=...
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Form, HTTPException, Request

from agent.logging_setup import setup_logging
from agent.orchestrator import Orchestrator

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(title="Acme ComplianceOS SDR Agent", version="0.1.0")
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/sms/inbound")
async def sms_inbound(
    request: Request,
) -> dict:
    """Africa's Talking webhook. Accepts form or JSON."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    phone = payload.get("from") or payload.get("phone")
    text = payload.get("text") or payload.get("message") or ""
    if not phone or not text:
        raise HTTPException(status_code=400, detail="missing from/text")

    result = get_orchestrator().handle_inbound(phone=phone, text=text)
    return result


@app.post("/synthetic/inbound")
async def synthetic_inbound(
    phone: str = Form(...),
    text: str = Form(...),
    email: str | None = Form(default=None),
    company: str | None = Form(default=None),
) -> dict:
    """Test endpoint used by scripts/synthetic_conversation.py."""
    return get_orchestrator().handle_inbound(phone=phone, text=text, email=email, company_hint=company)
