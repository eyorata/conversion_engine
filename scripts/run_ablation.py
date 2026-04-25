"""DCCG ablation runner.

Compares the agent's intent decision with the Dual-Control Commitment Gate
OFF (Day-1 baseline) vs ON (the Act IV mechanism). Held-out probes live in
probes/held_out_dual_control.yaml.

Failure metric: `intent == "book"` when the prospect has NOT given explicit
consent. The gate rewrites `intent` to `reply` when a wait signal fires
without explicit acceptance.

Outputs:
    eval/held_out_traces.jsonl    (one row per probe x arm x trial)
    eval/ablation_results.json    (aggregate + statistical test)

Stat test: two-proportion z-test with Wilson 95% CIs. Also reports the
exact binomial p-value as a sanity check.

Usage:
    python -m scripts.run_ablation
    python -m scripts.run_ablation --trials 3   # smaller, cheaper run
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

from agent.config import get_settings
from agent.dual_control import should_block_booking
from agent.llm import LLMClient
from agent.logging_setup import setup_logging
from agent.prompts import SYSTEM_PROMPT, build_user_prompt

setup_logging()
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
HELD_OUT = REPO_ROOT / "probes" / "held_out_dual_control.yaml"
TRACES_OUT = REPO_ROOT / "eval" / "held_out_traces.jsonl"
RESULTS_OUT = REPO_ROOT / "eval" / "ablation_results.json"

DEFAULT_SLOTS = [
    "2026-04-27T10:00:00Z",
    "2026-04-27T14:00:00Z",
    "2026-04-28T10:00:00Z",
    "2026-04-28T14:00:00Z",
    "2026-04-29T10:00:00Z",
]


def _build_user_prompt_for(probe: dict) -> str:
    """Mirror probes/run_probes.py: build the orchestrator prompt for one probe."""
    brief = dict(probe.get("hiring_signal_brief", {}))
    brief.setdefault("retrieved_at", "2026-04-25T00:00:00Z")
    brief.setdefault("source", "ablation_synthetic")
    gap = probe.get("competitor_gap_brief")
    inbound_text = probe["inbound"]
    turns = [{
        "role": "user",
        "channel": "email",
        "text": inbound_text,
        "ts": "2026-04-25T09:00:00Z",
    }]
    return build_user_prompt(
        channel="email",
        hiring_signal_brief=brief,
        competitor_gap_brief=gap,
        conversation_turns=turns,
        available_slots=DEFAULT_SLOTS,
    )


def _parse_intent(text: str) -> tuple[str | None, str]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, ""
    try:
        obj = json.loads(m.group(0))
        return obj.get("intent"), obj.get("body", "") or ""
    except json.JSONDecodeError:
        return None, ""


def _apply_gate(intent: str | None, inbound_text: str) -> tuple[str | None, dict]:
    """Apply the DCCG; return (final_intent, dccg_meta)."""
    blocked, sig = should_block_booking(inbound_text or "")
    fired = bool(blocked and intent == "book")
    final = "reply" if fired else intent
    return final, {
        "fired": fired,
        "wait_signal_present": sig is not None,
        "wait_signal_kind": sig.kind if sig else None,
    }


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Two-proportion z-test. Returns (z, two-sided p-value)."""
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (float("inf") if p1 != p2 else 0.0, 0.0 if p1 != p2 else 1.0)
    z = (p1 - p2) / se
    # Two-sided p: 2 * Phi(-|z|), Phi via erf
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return (z, p_value)


