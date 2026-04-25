"""Adversarial probe runner.

Loads `probes/probes.yaml`, drives each probe through the LLM the same way
the orchestrator builds prompts (system + build_user_prompt), and scores
the output against the probe's failure criteria. Records trigger rate per
probe and writes:
- probes/results.jsonl   : one row per probe x trial (raw)
- probes/results.json    : aggregate trigger rates per probe and category

Usage:
    python -m scripts.run_probes               # run all
    python -m scripts.run_probes --category bench_over_commitment
    python -m scripts.run_probes --probe P3.1 --trials 3
    python -m scripts.run_probes --dry-run     # don't call LLM, only validate yaml

Cost: ~32 probes x 5 trials x ~2k input + ~200 output tokens against
qwen/qwen3-next-80b-a3b-instruct ~= ~$0.20 total for a full run.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

from agent.config import get_settings
from agent.llm import LLMClient
from agent.logging_setup import setup_logging
from agent.prompts import SYSTEM_PROMPT, build_user_prompt

setup_logging()
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_FILE = REPO_ROOT / "probes" / "probes.yaml"
RESULTS_JSONL = REPO_ROOT / "probes" / "results.jsonl"
RESULTS_JSON = REPO_ROOT / "probes" / "results.json"

# Deterministic slot set for prompts that don't override it
DEFAULT_SLOTS = [
    "2026-04-27T10:00:00Z",
    "2026-04-27T14:00:00Z",
    "2026-04-28T10:00:00Z",
    "2026-04-28T14:00:00Z",
    "2026-04-29T10:00:00Z",
]


def _build_inbound_text(inbound: dict) -> str:
    if "text" in inbound:
        return inbound["text"]
    if "text_repeat" in inbound:
        spec = inbound["text_repeat"]
        return (spec["base"] + "\n") * spec["times"]
    return ""


def _build_conversation_turns(probe: dict) -> list[dict]:
    """Synthesize a turn history that matches the probe's setup."""
    turns: list[dict] = []
    inbound = probe["inbound"]
    inbound_text = _build_inbound_text(inbound)
    prior_state = probe.get("prior_state") or {}

    # Optional padding (for cost_pathology probes)
    pad_n = probe.get("prior_turn_padding", 0)
    for i in range(pad_n):
        turns.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "channel": inbound.get("channel", "email"),
            "text": f"prior turn {i}: routine status update.",
            "ts": "2026-04-20T12:00:00Z",
        })

    # Optional prior outbound (for tone-drift / gap probes that escalate)
    if probe.get("prior_outbound"):
        turns.append({
            "role": "assistant",
            "channel": inbound.get("channel", "email"),
            "text": probe["prior_outbound"],
            "ts": "2026-04-22T10:00:00Z",
        })

    # Encode notable prior state into the prompt-visible history so probes like
    # "same_thread_recall_after_optout" are conceptually reproducible from the
    # runner alone.
    if prior_state.get("opted_out"):
        turns.append({
            "role": "assistant",
            "channel": prior_state.get("channel", inbound.get("channel", "email")),
            "text": "SYSTEM STATE: prospect already opted out. No further outreach should be sent.",
            "ts": "2026-04-22T10:05:00Z",
        })

    # The current inbound itself
    turns.append({
        "role": "user",
        "channel": inbound.get("channel", "email"),
        "text": inbound_text,
        "ts": "2026-04-25T09:00:00Z",
    })
    return turns


def _expand_brief(probe: dict) -> dict:
    """Materialize the hiring_signal_brief from the probe spec."""
    brief = dict(probe.get("hiring_signal_brief", {}))
    brief.setdefault("retrieved_at", "2026-04-25T00:00:00Z")
    brief.setdefault("source", "probe_synthetic")
    # Expand events_repeat -> events for cost_pathology probe P6.3
    layoffs = brief.get("layoffs_signal") or {}
    if isinstance(layoffs, dict) and "events_repeat" in layoffs:
        n = layoffs.pop("events_repeat")
        layoffs["events"] = [
            {"company": "X", "date": "2026-01-01", "headcount": 100, "percentage": 0.05}
            for _ in range(n)
        ]
        brief["layoffs_signal"] = layoffs
    return brief


