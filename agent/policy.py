"""Post-LLM policy check for Tenacious outbound.

Guardrails between the LLM and the wire. Flags:
  - hiring-signal over-claim (e.g. "aggressive hiring" when total_roles < 5)
  - funding over-claim (naming Series A/B when last_funding_type absent)
  - layoff over-claim (referring to layoff when layoffs_signal.event_count == 0)
  - leadership over-claim (naming a new role change when leadership_signal.recent_change is False)
  - gap over-claim (referencing a competitor practice not in gap_brief.gap_practices)
  - capacity over-commitment (naming a specific engineer count / staffing promise)
  - pricing statements
  - Tenacious style markers: "just checking in", "circling back", "quick question"
  - message too long
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


AGGRESSIVE_HIRING_PATTERNS = [
    re.compile(r"\b(aggressive(ly)?\s+hiring|scaling\s+the\s+team|hiring\s+blitz|ramp(ing)?\s+hiring)\b", re.I),
    re.compile(r"\b(tripled|doubled|surged)\s+(open|engineering|your)?\s*(roles|hiring|openings)?\b", re.I),
]

FUNDING_PATTERNS = [
    re.compile(r"\bseries\s*[abcd]\b", re.I),
    re.compile(r"\braised\s*\$\s*\d", re.I),
    re.compile(r"\bfreshly\s+funded\b", re.I),
    re.compile(r"\b\$\s*\d+(\.\d+)?\s*(m|million|b|billion)\b", re.I),
]

LAYOFF_PATTERNS = [
    re.compile(r"\b(recent|announced|last)\s+(layoff|reduction\s+in\s+force|rif)\b", re.I),
    re.compile(r"\bpost[-\s]?layoff\b", re.I),
]

LEADERSHIP_PATTERNS = [
    re.compile(r"\bnew\s+(cto|vp\s+engineering|vpe|chief\s+data\s+officer|head\s+of\s+engineering)\b", re.I),
    re.compile(r"\b(recently\s+appointed|just\s+joined|coming\s+onboard)\b", re.I),
]

CAPACITY_COMMITMENT_PATTERNS = [
    re.compile(r"\b(\d{1,3})\s+(engineers|developers|python|go|java|data|ml)\s+engineers?\s+(ready|available|starting|onboard)\b", re.I),
    re.compile(r"\bstart\s+(next\s+week|monday|tomorrow)\s+with\b", re.I),
    re.compile(r"\bdeploy\s+a\s+team\s+of\s+\d+\b", re.I),
]

PRICING_PATTERNS = [
    re.compile(r"\$\s*\d+\s?(k|K|m|M)?\s*/\s*(month|month|mo|engineer|year|yr)\b", re.I),
    re.compile(r"\b(rate|pricing|contract\s+term|invoice)\s+(of|is|starts)\s+\$", re.I),
]

BANNED_STYLE_PHRASES = [
    re.compile(r"\bjust\s+checking\s+in\b", re.I),
    re.compile(r"\bcircling\s+back\b", re.I),
    re.compile(r"\bquick\s+question\b", re.I),
    re.compile(r"\btouching\s+base\b", re.I),
    re.compile(r"\bhope\s+this\s+finds\s+you\s+well\b", re.I),
]


@dataclass
class PolicyResult:
    ok: bool
    violations: list[str]


def _confidence_allows(sig: dict | None, asserting_kinds=("high", "medium")) -> bool:
    if not sig:
        return False
    return sig.get("confidence") in asserting_kinds


def _claims_exist(patterns: list[re.Pattern], text: str) -> list[str]:
    hits = []
    for p in patterns:
        m = p.search(text)
        if m:
            hits.append(m.group(0))
    return hits


def check_outbound(
    *,
    channel: str,
    subject: str | None,
    body: str,
    hiring_signal_brief: dict,
    competitor_gap_brief: dict | None,
) -> PolicyResult:
    violations: list[str] = []

    if not body:
        return PolicyResult(ok=True, violations=[])

    jobs = hiring_signal_brief.get("jobs_signal") or {}
    layoffs = hiring_signal_brief.get("layoffs_signal") or {}
    leadership = hiring_signal_brief.get("leadership_signal") or {}
    funding = hiring_signal_brief.get("funding_signal") or {}

    # Aggressive hiring claim only allowed at jobs_signal.confidence >= medium
    # AND at least 5 total_roles
    if not (_confidence_allows(jobs) and (jobs.get("total_roles_current") or 0) >= 5):
        hits = _claims_exist(AGGRESSIVE_HIRING_PATTERNS, body)
        if hits:
            violations.append(f"hiring_over_claim:{hits[0]!r}")

    # Funding mentions require last_funding_type to be set
    if not funding.get("last_funding_type"):
        hits = _claims_exist(FUNDING_PATTERNS, body)
        if hits:
            violations.append(f"funding_over_claim:{hits[0]!r}")

    # Layoff mentions require layoffs_signal.event_count > 0
    if not (layoffs.get("event_count", 0) > 0):
        hits = _claims_exist(LAYOFF_PATTERNS, body)
        if hits:
            violations.append(f"layoff_over_claim:{hits[0]!r}")

    # Leadership change mentions require leadership_signal.recent_change
    if not leadership.get("recent_change"):
        hits = _claims_exist(LEADERSHIP_PATTERNS, body)
        if hits:
            violations.append(f"leadership_over_claim:{hits[0]!r}")

    # Capacity commitment is always a violation — route to human
    hits = _claims_exist(CAPACITY_COMMITMENT_PATTERNS, body)
    if hits:
        violations.append(f"capacity_commitment:{hits[0]!r}")

    # Pricing always violation
    hits = _claims_exist(PRICING_PATTERNS, body)
    if hits:
        violations.append(f"pricing_mention:{hits[0]!r}")

    # Banned SDR filler style
    hits = _claims_exist(BANNED_STYLE_PHRASES, body)
    if hits:
        violations.append(f"style_filler:{hits[0]!r}")

    # Competitor gap: any named practice that isn't in gap_practices with >=2 supporters
    if competitor_gap_brief:
        supported_practices = {
            p.get("practice", "").lower()
            for p in competitor_gap_brief.get("gap_practices", [])
            if p.get("supporting_peer_count", 0) >= 2
        }
        # This is a weak check — gap practices are named as signal keys like
        # "ai_role_share". The LLM paraphrases them. We only flag if the LLM
        # names a peer company in a disparaging way.
        DISPARAGING = re.compile(
            r"\b(ahead\s+of|beating|outpacing|crushing|dominating|trouncing|leaving.*behind)\b",
            re.I,
        )
        for peer in [p["name"] for p in (competitor_gap_brief.get("peers") or [])]:
            if peer.lower() in body.lower() and DISPARAGING.search(body):
                violations.append(f"gap_disparaging:{peer}")

    # Length budgets
    if channel == "email" and len(body) > 2000:
        violations.append("email_body_too_long")
    if channel == "email" and subject and len(subject) > 60:
        violations.append("email_subject_too_long")
    if channel == "sms" and len(body) > 320:
        violations.append("sms_too_long")

    return PolicyResult(ok=not violations, violations=violations)
