"""Leadership-change detection.

Primary signal: Crunchbase record's last_funding_at + founded_year + key_people.
We can't reliably detect CTO/VP-Eng appointments from the ODM sample alone,
so we support an override file: data/leadership_changes.json keyed by
normalized company name, with entries:

  { "role": "CTO" | "VP Engineering" | "Chief Data Officer",
    "person": "Name",
    "announced": "YYYY-MM-DD",
    "source": "press URL" }

An entry within the last 90 days triggers ICP Segment 3 (leadership transition).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OVERRIDES_PATH = DATA_DIR / "leadership_changes.json"


@dataclass
class LeadershipSignal:
    company: str
    recent_change: bool
    role: Optional[str]
    person: Optional[str]
    announced: Optional[str]
    source_url: Optional[str]
    days_ago: Optional[int]
    confidence: str
    retrieved_at: str


def _load_overrides() -> dict:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("failed to read leadership_changes.json: %s", e)
        return {}


_CTO_ROLES = {"cto", "vp engineering", "vp eng", "chief technology officer",
              "chief data officer", "head of engineering"}


def fetch_leadership_signal(company: str) -> LeadershipSignal:
    now = datetime.now(tz=timezone.utc)
    overrides = _load_overrides()
    key = company.lower().strip()
    entry = overrides.get(key)

    if not entry:
        return LeadershipSignal(
            company=company,
            recent_change=False,
            role=None,
            person=None,
            announced=None,
            source_url=None,
            days_ago=None,
            confidence="none",
            retrieved_at=now.isoformat(),
        )

    role = entry.get("role", "").strip()
    if role.lower() not in _CTO_ROLES:
        log.info("leadership override role %r is not an eng-leader; ignoring", role)
        return LeadershipSignal(
            company=company,
            recent_change=False,
            role=role or None,
            person=entry.get("person"),
            announced=entry.get("announced"),
            source_url=entry.get("source"),
            days_ago=None,
            confidence="none",
            retrieved_at=now.isoformat(),
        )

    try:
        announced_dt = datetime.strptime(entry["announced"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        announced_dt = None

    if announced_dt is None:
        days_ago = None
        recent = False
    else:
        days_ago = (now - announced_dt).days
        recent = days_ago is not None and days_ago <= 90

    return LeadershipSignal(
        company=company,
        recent_change=recent,
        role=role,
        person=entry.get("person"),
        announced=entry.get("announced"),
        source_url=entry.get("source"),
        days_ago=days_ago,
        confidence="high" if recent else "medium",
        retrieved_at=now.isoformat(),
    )


def build_leadership_signal_dict(sig: LeadershipSignal) -> dict:
    return {
        "company": sig.company,
        "recent_change": sig.recent_change,
        "role": sig.role,
        "person": sig.person,
        "announced": sig.announced,
        "source_url": sig.source_url,
        "days_ago": sig.days_ago,
        "confidence": sig.confidence,
        "retrieved_at": sig.retrieved_at,
        "source": "manual_overrides+press",
    }