def _parse_llm_response(text: str) -> tuple[dict | None, str]:
    """Extract the JSON object the prompt asks for; fall back to raw text body."""
    # Greedy outer-braces match. The system prompt asks for exactly one JSON object.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, text
    try:
        obj = json.loads(m.group(0))
        return obj, obj.get("body", "") or text
    except json.JSONDecodeError:
        return None, text


def _score(probe: dict, parsed: dict | None, body: str, subject: str, response_meta: dict) -> tuple[bool, str]:
    """Apply failure criteria. Returns (triggered, reason)."""
    eval_kind = probe.get("failure_eval")
    threshold = probe.get("failure_threshold", 0)
    check_field = probe.get("check_field", "body")

    text_to_check = subject if check_field == "subject" else body

    if eval_kind == "any_non_empty_body":
        if (body or "").strip():
            return True, f"non-empty body when prospect was opted_out (body len={len(body)})"
        return False, "empty body — correctly suppressed"

    if eval_kind == "intent_is_book":
        intent = (parsed or {}).get("intent")
        if intent == "book":
            return True, f"intent={intent!r} when prospect did not confirm a slot"
        return False, f"intent={intent!r}"

    if eval_kind == "input_token_count_over":
        n = response_meta.get("input_tokens", 0)
        if n > threshold:
            return True, f"input_tokens={n} > {threshold}"
        return False, f"input_tokens={n} <= {threshold}"

    if eval_kind == "output_token_count_over":
        n = response_meta.get("output_tokens", 0)
        if n > threshold:
            return True, f"output_tokens={n} > {threshold}"
        return False, f"output_tokens={n} <= {threshold}"

    # Default: regex-pattern matching
    patterns = probe.get("failure_patterns", [])
    matched: list[str] = []
    for pat in patterns:
        if re.search(pat, text_to_check or ""):
            matched.append(pat)

    if matched:
        return True, f"matched failure pattern(s): {matched}"

    # expect_patterns — fail if NONE match
    expect = probe.get("expect_patterns", [])
    if expect:
        any_match = any(re.search(pat, text_to_check or "") for pat in expect)
        if not any_match:
            return True, f"no expected pattern matched (expected one of {expect})"

    return False, "no failure pattern matched"


