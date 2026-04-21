"""Post-LLM policy enforcement. Hard guardrails between the LLM and the wire.

The LLM is instructed not to over-claim, but we don't trust it. This module
inspects the LLM's proposed reply against the briefs and either passes it, edits
it, or asks for regeneration.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Phrases that make a compliance claim — banned unless brief has high confidence.
_OVER_CLAIM_PATTERNS = [
    re.compile(r"\bCFPB\b", re.I),
    re.compile(r"\bcomplaint", re.I),
    re.compile(r"\bregulator", re.I),
    re.compile(r"\bviolation", re.I),
    re.compile(r"\bpenalt", re.I),
    re.compile(r"\bnon.?compliance\b", re.I),
    re.compile(r"\bexposure\b", re.I),
]

# Phrases that assert firmographic facts — must be grounded.
_FIRMO_PATTERNS = [
    re.compile(r"\b(series [abcd]|raised|funding|valuation|employees?)\b", re.I),
    re.compile(r"\$\s?\d+(\.\d+)?\s?(m|million|b|billion)", re.I),
]


@dataclass
class PolicyResult:
    ok: bool
    reply: str
    violations: list[str]
    edited: bool


def check_reply(
    reply: str,
    *,
    enrichment_brief: dict,
    compliance_brief: dict,
) -> PolicyResult:
    if not reply:
        return PolicyResult(ok=True, reply=reply, violations=[], edited=False)

    violations: list[str] = []

    conf = compliance_brief.get("confidence") if compliance_brief else None
    if conf in (None, "none", "low"):
        for pat in _OVER_CLAIM_PATTERNS:
            if pat.search(reply):
                violations.append(f"compliance_over_claim:{pat.pattern}")

    no_firmo = not enrichment_brief or enrichment_brief.get("match") == "no_crunchbase_hit"
    if no_firmo:
        for pat in _FIRMO_PATTERNS:
            if pat.search(reply):
                violations.append(f"firmographic_over_claim:{pat.pattern}")

    if len(reply) > 320:
        violations.append("message_too_long")

    if violations:
        return PolicyResult(ok=False, reply=reply, violations=violations, edited=False)
    return PolicyResult(ok=True, reply=reply, violations=[], edited=False)
