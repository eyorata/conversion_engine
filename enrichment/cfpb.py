"""CFPB Consumer Complaint Database client.

API: https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/
No API key required. We cap `size` and time-window to 180 days per spec.

Per data policy, the agent may ONLY cite issues that appear in the structured response.
Over-claiming = misrepresentation liability.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import get_settings

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cfpb_cache"
CACHE_TTL_DAYS = 7


@dataclass
class ComplianceBrief:
    company_query: str
    window_days: int
    complaint_count: int
    top_issues: list[dict]  # [{issue: str, count: int, share: float}, ...]
    most_recent_date: Optional[str]
    confidence: str  # "high" / "medium" / "low" / "none"
    retrieved_at: str
    source: str = "cfpb_public_api"


def _cache_path(company: str, window_days: int) -> Path:
    key = hashlib.sha256(f"{company.lower()}|{window_days}".encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cache_get(company: str, window_days: int) -> Optional[dict]:
    path = _cache_path(company, window_days)
    if not path.exists():
        return None
    age = datetime.now(tz=timezone.utc) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )
    if age > timedelta(days=CACHE_TTL_DAYS):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(company: str, window_days: int, payload: dict) -> None:
    _cache_path(company, window_days).write_text(
        json.dumps(payload), encoding="utf-8"
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
)
def _call_cfpb(company: str, window_days: int) -> dict:
    settings = get_settings()
    date_received_min = (
        datetime.now(tz=timezone.utc) - timedelta(days=window_days)
    ).strftime("%Y-%m-%d")
    params = {
        "company": company,
        "date_received_min": date_received_min,
        "size": 100,
        "format": "json",
        "no_aggs": "false",
    }
    r = httpx.get(settings.CFPB_API_BASE, params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _confidence(count: int) -> str:
    if count == 0:
        return "none"
    if count < 5:
        return "low"
    if count < 25:
        return "medium"
    return "high"


def fetch_compliance_brief(company: str, *, window_days: int = 180) -> ComplianceBrief:
    cached = _cache_get(company, window_days)
    if cached is not None:
        return ComplianceBrief(**cached)

    try:
        payload = _call_cfpb(company, window_days)
    except Exception as e:
        log.warning("CFPB call failed for %s: %s", company, e)
        brief = ComplianceBrief(
            company_query=company,
            window_days=window_days,
            complaint_count=0,
            top_issues=[],
            most_recent_date=None,
            confidence="none",
            retrieved_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        _cache_put(company, window_days, brief.__dict__)
        return brief

    hits = payload.get("hits", {}).get("hits", [])
    total = payload.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        total_count = total.get("value", len(hits))
    else:
        total_count = total if isinstance(total, int) else len(hits)

    issues: Counter[str] = Counter()
    most_recent: Optional[str] = None
    for hit in hits:
        src = hit.get("_source", {})
        issue = src.get("issue")
        if issue:
            issues[issue] += 1
        date = src.get("date_received")
        if date and (most_recent is None or date > most_recent):
            most_recent = date

    top = [
        {
            "issue": issue,
            "count": count,
            "share": round(count / max(total_count, 1), 3),
        }
        for issue, count in issues.most_common(3)
    ]

    brief = ComplianceBrief(
        company_query=company,
        window_days=window_days,
        complaint_count=total_count,
        top_issues=top,
        most_recent_date=most_recent,
        confidence=_confidence(total_count),
        retrieved_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    _cache_put(company, window_days, brief.__dict__)
    return brief
