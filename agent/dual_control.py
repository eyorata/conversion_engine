"""Dual-control commitment gate (DCCG).

Detects scheduling-deferral signals in the prospect's latest inbound and
prevents the agent from unilaterally booking a slot when the prospect has
not yet given explicit consent.

This is the Act IV mechanism, targeting probe P7.1 which currently fires at
100% trigger rate. See probes/target_failure_mode.md for the full design.

Public API:
    detect_wait_signal(text)         -> WaitSignal | None
    detect_explicit_acceptance(text) -> bool

Both are pure functions over the inbound text. They return primitives so
the orchestrator can write them into trace metadata without serialization
gymnastics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Patterns are ordered by specificity; the first match wins for trace tagging.
# Each entry: (signal_kind, compiled_regex)
_WAIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("let_me_check", re.compile(r"\blet\s+me\s+check\b", re.IGNORECASE)),
    ("get_back_to_you", re.compile(r"\bget\s+back\s+to\s+(?:you|u)\b", re.IGNORECASE)),
    ("ill_let_you_know", re.compile(r"\bi(?:'|\s+wi)?ll\s+let\s+you\s+know\b", re.IGNORECASE)),
    ("thinking_about_it", re.compile(r"\bthinking\s+about\s+(?:it|this)\b", re.IGNORECASE)),
    ("need_to_confirm", re.compile(r"\b(?:need|have)\s+to\s+confirm\b", re.IGNORECASE)),
    ("checking_with_team", re.compile(r"\bcheck(?:ing)?\s+with\s+(?:my\s+|the\s+)?(?:team|cto|ceo|cfo|board)\b", re.IGNORECASE)),
    ("circle_back", re.compile(r"\bcircle\s+back\b", re.IGNORECASE)),
    ("hold_off", re.compile(r"\bhold\s+off\b", re.IGNORECASE)),
    ("revisit_later", re.compile(r"\b(?:let'?s|will|would)\s+revisit\b", re.IGNORECASE)),
    ("week_is_busy", re.compile(r"\bthis\s+week\s+is\s+(?:busy|tight|tough|crazy|packed)\b", re.IGNORECASE)),
    ("not_this_week", re.compile(r"\bnot\s+(?:this|next)\s+week\b", re.IGNORECASE)),
    ("maybe_later", re.compile(r"\bmaybe\s+(?:next\s+|the\s+)?(?:week|month|quarter)\b", re.IGNORECASE)),
    ("reach_out_later", re.compile(r"\b(?:i\s+will|i'll)\s+reach\s+out\b", re.IGNORECASE)),
]

# Explicit acceptance overrides the wait signal — but ONLY when the prospect
# names a specific time / commits to a booking. A bare "Yeah" or "Sure" is a
# softener, not slot acceptance, so those alone do not override the wait
# signal. Each pattern below is independently sufficient evidence of consent.
_ACCEPT_PATTERNS: list[re.Pattern[str]] = [
    # Imperative booking verbs (strong consent on their own)
    re.compile(r"\b(?:book\s+(?:it|that|this)|lock\s+(?:it|that|this)\s+in|please\s+book|send\s+(?:the|a)\s+(?:invite|invitation|calendar))\b", re.IGNORECASE),
    re.compile(r"\b(?:confirmed|confirming\s+(?:the|that)|locked\s+in|see\s+you\s+then|count\s+me\s+in)\b", re.IGNORECASE),
    # Affirmation that is bound to the slot ("that works", "works for me")
    re.compile(r"\b(?:that\s+works|works\s+for\s+me|works\s+great|that'?s\s+(?:fine|good|perfect))\b", re.IGNORECASE),
    # Concrete time (HH:MM with optional am/pm/UTC, or ISO timestamp, or weekday+at+time)
    re.compile(r"\b\d{1,2}:\d{2}\s*(?:am|pm|utc)?\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s*(?:am|pm)\b(?!\s*(?:est|cst|mst|pst|edt|cdt|mdt|pdt|cet|bst|ist|gmt|utc))", re.IGNORECASE),
    re.compile(r"\b202[6-9]-\d{2}-\d{2}T\d{2}:\d{2}"),
    re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+\d", re.IGNORECASE),
]


@dataclass(frozen=True)
class WaitSignal:
    kind: str
    matched_text: str

    def __bool__(self) -> bool:  # truthiness for orchestrator code
        return True


def detect_wait_signal(text: str) -> Optional[WaitSignal]:
    """Return a WaitSignal if the inbound text contains a scheduling-deferral
    pattern, else None.

    First match wins (patterns are ordered by specificity above).
    """
    if not text:
        return None
    for kind, pat in _WAIT_PATTERNS:
        m = pat.search(text)
        if m:
            return WaitSignal(kind=kind, matched_text=m.group(0))
    return None


def detect_explicit_acceptance(text: str) -> bool:
    """True if the inbound contains an explicit slot acceptance.

    Used as a false-positive guard: if the prospect said both "let me check"
    AND gave an explicit time, we treat the explicit time as authoritative.
    """
    if not text:
        return False
    return any(pat.search(text) for pat in _ACCEPT_PATTERNS)


def should_block_booking(text: str) -> tuple[bool, Optional[WaitSignal]]:
    """Combined check.

    Returns (should_block, matched_signal). should_block is True iff a wait
    signal is present AND no explicit acceptance was given.
    """
    sig = detect_wait_signal(text)
    if sig is None:
        return False, None
    if detect_explicit_acceptance(text):
        return False, sig  # signal seen, but overridden by explicit accept
    return True, sig