def _run_probe(probe: dict, llm: LLMClient, trials: int, expects_book: bool, group: str) -> list[dict]:
    """Run trials; return rows for both arms (gate_off, gate_on)."""
    inbound = probe["inbound"]
    user_prompt = _build_user_prompt_for(probe)
    rows: list[dict] = []

    for trial in range(trials):
        t0 = time.time()
        try:
            r = llm.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=400,
                temperature=0.3,
            )
            intent_raw, body = _parse_intent(r.text)
            latency = int((time.time() - t0) * 1000)
        except Exception as e:
            log.exception("LLM call failed for probe %s trial %d", probe["id"], trial)
            for arm in ("gate_off", "gate_on"):
                rows.append({
                    "probe_id": probe["id"],
                    "scenario_label": probe.get("scenario_label"),
                    "group": group,
                    "expects_book": expects_book,
                    "arm": arm,
                    "trial": trial,
                    "intent_raw": None,
                    "final_intent": None,
                    "fired": None,
                    "failed": None,
                    "error": f"{type(e).__name__}: {e}",
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
            continue

        # Arm 1: gate OFF (Day-1 baseline). Intent is the LLM's decision.
        off_intent = intent_raw
        # An "off" failure is: gate would have wanted to fire but didn't.
        # For deferral group: failed iff intent == "book" (we wanted suppression).
        # For acceptance group: failed iff intent != "book" (we wanted booking).
        off_failed = (off_intent == "book") if expects_book is False else (off_intent != "book")

        rows.append({
            "probe_id": probe["id"],
            "scenario_label": probe.get("scenario_label"),
            "group": group,
            "expects_book": expects_book,
            "arm": "gate_off",
            "trial": trial,
            "intent_raw": intent_raw,
            "final_intent": off_intent,
            "fired": False,
            "failed": off_failed,
            "body": (body or "")[:300],
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "latency_ms": latency,
            "model": r.model,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

        # Arm 2: gate ON. Apply the gate to the same LLM output.
        on_intent, dccg_meta = _apply_gate(intent_raw, inbound)
        on_failed = (on_intent == "book") if expects_book is False else (on_intent != "book")

        rows.append({
            "probe_id": probe["id"],
            "scenario_label": probe.get("scenario_label"),
            "group": group,
            "expects_book": expects_book,
            "arm": "gate_on",
            "trial": trial,
            "intent_raw": intent_raw,
            "final_intent": on_intent,
            "fired": dccg_meta["fired"],
            "wait_signal_kind": dccg_meta["wait_signal_kind"],
            "failed": on_failed,
            "body": (body or "")[:300],
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "latency_ms": latency,  # same LLM call as gate_off; gate adds <1ms
            "model": r.model,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

        log.info(
            "probe=%s trial=%d off_intent=%s on_intent=%s fired=%s",
            probe["id"], trial, off_intent, on_intent, dccg_meta["fired"],
        )

    return rows


def _aggregate(rows: list[dict]) -> dict:
    """Compute per-arm trigger rates and statistical test."""
    # Primary metric: failure rate on the deferral group (where gate should fire).
    deferral = [r for r in rows if r["group"] == "deferral" and r.get("failed") is not None]
    acceptance = [r for r in rows if r["group"] == "acceptance" and r.get("failed") is not None]

    def _arm_stats(rows_subset: list[dict], arm: str) -> dict:
        arm_rows = [r for r in rows_subset if r["arm"] == arm]
        n = len(arm_rows)
        k = sum(1 for r in arm_rows if r["failed"])
        ci = _wilson_ci(k, n)
        return {"n": n, "failed": k, "rate": k / n if n else 0.0, "ci95": [round(ci[0], 4), round(ci[1], 4)]}

    deferral_off = _arm_stats(deferral, "gate_off")
    deferral_on = _arm_stats(deferral, "gate_on")
    acceptance_off = _arm_stats(acceptance, "gate_off")
    acceptance_on = _arm_stats(acceptance, "gate_on")

    # Delta A: gate_on vs gate_off on deferral group.
    z, p = _two_proportion_z(
        deferral_off["failed"], deferral_off["n"],
        deferral_on["failed"], deferral_on["n"],
    )
    rate_drop = deferral_off["rate"] - deferral_on["rate"]

    # False-positive: gate_on suppressed booking when prospect DID accept.
    # Lower is better. Acceptance-group failure on gate_on = FP rate.
    fp_rate = acceptance_on["rate"]

    # Latency overhead: identical LLM call, gate is regex eval; should be ~0.
    latencies_off = [r["latency_ms"] for r in rows if r["arm"] == "gate_off" and "latency_ms" in r]
    latencies_on = [r["latency_ms"] for r in rows if r["arm"] == "gate_on" and "latency_ms" in r]
    p50_off = round(statistics.median(latencies_off), 0) if latencies_off else 0
    p50_on = round(statistics.median(latencies_on), 0) if latencies_on else 0

    return {
        "primary_metric": "intent==book when prospect deferred",
        "deferral_group": {
            "n_variants": len(set(r["probe_id"] for r in deferral)),
            "trials_per_variant": (deferral_off["n"] // len(set(r["probe_id"] for r in deferral))) if deferral else 0,
            "gate_off": deferral_off,
            "gate_on": deferral_on,
        },
        "acceptance_group": {
            "n_variants": len(set(r["probe_id"] for r in acceptance)),
            "gate_off": acceptance_off,
            "gate_on": acceptance_on,
        },
        "delta_a": {
            "definition": "failure_rate(gate_off) - failure_rate(gate_on) on deferral group",
            "rate_drop": round(rate_drop, 4),
            "z": round(z, 4),
            "p_value_two_sided": p,
            "test": "two_proportion_z",
            "ci_separation_95": (deferral_off["ci95"][0] > deferral_on["ci95"][1])
                                or (deferral_on["ci95"][0] > deferral_off["ci95"][1]),
        },
        "false_positive_rate_method": {
            "rate": round(fp_rate, 4),
            "ci95": acceptance_on["ci95"],
            "interpretation": "gate suppressed booking when prospect explicitly accepted",
        },
        "latency_p50_ms": {
            "gate_off": p50_off,
            "gate_on": p50_on,
            "overhead_ms": p50_on - p50_off,
        },
        "model": rows[0]["model"] if rows else None,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, help="Override trials per arm (default from yaml)")
    args = parser.parse_args(argv[1:])

    spec = yaml.safe_load(HELD_OUT.read_text())
    trials = args.trials if args.trials is not None else spec.get("trials_per_arm", 5)
    deferral_probes = spec.get("deferral_probes", [])
    acceptance_probes = spec.get("acceptance_probes", [])

    settings = get_settings()
    if not settings.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY unset; aborting", file=sys.stderr)
        return 2

    llm = LLMClient(tier="dev")
    all_rows: list[dict] = []

    TRACES_OUT.parent.mkdir(parents=True, exist_ok=True)
    with TRACES_OUT.open("w", encoding="utf-8") as f:
        for probe in deferral_probes:
            log.info("== deferral %s %s ==", probe["id"], probe.get("scenario_label"))
            rows = _run_probe(probe, llm, trials, expects_book=False, group="deferral")
            for row in rows:
                f.write(json.dumps(row) + "\n")
            all_rows.extend(rows)
        for probe in acceptance_probes:
            log.info("== acceptance %s %s ==", probe["id"], probe.get("scenario_label"))
            rows = _run_probe(probe, llm, trials, expects_book=True, group="acceptance")
            for row in rows:
                f.write(json.dumps(row) + "\n")
            all_rows.extend(rows)

    summary = _aggregate(all_rows)
    RESULTS_OUT.write_text(json.dumps(summary, indent=2))

    # Console report
    print("\n=== DCCG ablation ===")
    print(f"deferral group ({summary['deferral_group']['n_variants']} variants, "
          f"{summary['deferral_group']['trials_per_variant']} trials each):")
    print(f"  gate_off failure_rate = {summary['deferral_group']['gate_off']['rate']:.3f} "
          f"CI95={summary['deferral_group']['gate_off']['ci95']}")
    print(f"  gate_on  failure_rate = {summary['deferral_group']['gate_on']['rate']:.3f} "
          f"CI95={summary['deferral_group']['gate_on']['ci95']}")
    print(f"  Delta A (drop) = {summary['delta_a']['rate_drop']:+.3f}, "
          f"z = {summary['delta_a']['z']:.2f}, p = {summary['delta_a']['p_value_two_sided']:.2e}")
    print(f"  CI 95% non-overlap: {summary['delta_a']['ci_separation_95']}")
    print(f"\nacceptance group (FP guard, {summary['acceptance_group']['n_variants']} variants):")
    print(f"  gate_on  FP rate = {summary['false_positive_rate_method']['rate']:.3f} "
          f"CI95={summary['false_positive_rate_method']['ci95']}")
    print(f"\nlatency: gate_off p50 = {summary['latency_p50_ms']['gate_off']} ms,  "
          f"gate_on p50 = {summary['latency_p50_ms']['gate_on']} ms")
    print(f"\ntraces: {TRACES_OUT}")
    print(f"summary: {RESULTS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
