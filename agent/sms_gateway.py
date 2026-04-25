"""Africa's Talking SMS gateway with a hard kill switch.

POLICY (see docs/data_policy.md):
Outbound SMS is routed to STAFF_SINK_NUMBER unless LIVE_OUTBOUND=1.
Default MUST be unset. A unit test enforces this.

Uses httpx directly against the AT REST API rather than the `africastalking`
SDK, which hardcodes `requests` + `urllib3` and fails under some Windows TLS
inspection stacks with SSL WRONG_VERSION_NUMBER. httpx is already the
project's standard HTTP client (Resend, Cal.com, OpenRouter).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from agent.config import get_settings

log = logging.getLogger(__name__)

_SANDBOX_BASE = "https://api.sandbox.africastalking.com"
_PRODUCTION_BASE = "https://api.africastalking.com"


@dataclass
class SendResult:
    to: str
    status: str
    provider_message_id: Optional[str]
    routed_to_sink: bool


class SMSGateway:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _base_url(self) -> str:
        return _SANDBOX_BASE if self.settings.AT_USERNAME == "sandbox" else _PRODUCTION_BASE

    def send(self, to: str, message: str) -> SendResult:
        """Send a message. Enforces the kill switch."""
        routed_to_sink = False
        actual_to = to
        if not self.settings.LIVE_OUTBOUND:
            if not self.settings.STAFF_SINK_NUMBER:
                log.warning(
                    "LIVE_OUTBOUND unset and STAFF_SINK_NUMBER unset; dropping outbound"
                )
                return SendResult(
                    to=to, status="dropped_no_sink", provider_message_id=None, routed_to_sink=True
                )
            actual_to = self.settings.STAFF_SINK_NUMBER
            routed_to_sink = True
            log.info("kill-switch active: routing %s -> sink %s", to, actual_to)

        if not self.settings.AT_API_KEY:
            log.info("SMS dry-run (AT_API_KEY unset): to=%s msg=%r", actual_to, message[:80])
            return SendResult(
                to=actual_to,
                status="dry_run",
                provider_message_id=None,
                routed_to_sink=routed_to_sink,
            )

        try:
            form = {
                "username": self.settings.AT_USERNAME,
                "to": actual_to,
                "message": message,
            }
            if self.settings.AT_SHORTCODE:
                form["from"] = self.settings.AT_SHORTCODE

            resp = httpx.post(
                f"{self._base_url()}/version1/messaging",
                data=form,
                headers={
                    "apiKey": self.settings.AT_API_KEY,
                    "Accept": "application/json",
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            recipients = resp.json().get("SMSMessageData", {}).get("Recipients", [])
            mid = recipients[0].get("messageId") if recipients else None
            status = recipients[0].get("status") if recipients else "unknown"
            return SendResult(
                to=actual_to,
                status=status,
                provider_message_id=mid,
                routed_to_sink=routed_to_sink,
            )
        except Exception as e:
            log.exception("SMS send failed")
            return SendResult(
                to=actual_to,
                status=f"error:{e}",
                provider_message_id=None,
                routed_to_sink=routed_to_sink,
            )


STOP_TOKENS = {"STOP", "STOPALL", "UNSUBSCRIBE", "UNSUB", "CANCEL", "END", "QUIT"}
HELP_TOKENS = {"HELP", "INFO"}


def classify_inbound(text: str) -> str:
    """TCPA-compliant classification of inbound SMS."""
    t = (text or "").strip().upper()
    if t in STOP_TOKENS:
        return "stop"
    if t in HELP_TOKENS:
        return "help"
    return "message"
