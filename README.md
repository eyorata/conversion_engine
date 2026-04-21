# Conversion Engine — Acme ComplianceOS Edition

SMS + CRM agent that qualifies inbound and outbound leads for a fictional mid-market B2B SaaS (Acme ComplianceOS) selling compliance software to US financial institutions. Grounds every conversation in real Crunchbase firmographics and CFPB complaint data. Books discovery calls via Cal.com and writes back to HubSpot.

Built for the tenx academy Week 10 challenge. Benchmark: τ²-Bench retail.

## Architecture

```
  inbound SMS ─┐                                  ┌─ Crunchbase ODM (firmographics)
  web form  ───┼─> webhook ─> enrichment ────────┼─ CFPB API (complaints, last 180d)
  outbound ────┘              pipeline            └─ Playwright (news/press)
                                   │
                                   ▼
                         agent (OpenRouter dev / Claude eval)
                         ├── policy: TCPA + STOP/HELP
                         ├── policy: no unverified compliance claims
                         ├── tool: HubSpot MCP (contacts, deals, notes)
                         ├── tool: Cal.com booking
                         └── tool: SMS send (Africa's Talking sandbox)
                                   │
                                   ▼
                         Langfuse (every trace, every $)
```

## Repository layout

| Path | Purpose |
|------|---------|
| `agent/` | SMS webhook, conversation agent, tool integrations |
| `enrichment/` | Crunchbase ODM loader, CFPB client, Playwright news scraper |
| `eval/` | τ²-Bench harness wrapper, score_log.json, trace_log.jsonl |
| `probes/` | Adversarial probe library (Act III) |
| `data/` | Local caches — gitignored |
| `scripts/` | One-off setup and data-prep scripts |
| `memo/` | Final 2-page decision memo and evidence_graph.json |

## Setup (Day 0)

Prerequisites: Python 3.11+, Docker (for Cal.com), a free GitHub account for cloning τ²-Bench.

```bash
# 1. clone and install
git clone <this repo> conversion_engine
cd conversion_engine
python -m venv .venv
source .venv/Scripts/activate   # git-bash on Windows
pip install -r requirements.txt
playwright install chromium

# 2. clone tau2-bench (external, gitignored)
git clone https://github.com/sierra-research/tau2-bench.git

# 3. fill in .env
cp .env.example .env
# edit .env — see day0_checklist.md for each account

# 4. smoke test each integration
python -m scripts.day0_smoke_test
```

See [docs/day0_checklist.md](docs/day0_checklist.md) for step-by-step account setup (Africa's Talking, HubSpot sandbox, Cal.com, Langfuse).

## Running

```bash
# smoke-test the τ²-Bench baseline (Act I)
python -m eval.tau2_runner --slice dev --trials 5

# run the SMS webhook server
uvicorn agent.app:app --host 0.0.0.0 --port 8080 --reload

# run an end-to-end synthetic conversation
python -m scripts.synthetic_conversation --n 20
```

## Data handling policy

This is a challenge build. All outbound SMS must route to the staff sink unless `LIVE_OUTBOUND=1` is explicitly set. Default is unset. See [docs/data_policy.md](docs/data_policy.md) for the full policy. A kill switch is implemented in `agent/sms_gateway.py`.

## Cost envelope

Target ≤ $20 total. Dev-tier LLM (OpenRouter Qwen3/DeepSeek) for Days 1–4 (≤$4). Eval-tier (Claude Sonnet 4.6) for the sealed held-out run only (≤$12). Per-trace cost attribution via Langfuse.

## Status

See [STATUS.md](STATUS.md) for live progress against the Day 0 → Act V plan.
