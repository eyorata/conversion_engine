"""Cal.com booking client.

Uses Cal.com's v1 API: POST /v1/bookings with apiKey as query string.
Returns booking confirmation or error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class Booking:
    booking_id: Optional[str]
    start_at: Optional[str]
    end_at: Optional[str]
    booking_url: Optional[str]
    error: Optional[str] = None


class CalcomClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def available_slots(self, *, days_ahead: int = 5) -> list[str]:
        """Naive slot suggestion: next N weekdays 10:00, 14:00 UTC. For production
        this should call /v1/slots, but the webhook mock is sufficient for the demo.
        """
        slots = []
        now = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        for d in range(1, days_ahead + 1):
            day = now + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            for hour in (10, 14):
                slots.append(day.replace(hour=hour).isoformat())
        return slots[:6]

    def book(
        self,
        *,
        start_at: str,
        name: str,
        email: str,
        phone: str,
        company: Optional[str] = None,
        timezone_str: str = "UTC",
    ) -> Booking:
        if not (self.settings.CALCOM_API_KEY and self.settings.CALCOM_EVENT_TYPE_ID):
            log.warning("Cal.com env unset; returning dry-run booking")
            return Booking(
                booking_id=f"dryrun-{int(datetime.now().timestamp())}",
                start_at=start_at,
                end_at=None,
                booking_url=None,
                error="dry_run",
            )

        params = {"apiKey": self.settings.CALCOM_API_KEY}
        body = {
            "eventTypeId": int(self.settings.CALCOM_EVENT_TYPE_ID),
            "start": start_at,
            "responses": {
                "name": name,
                "email": email,
                "phone": phone,
                "location": {"value": "phone", "optionValue": phone},
            },
            "timeZone": timezone_str,
            "language": "en",
            "metadata": {"company": company or ""},
        }

        try:
            r = httpx.post(
                f"{self.settings.CALCOM_BASE_URL}/v1/bookings",
                params=params,
                json=body,
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()
            return Booking(
                booking_id=str(data.get("id") or data.get("uid") or ""),
                start_at=data.get("startTime") or start_at,
                end_at=data.get("endTime"),
                booking_url=data.get("bookingUrl") or data.get("location"),
            )
        except Exception as e:
            log.exception("Cal.com booking failed")
            return Booking(
                booking_id=None,
                start_at=start_at,
                end_at=None,
                booking_url=None,
                error=str(e),
            )
