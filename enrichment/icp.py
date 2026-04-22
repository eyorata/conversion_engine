"""ICP segment classifier.

Four segments per the Tenacious brief:
  1. Recently-funded Series A/B (last 180d, $5-30M, ~15-80 people)
  2. Mid-market restructuring (post-layoff within 120d; 200-2000 people)
  3. Leadership transition (new CTO/VP Eng within 90d)
  4. Specialized capability gap (requires AI maturity >= 2 to pitch)

Returns a ranked list of (segment, confidence) pairs. Ties broken by priority.
If no segment scores above low confidence, return empty -> generic exploratory email.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ICPAssignment:
    segment: int
    name: str
    confidence: str          # "high" | "medium" | "low" | "none"
    rationale: list[str]


def _to_date(s: Optional[str]):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _employee_band(emp: Optional[str]) -> Optional[tuple[int, int]]:
    if not emp:
        return None
    txt = emp.replace(",", "").strip().lower()
    # handle "11-50", "51-100", "201-500", "1001-5000", "10001+"
    if "-" in txt:
        lo, hi = txt.split("-", 1)
        try:
            return int("".join(c for c in lo if c.isdigit())), int("".join(c for c in hi if c.isdigit()))
        except Exception:
            return None
    if txt.endswith("+"):
        try:
            return int("".join(c for c in txt if c.isdigit())), 10_000_000
        except Exception:
            return None
    try:
        return int("".join(c for c in txt if c.isdigit())), int("".join(c for c in txt if c.isdigit()))
    except Exception:
        return None


def classify(
    *,
    enrichment_brief: dict,
    layoffs_signal: dict,
    leadership_signal: dict,
    ai_maturity: dict,
) -> list[ICPAssignment]:
    now = datetime.now(tz=timezone.utc)
    out: list[ICPAssignment] = []

    # Segment 1 — recently funded Series A/B
    last_fund = _to_date(enrichment_brief.get("last_funding_at"))
    ftype = (enrichment_brief.get("last_funding_type") or "").lower()
    amt = enrichment_brief.get("total_funding_usd")
    band = _employee_band(enrichment_brief.get("employee_count"))
    s1_reasons: list[str] = []
    s1_conf = "none"
    if last_fund and (now - last_fund).days <= 180 and ("series a" in ftype or "series b" in ftype):
        s1_reasons.append(f"{ftype} {last_fund.date()} ({(now - last_fund).days}d ago)")
        s1_conf = "medium"
        # Size check is nice-to-have; ODM sample employee_count is inconsistent
        if band and (15 <= band[0] <= 200 or 15 <= band[1] <= 200):
            s1_reasons.append(f"size band {band[0]}-{band[1]} within ICP")
            s1_conf = "high"
        if isinstance(amt, (int, float)) and 5e6 <= amt <= 30e6:
            s1_reasons.append(f"total funding ${amt:,.0f} within Series A/B range")
            s1_conf = "high"
        out.append(ICPAssignment(1, "recently_funded_series_ab", s1_conf, s1_reasons))

    # Segment 2 — mid-market restructuring
    if layoffs_signal and layoffs_signal.get("event_count", 0) > 0:
        reasons = [f"{layoffs_signal['event_count']} layoff event(s) within 120d"]
        conf = "high"
        if band and band[0] >= 200:
            reasons.append(f"size band {band[0]}-{band[1]} within mid-market")
        elif band and band[1] < 200:
            conf = "medium"
            reasons.append(f"size band {band[0]}-{band[1]} smaller than ICP sweet spot")
        out.append(ICPAssignment(2, "mid_market_restructuring", conf, reasons))

    # Segment 3 — leadership transition
    if leadership_signal and leadership_signal.get("recent_change"):
        role = leadership_signal.get("role", "leader")
        days = leadership_signal.get("days_ago")
        out.append(ICPAssignment(
            3,
            "leadership_transition",
            "high",
            [f"new {role} appointed {days}d ago", f"source: {leadership_signal.get('source_url') or 'override'}"],
        ))

    # Segment 4 — capability gap (AI maturity >= 2 required per brief)
    score = (ai_maturity or {}).get("score", 0)
    mat_conf = (ai_maturity or {}).get("confidence", "none")
    if score >= 2 and mat_conf in ("medium", "high"):
        conf = "high" if (score == 3 and mat_conf == "high") else "medium"
        out.append(ICPAssignment(
            4,
            "specialized_capability_gap",
            conf,
            [f"AI maturity score {score}/3 with {mat_conf} confidence"],
        ))
    elif score >= 2 and mat_conf == "low":
        out.append(ICPAssignment(
            4,
            "specialized_capability_gap",
            "low",
            [f"AI maturity score {score}/3 but evidence weight is low — soft phrasing only"],
        ))

    priority_rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
    out.sort(key=lambda a: -priority_rank.get(a.confidence, 0))
    return out


def icp_assignments_to_list(assignments: list[ICPAssignment]) -> list[dict]:
    return [
        {"segment": a.segment, "name": a.name, "confidence": a.confidence, "rationale": a.rationale}
        for a in assignments
    ]
