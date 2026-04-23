"""Conversation state: a minimal JSON-on-disk store keyed by phone number.

For the challenge week this is sufficient; a production deploy would use
Postgres. The interface is the same — swap the implementation.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).resolve().parent / "conversation_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


@dataclass
class Turn:
    role: str  # "user" | "agent"
    text: str
    at: str  # ISO timestamp
    trace_id: Optional[str] = None
    channel: Optional[str] = None  # "email" | "sms" — needed for warm-lead gate


@dataclass
class Conversation:
    phone: str
    opted_out: bool = False
    qualified: bool = False
    booked: bool = False
    undeliverable: bool = False  # set True by bounce/complaint events
    crunchbase_id: Optional[str] = None
    company: Optional[str] = None
    stage: str = "new"  # new | enriched | qualifying | booked | closed | opted_out | undeliverable
    last_outbound_at: Optional[str] = None
    attempts: int = 0
    turns: list[Turn] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def path(self) -> Path:
        return STATE_DIR / f"{_safe_phone(self.phone)}.json"

    def touch(self) -> None:
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()


def _safe_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isalnum() or c == "+").replace("+", "p")


def load(phone: str) -> Conversation:
    path = STATE_DIR / f"{_safe_phone(phone)}.json"
    if not path.exists():
        return Conversation(phone=phone)
    with _lock:
        raw = json.loads(path.read_text(encoding="utf-8"))
    turns = [Turn(**t) for t in raw.pop("turns", [])]
    return Conversation(turns=turns, **raw)


def save(conv: Conversation) -> None:
    conv.touch()
    payload = asdict(conv)
    with _lock:
        conv.path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def all_conversations() -> list[Conversation]:
    out: list[Conversation] = []
    for p in STATE_DIR.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            turns = [Turn(**t) for t in raw.pop("turns", [])]
            out.append(Conversation(turns=turns, **raw))
        except Exception as e:
            log.warning("skip unreadable state %s: %s", p, e)
    return out
