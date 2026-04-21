"""Africa's Talking SMS gateway with a hard kill switch.

POLICY (see docs/data_policy.md):
Outbound SMS is routed to STAFF_SINK_NUMBER unless LIVE_OUTBOUND=1.
Default MUST be unset. A unit test enforces this.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class SendResult:
    to: str
    status: str
    provider_message_id: Optional[str]
    routed_to_sink: bool


class SMSGateway:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.settings.AT_API_KEY:
            log.warning(
                "AT_API_KEY unset; SMS sends will be logged only (no provider call)"
            )
            return None
        try:
            import africastalking

            africastalking.initialize(
                self.settings.AT_USERNAME, self.settings.AT_API_KEY
            )
            self._client = africastalking.SMS
            return self._client
        except Exception as e:
            log.warning("Africa's Talking init failed: %s", e)
            return None

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

        client = self._get_client()
        if client is None:
            log.info("SMS dry-run: to=%s msg=%r", actual_to, message[:80])
            return SendResult(
                to=actual_to,
                status="dry_run",
                provider_message_id=None,
                routed_to_sink=routed_to_sink,
            )

        try:
            resp = client.send(message, [actual_to], self.settings.AT_SHORTCODE)
            recipients = resp.get("SMSMessageData", {}).get("Recipients", [])
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
