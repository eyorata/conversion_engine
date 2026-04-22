"""Drive N synthetic conversations through the orchestrator end-to-end.

Generates dummy phone numbers and drives a short 3-turn script against each.
Records latency per turn and writes a JSONL log for p50/p95 computation.

Works even without external keys: LLM calls will raise and be caught, HubSpot
writes no-op, SMS is kill-switch-routed. For a real run, fill .env.

Usage:
  python -m scripts.synthetic_conversation --n 20 --out data/runs/synthetic.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.logging_setup import setup_logging
from agent.orchestrator import Orchestrator

setup_logging()
log = logging.getLogger(__name__)


SCENARIOS = [
    # (inbound text, email domain hint)
    ("Hi, saw the ad. We have a compliance gap review coming up. Can we talk?", "example-bank.com"),
    ("Who is this?", "firstcitizens.com"),
    ("Not interested.", "tdbank.com"),
    ("STOP", "anycu.org"),
    ("What do you actually do?", "navyfederal.org"),
    ("Send pricing", "regions.com"),
    ("We use Drata already. What's different?", "pnc.com"),
    ("Tell me more. VP compliance here.", "ally.com"),
    ("Who said I wanted outreach?", "citizensbank.com"),
    ("Is this a bot?", "fifththird.com"),
]


def run(n: int, out_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    orch = Orchestrator()
    records: list[dict] = []
    latencies_ms: list[float] = []
    errors = 0

    for i in range(n):
        text, domain = SCENARIOS[i % len(SCENARIOS)]
        phone = f"+1555{str(1000 + i).zfill(7)}"
        email = f"lead{i}@{domain}"
        t0 = time.perf_counter()
        try:
            result = orch.handle_inbound(
                phone=phone, text=text, email=email, company_hint=None
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)
            record = {
                "i": i,
                "phone": phone,
                "email": email,
                "inbound": text,
                "reply": result.get("reply"),
                "intent": result.get("intent"),
                "latency_ms": elapsed_ms,
                "trace_id": result.get("trace_id"),
                "policy": result.get("policy"),
                "hubspot_contact_id": result.get("hubspot_contact_id"),
                "booking": result.get("booking"),
                "error": None,
                "at": datetime.now(tz=timezone.utc).isoformat(),
            }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)
            errors += 1
            record = {
                "i": i,
                "phone": phone,
                "email": email,
                "inbound": text,
                "reply": None,
                "intent": None,
                "latency_ms": elapsed_ms,
                "trace_id": None,
                "policy": None,
                "hubspot_contact_id": None,
                "booking": None,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=3),
                "at": datetime.now(tz=timezone.utc).isoformat(),
            }
            log.warning("scenario %d failed: %s", i, e)
        records.append(record)

    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    summary = {
        "n": n,
        "errors": errors,
        "success": n - errors,
        "p50_ms": round(statistics.median(latencies_ms), 1) if latencies_ms else None,
        "p95_ms": round(sorted(latencies_ms)[int(0.95 * len(latencies_ms))], 1) if latencies_ms else None,
        "mean_ms": round(statistics.mean(latencies_ms), 1) if latencies_ms else None,
        "out": str(out_path),
        "at": datetime.now(tz=timezone.utc).isoformat(),
    }
    print(json.dumps(summary, indent=2))
    (out_path.parent / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--out", type=Path, default=Path("data/runs/synthetic.jsonl"))
    args = p.parse_args()
    run(args.n, args.out)


if __name__ == "__main__":
    main()