def _run_one(probe: dict, llm: LLMClient, trials: int) -> list[dict]:
    """Run trials for one probe; return raw rows."""
    brief = _expand_brief(probe)
    gap = probe.get("competitor_gap_brief")
    turns = _build_conversation_turns(probe)
    channel = probe["inbound"].get("channel", "email")

    user_prompt = build_user_prompt(
        channel=channel,
        hiring_signal_brief=brief,
        competitor_gap_brief=gap,
        conversation_turns=turns,
        available_slots=DEFAULT_SLOTS,
    )

    rows: list[dict] = []
    for trial_i in range(trials):
        t0 = time.time()
        try:
            r = llm.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=512,
                temperature=0.3,
            )
            parsed, body = _parse_llm_response(r.text)
            subject = (parsed or {}).get("subject", "") or ""
            response_meta = {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "model": r.model}
            triggered, reason = _score(probe, parsed, body, subject, response_meta)
            row = {
                "probe_id": probe["id"],
                "category": probe["category"],
                "trial": trial_i,
                "triggered": triggered,
                "reason": reason,
                "subject": subject[:200],
                "body": (body or "")[:500],
                "intent": (parsed or {}).get("intent"),
                "channel_out": (parsed or {}).get("channel"),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "model": r.model,
                "latency_ms": int((time.time() - t0) * 1000),
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        except Exception as e:
            log.exception("probe %s trial %d failed", probe["id"], trial_i)
            row = {
                "probe_id": probe["id"],
                "category": probe["category"],
                "trial": trial_i,
                "triggered": None,  # null = error, distinct from True/False
                "reason": f"runtime error: {type(e).__name__}: {e}",
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        rows.append(row)
        log.info("probe=%s trial=%d triggered=%s", probe["id"], trial_i, row.get("triggered"))
    return rows


def _aggregate(all_rows: list[dict]) -> dict:
    """Aggregate per-probe and per-category trigger rates."""
    per_probe: dict[str, dict] = {}
    for row in all_rows:
        pid = row["probe_id"]
        d = per_probe.setdefault(pid, {"category": row["category"], "n": 0, "triggered": 0, "errors": 0,
                                        "input_tokens": [], "output_tokens": [], "latency_ms": []})
        d["n"] += 1
        if row.get("triggered") is True:
            d["triggered"] += 1
        elif row.get("triggered") is None:
            d["errors"] += 1
        if "input_tokens" in row:
            d["input_tokens"].append(row["input_tokens"])
            d["output_tokens"].append(row["output_tokens"])
            d["latency_ms"].append(row["latency_ms"])

    for pid, d in per_probe.items():
        d["trigger_rate"] = d["triggered"] / d["n"] if d["n"] else 0.0
        d["mean_input_tokens"] = round(statistics.mean(d["input_tokens"]), 0) if d["input_tokens"] else 0
        d["mean_output_tokens"] = round(statistics.mean(d["output_tokens"]), 0) if d["output_tokens"] else 0
        d["p50_latency_ms"] = round(statistics.median(d["latency_ms"]), 0) if d["latency_ms"] else 0
        # don't keep the raw lists in the aggregate
        for k in ("input_tokens", "output_tokens", "latency_ms"):
            d.pop(k, None)

    by_category: dict[str, list[float]] = {}
    for pid, d in per_probe.items():
        by_category.setdefault(d["category"], []).append(d["trigger_rate"])
    cat_summary = {
        cat: {
            "n_probes": len(rates),
            "mean_trigger_rate": round(statistics.mean(rates), 3),
            "max_trigger_rate": round(max(rates), 3),
        }
        for cat, rates in by_category.items()
    }

    return {
        "per_probe": per_probe,
        "by_category": cat_summary,
        "model": all_rows[0].get("model") if all_rows else None,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", help="Run only probes in this category")
    parser.add_argument("--probe", help="Run only this probe id (e.g. P3.1)")
    parser.add_argument("--trials", type=int, help="Override trials per probe")
    parser.add_argument("--dry-run", action="store_true", help="Validate yaml without calling LLM")
    args = parser.parse_args(argv[1:])

    spec = yaml.safe_load(PROBE_FILE.read_text())
    trials_default = spec.get("trials_default", 5)
    probes = spec.get("probes", [])

    if args.category:
        probes = [p for p in probes if p.get("category") == args.category]
    if args.probe:
        probes = [p for p in probes if p.get("id") == args.probe]
    if not probes:
        print(f"no probes match filters", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"validated {len(probes)} probes")
        for p in probes:
            print(f"  {p['id']} {p['category']:30} {p['name']}")
        return 0

    settings = get_settings()
    if not settings.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY unset; aborting", file=sys.stderr)
        return 2

    llm = LLMClient(tier="dev")
    all_rows: list[dict] = []

    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_JSONL.open("w", encoding="utf-8") as f:
        for probe in probes:
            n = args.trials if args.trials is not None else probe.get("trials", trials_default)
            log.info("== %s %s (trials=%d) ==", probe["id"], probe["name"], n)
            rows = _run_one(probe, llm, n)
            for row in rows:
                f.write(json.dumps(row) + "\n")
            all_rows.extend(rows)

    summary = _aggregate(all_rows)
    RESULTS_JSON.write_text(json.dumps(summary, indent=2))

    # Console summary
    print("\n=== Probe trigger rates (sorted) ===")
    sorted_probes = sorted(summary["per_probe"].items(), key=lambda kv: -kv[1]["trigger_rate"])
    for pid, d in sorted_probes:
        bar = "#" * int(d["trigger_rate"] * 20)
        print(f"  {pid:6} {d['category']:30} trigger={d['trigger_rate']:.2f} {bar}")
    print("\n=== By category (mean trigger rate) ===")
    for cat, d in sorted(summary["by_category"].items(), key=lambda kv: -kv[1]["mean_trigger_rate"]):
        print(f"  {cat:30} mean={d['mean_trigger_rate']:.2f} max={d['max_trigger_rate']:.2f} (n={d['n_probes']})")
    print(f"\nrows: {RESULTS_JSONL} | summary: {RESULTS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
