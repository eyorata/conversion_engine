"""Resend email handler (primary channel for Tenacious).

Sends transactional email via Resend's REST API. Enforces the kill switch:
all outbound routes to STAFF_SINK_EMAIL unless LIVE_OUTBOUND=1.

Resend free tier: 3,000 emails/month, no CC needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class EmailSendResult:
    to: str
    status: str
    provider_message_id: Optional[str]
    routed_to_sink: bool


class EmailHandler:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> EmailSendResult:
        routed_to_sink = False
        actual_to = to
        if not self.settings.LIVE_OUTBOUND:
            if not self.settings.STAFF_SINK_EMAIL:
                log.warning(
                    "LIVE_OUTBOUND unset and STAFF_SINK_EMAIL unset; dropping outbound email"
                )
                return EmailSendResult(
                    to=to, status="dropped_no_sink", provider_message_id=None, routed_to_sink=True
                )
            actual_to = self.settings.STAFF_SINK_EMAIL
            routed_to_sink = True
            log.info("email kill-switch: routing %s -> sink %s", to, actual_to)

        if not self.settings.RESEND_API_KEY:
            log.info("Resend key unset; dry-run email to=%s subject=%r", actual_to, subject[:80])
            return EmailSendResult(
                to=actual_to, status="dry_run", provider_message_id=None, routed_to_sink=routed_to_sink
            )

        headers = {
            "Authorization": f"Bearer {self.settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": self.settings.RESEND_FROM_EMAIL or "onboarding@resend.dev",
            "to": [actual_to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = [reply_to]

        try:
            r = httpx.post(
                "https://api.resend.com/emails",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()
            return EmailSendResult(
                to=actual_to,
                status="queued",
                provider_message_id=data.get("id"),
                routed_to_sink=routed_to_sink,
            )
        except Exception as e:
            log.exception("Resend send failed")
            return EmailSendResult(
                to=actual_to, status=f"error:{e}", provider_message_id=None, routed_to_sink=routed_to_sink
            )


def classify_email_reply(text: str) -> str:
    """Crude intent tag for an inbound email reply."""
    t = (text or "").strip().lower()
    if not t:
        return "empty"
    if any(word in t for word in ("unsubscribe", "stop", "remove me", "do not email")):
        return "unsubscribe"
    if any(word in t for word in ("not interested", "no thanks", "not a fit")):
        return "negative"
    if any(word in t for word in ("yes", "interested", "let's chat", "schedule", "book", "calendar", "call")):
        return "positive"
    return "ambiguous"
