"""Drive N synthetic conversations through the Tenacious orchestrator.

Generates dummy prospects and runs a short script (cold email, reply, booking).
Records latency per turn and writes a JSONL log for p50/p95 computation.

Works without external keys: email sends dry-run (kill switch routes to sink
that is unset -> drop), HubSpot writes no-op, LLM falls back to canned reply.

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
from datetime import datetime, timezone
from pathlib import Path

from agent.logging_setup import setup_logging
from agent.orchestrator import Orchestrator

setup_logging()
log = logging.getLogger(__name__)


SCENARIOS = [
    # (channel_in, inbound_text, email, phone, company_hint)
    ("email", "Saw your note. What exactly do you offer?", "vpe@example-prospect.com", None, "Example Prospect"),
    ("email", "Not the right time for us.", "cto@stripe.com", None, "Stripe"),
    ("email", "Send pricing.", "founder@openai.com", None, "OpenAI"),
    ("email", "unsubscribe", "ops@anthropic.com", None, "Anthropic"),
    ("email", "Interested — can we talk next week?", "vp@databricks.com", None, "Databricks"),
    ("email", "Who is this?", "cto@consolety.net", None, "Consolety"),
    ("email", "We use our own offshore team. Nothing new here.", "vpe@winder.test", None, "Winder Research"),
    ("email", "Pricing please.", "cfo@wiring.test", None, "Wiring Technologies"),
    ("sms", "Yes, scheduling works — Thursday 2pm UTC?", None, "+15551112222", "Example Prospect"),
    ("sms", "STOP", None, "+15553334444", None),
]


def run(n: int, out_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    orch = Orchestrator()
    records: list[dict] = []
    latencies_ms: list[float] = []
    errors = 0

    for i in range(n):
        channel, text, email, phone, company = SCENARIOS[i % len(SCENARIOS)]
        # uniquify identifiers
        if email:
            user, domain = email.split("@", 1)
            email = f"{user}+{i}@{domain}"
        if phone:
            phone = f"+1555{str(6000000 + i)[-7:]}"
        contact_key = email or phone

        t0 = time.perf_counter()
        try:
            result = orch.handle_turn(
                channel_in=channel,
                inbound_text=text,
                contact_key=contact_key,
                email=email,
                phone=phone,
                company_hint=company,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies_ms.append(elapsed_ms)
            record = {
                "i": i,
                "channel_in": channel,
                "contact_key": contact_key,
                "inbound": text,
                "channel_out": result.get("channel_out"),
                "subject": result.get("subject"),
                "reply": result.get("reply"),
                "intent": result.get("intent"),
                "segment_used": result.get("segment_used"),
                "latency_ms": elapsed_ms,
                "trace_id": result.get("trace_id"),
                "policy": result.get("policy"),
                "hubspot_contact_id": result.get("hubspot_contact_id"),
                "booking": result.get("booking"),
                "enrichment_summary": result.get("enrichment_summary"),
                "error": None,
                "at": datetime.now(tz=timezone.utc).isoformat(),
            }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies_ms.append(elapsed_ms)
            errors += 1
            record = {
                "i": i,
                "channel_in": channel,
                "contact_key": contact_key,
                "inbound": text,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=3),
                "latency_ms": elapsed_ms,
                "at": datetime.now(tz=timezone.utc).isoformat(),
            }
            log.warning("scenario %d failed: %s", i, e)
        records.append(record)

    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    lat_sorted = sorted(latencies_ms)
    summary = {
        "n": n,
        "errors": errors,
        "success": n - errors,
        "p50_ms": round(lat_sorted[len(lat_sorted) // 2], 1) if lat_sorted else None,
        "p95_ms": round(lat_sorted[int(0.95 * len(lat_sorted))], 1) if lat_sorted else None,
        "mean_ms": round(statistics.mean(latencies_ms), 1) if latencies_ms else None,
        "out": str(out_path),
        "at": datetime.now(tz=timezone.utc).isoformat(),
    }
    (out_path.parent / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--out", type=Path, default=Path("data/runs/synthetic.jsonl"))
    args = p.parse_args()
    run(args.n, args.out)


if __name__ == "__main__":
    main()
