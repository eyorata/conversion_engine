# Conversion Engine — Tenacious Edition

Automated outbound lead-generation and conversion system for Tenacious
Consulting and Outsourcing. Finds prospective clients in public data,
qualifies them against a real intent signal, runs a nurture sequence, and
books a discovery call with a Tenacious delivery lead.

Email is the primary channel. SMS is secondary for warm-lead scheduling
handoff only. Voice is reserved for the human-delivered discovery call.

Benchmark: τ²-Bench retail. Enrichment: Crunchbase ODM + layoffs.fyi +
public job-post velocity + leadership change + AI maturity 0–3 score +
competitor gap brief.

## Architecture

```
 outbound seed --->  enrichment pipeline  ------> hiring_signal_brief.json
 (Crunchbase id)     ├── Crunchbase ODM (firmo)   competitor_gap_brief.json
                     ├── layoffs.fyi (120d)              |
                     ├── job posts (60d velocity)        v
                     ├── leadership change (90d)   agent (LLM, dev/eval tiers)
                     ├── AI maturity 0-3 score      ├── 4 ICP segments
                     └── competitor gap brief       ├── per-segment language
                                                     ├── hard policy guardrails
                                                     │   (no unverified claims,
                                                     │    no capacity promise,
                                                     │    no pricing)
                                                     ├── tool: Resend email
                                                     ├── tool: AT SMS (warm only)
                                                     ├── tool: Cal.com booking
                                                     └── tool: HubSpot MCP
                                                            |
                                                            v
                                                   Langfuse (traces + cost)
```

Kill switch: all outbound routed to `STAFF_SINK_EMAIL` / `STAFF_SINK_NUMBER`
unless `LIVE_OUTBOUND=1`. Default MUST be unset per the data-handling policy.

## Repository layout

| Path | Purpose |
|------|---------|
| `agent/` | email handler (primary), SMS gateway (secondary), orchestrator, prompts, policy, HubSpot + Cal.com + LLM + tracing clients, FastAPI app |
| `enrichment/` | Crunchbase ODM loader, layoffs.fyi parser, job-post velocity, leadership detector, AI maturity scorer, ICP classifier, competitor gap brief, unified pipeline |
| `eval/` | τ²-Bench harness wrapper, `score_log.json`, `trace_log.jsonl`, `baseline.md` |
| `probes/` | Adversarial probe library (Act III) |
| `data/` | Seed snapshots (job posts, leadership overrides, layoffs seed). Heavy downloads (Crunchbase CSV, live layoffs) gitignored |
| `scripts/` | Day 0 smoke test, synthetic conversation runner |
| `tests/` | Unit tests (28 passing) |
| `docs/` | Data handling policy, Day 0 checklist |
| `memo/` | Final 2-page decision memo and `evidence_graph.json` |

## Setup

Prerequisites: Python 3.11+, Docker (for Cal.com self-host), Git, free
GitHub account for τ²-Bench clone.

```bash
python -m venv .venv
source .venv/Scripts/activate     # git-bash on Windows
pip install -r requirements.txt

cp .env.example .env
# edit .env — see docs/day0_checklist.md

playwright install chromium       # only needed for live job-post scraping

# pull external benchmark (gitignored)
git clone https://github.com/sierra-research/tau2-bench.git
pip install -e ./tau2-bench
```

## Running

```bash
# unit tests
python -m pytest tests/ -v

# Day 0 smoke tests (prints pass/fail for each integration)
python -m scripts.day0_smoke_test all

# τ²-Bench retail dev-slice baseline (Act I)
python -m eval.tau2_runner --slice dev --trials 5 \
    --out eval/score_log.json --traces eval/trace_log.jsonl

# SMS + email webhook server (FastAPI)
uvicorn agent.app:app --host 0.0.0.0 --port 8080 --reload

# 20 synthetic interactions end-to-end for p50/p95
python -m scripts.synthetic_conversation --n 20 \
    --out data/runs/synthetic.jsonl
```

## Data handling

All prospects during the challenge week are synthetic, derived from public
Crunchbase firmographics plus fictitious contact details. The program-operated
SMS rig and email sink receive all outbound. See [docs/data_policy.md](docs/data_policy.md).

## Cost envelope

≤ $10 total per the 2026-04-23 program update. Dev-tier LLM (OpenRouter
Qwen3 / DeepSeek) for Days 1–4. Eval-tier (Claude Sonnet 4.6) for the
sealed held-out run only, trials=1. Per-trace cost attribution via Langfuse.

## τ²-Bench baseline

Per the 2026-04-23 program update, the baseline is provided by staff and
lives in [eval/baseline.md](eval/baseline.md), [eval/score_log.json](eval/score_log.json),
and [eval/trace_log.jsonl](eval/trace_log.jsonl). Trainees do not re-run it.
Reference: pass@1 = 0.727, 95% CI [0.65, 0.79], 30 retail tasks × 5 trials,
avg cost $0.02/run. Act IV held-out evaluation runs at **trials = 1**.

## Status

See [STATUS.md](STATUS.md) for live progress.
