# Act I — τ²-Bench Baseline

## What was reproduced

`eval/tau2_runner.py` wraps the Sierra Research τ²-Bench harness and, on every
run, writes both a `score_log.json` summary (pass@1 with 95% CI, cost,
p50/p95 latency) and a full `trace_log.jsonl` trajectory line per task. The
runner partitions the retail domain into a 30-task dev slice and a 20-task
held-out slice per the challenge brief; the held-out slice is sealed and
never evaluated against during development.

**Mode.** The runner operates in two modes. When the upstream `tau2` package
is importable it routes every task through the harness under the pinned
dev-tier model (`qwen/qwen3-next-80b-a3b` via OpenRouter). When it is not
yet installed — or when the OpenRouter key is unset as in the interim
snapshot below — it falls back to a compact dry-run task set (five
qualification scenarios cycled) that exercises the same scoring, tracing,
and cost-attribution pipeline. `baseline.md` reports which mode the run
used so no numbers are claimed under false pretense.

## Interim numbers (dry-run, unset OpenRouter key)

Run id: `dev-20260422T170913`, 3 trials × 10 tasks on the dev slice.

| Metric | Value |
|--------|-------|
| pass@1 mean | 0.00 |
| 95% CI (±) | 0.00 |
| cost per run | $0.00 |
| p50 latency | 3.0 s |
| p95 latency | 3.0 s |

Every task failed because the LLM calls were short-circuited by a missing
OpenRouter credential. The 3-second per-task wall time is the `httpx` retry
backoff. This is the honest floor: the pipeline executes, emits traces,
and records costs. The numbers will lift above zero as soon as the
OpenRouter key in `.env` is populated and the upstream `tau2-bench` repo
is cloned.

**Reference.** τ²-Bench retail pass@1 published ceiling is ~42% on
GPT-5-class models and ~30% on telecom (Sierra Research, Feb 2026). Our
dev-tier target after Day 0 completion is within 3 percentage points of
the dev-tier Qwen3 reference that program staff will publish on Day 1.

## Cost per run

Dry-run cost is $0.00 (no API call succeeded). Projected cost under full
execution: ~$0.02 per 10-task trial at Qwen3 pricing (input ≈ 150 tokens,
output ≈ 40 tokens, $0.15/$0.60 per 1M). A 30-task × 5-trial dev baseline
is projected at ≤ $0.30, well inside the ≤$4 Day-1–4 budget.

## Unexpected behavior

1. `tau2-bench` is not installed in the interim snapshot; the runner uses
   its dry-run fallback and declares `mode=dry_run` in `score_log.json`.
   Full mode activates after `pip install -e ./tau2-bench`.
2. The `httpx` retry policy adds deterministic 3 s latency on every
   dry-run failure. This dominates the interim p50/p95. After credentials
   are in place the expected p50 is 2–4 s per task (Qwen3 generation
   latency), not retry backoff.
3. The runner appends to `score_log.json` on every invocation. This
   preserves the reproduction history needed for the evidence graph at
   Act V.

(Word count: 397)
