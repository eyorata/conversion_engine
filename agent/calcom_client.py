"""Cal.com booking client.

Uses Cal.com's v2 API: POST /v2/bookings with Bearer auth so the API key
never appears in the URL (and therefore never leaks via httpx logs or
tracebacks). v1 is deprecated on hosted cal.com (returns 410 Gone).
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

    def available_slots(self, *, days_ahead: int = 14) -> list[str]:
        """Return slots that are actually free on Cal.com.

        Queries /v2/slots for real availability when creds are set so every
        synthetic prospect picks a distinct free slot. Falls back to a naive
        weekday grid (next N weekdays × 10/14 UTC) when creds are unset or
        the API call fails, so dry-run paths still work.
        """
        if self.settings.CALCOM_API_KEY and self.settings.CALCOM_EVENT_TYPE_ID:
            try:
                now = datetime.now(tz=timezone.utc)
                end = now + timedelta(days=days_ahead)
                r = httpx.get(
                    f"{self.settings.CALCOM_BASE_URL}/v2/slots",
                    headers={
                        "Authorization": f"Bearer {self.settings.CALCOM_API_KEY}",
                        "cal-api-version": "2024-09-04",
                    },
                    params={
                        "eventTypeId": int(self.settings.CALCOM_EVENT_TYPE_ID),
                        "start": now.isoformat().replace("+00:00", "Z"),
                        "end": end.isoformat().replace("+00:00", "Z"),
                    },
                    timeout=15.0,
                )
                if r.status_code == 200:
                    payload = r.json().get("data", {})
                    # v2/slots returns {"YYYY-MM-DD": [{"start": "..."}, ...]}
                    slots: list[str] = []
                    if isinstance(payload, dict):
                        for day_slots in payload.values():
                            if isinstance(day_slots, list):
                                slots.extend(s.get("start") for s in day_slots if isinstance(s, dict) and s.get("start"))
                    if slots:
                        return slots[:30]
                log.warning("Cal.com slots query failed (%s): %s", r.status_code, r.text[:200])
            except Exception as e:
                log.warning("Cal.com slots query exception: %s", e)

        # Fallback: naive grid for dry-run / no-creds path
        slots: list[str] = []
        now = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        for d in range(1, days_ahead + 1):
            day = now + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            for hour in (10, 14):
                slots.append(day.replace(hour=hour).isoformat())
        return slots[:30]

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

        headers = {
            "Authorization": f"Bearer {self.settings.CALCOM_API_KEY}",
            "cal-api-version": "2024-08-13",
            "Content-Type": "application/json",
        }
        body = {
            "eventTypeId": int(self.settings.CALCOM_EVENT_TYPE_ID),
            "start": start_at,
            "attendee": {
                "name": name,
                "email": email,
                "timeZone": timezone_str,
                "language": "en",
                "phoneNumber": phone,
            },
            "metadata": {"company": company or ""},
        }

        try:
            r = httpx.post(
                f"{self.settings.CALCOM_BASE_URL}/v2/bookings",
                headers=headers,
                json=body,
                timeout=30.0,
            )
            if r.status_code >= 400:
                log.error("Cal.com v2 rejected booking (%s): %s", r.status_code, r.text[:500])
            r.raise_for_status()
            payload = r.json()
            # v2 wraps the booking in {"status": "success", "data": {...}}
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            return Booking(
                booking_id=str(data.get("id") or data.get("uid") or ""),
                start_at=data.get("start") or data.get("startTime") or start_at,
                end_at=data.get("end") or data.get("endTime"),
                booking_url=data.get("bookingUrl") or data.get("location"),
            )
        except Exception as e:
            log.exception("Cal.com booking failed")
            return Booking(
                booking_id=None,
                start_at=start_at,
                end_at=None,
                booking_url=None,
                error=str(type(e).__name__),
            )
