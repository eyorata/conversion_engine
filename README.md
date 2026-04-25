# Conversion Engine - Tenacious Edition

Automated outbound lead-generation and conversion system for Tenacious Consulting and Outsourcing. The system enriches a prospect from public signals, drafts a response through the LLM backbone, routes through channel-specific handlers, writes CRM activity, and books discovery calls through Cal.com.

Email is the primary channel. SMS is secondary and is only allowed for warm-lead scheduling handoff after a prior email reply.

## Architecture

```text
outbound seed / inbound reply
        |
        v
enrichment pipeline
  |- Crunchbase ODM firmographics + funding
  |- layoffs.fyi 120d signal
  |- public job-post velocity (60d)
  |- leadership change (90d)
  |- AI maturity 0-3 scoring
  `- competitor gap brief
        |
        v
agent orchestrator
  |- conversation state
  |- prompt builder + LLM client
  |- policy guardrails
  |- dual-control booking gate
  |- channel hierarchy (email first, SMS only for warm leads)
  |- Resend send + reply webhook
  |- Africa's Talking send + inbound webhook
  |- Cal.com slot lookup + booking + booking webhook
  `- HubSpot contact upsert + note logging
        |
        v
Langfuse tracing / cost attribution
```

Kill switch:
all outbound routes to `STAFF_SINK_EMAIL` / `STAFF_SINK_NUMBER` unless `LIVE_OUTBOUND=1`.

## Repository Layout

| Path | Purpose |
|------|---------|
| `agent/` | FastAPI app, orchestrator, email/SMS handlers, Cal.com client, HubSpot client, prompts, tracing, state, and Act IV dual-control mechanism. |
| `enrichment/` | Public-signal collection and merging: Crunchbase, layoffs, jobs, leadership, AI maturity, ICP classification, competitor-gap generation, and `competitor_gap_brief` schema artifacts. |
| `eval/` | Baseline artifacts, ablation outputs, and `method.md` for the mechanism writeup. |
| `probes/` | Adversarial probe library, taxonomy, held-out set, and target failure documentation. |
| `scripts/` | Smoke tests, HubSpot property provisioning, synthetic runs, probe runner, and ablation runner. |
| `tests/` | Unit tests for policy, webhook handling, kill switches, SMS gate, and mechanism behavior. |
| `docs/` | Human-facing setup and policy docs, including Day 0 checklist and data handling. |
| `memo/` | Interim/final reporting artifacts and evidence-graph material. |
| `data/` | Frozen public-data snapshots and seed files used by the enrichment pipeline. |
| `cal.com/` | Local self-hosted Cal.com checkout used for Day 0 booking integration testing. |
| `tau2-bench/` | External benchmark checkout used for the course baseline and held-out harness. |
| `tenacious_sales_data/` | Seed materials, style guide, policy notes, and benchmark numbers used by prompts and evaluation. |
| `.venv/` | Local virtual environment created during setup; user-local, not part of the application logic. |
| `.pytest_cache/` | Test runner cache generated locally. |

## Prerequisites

- Python `3.11+`
- Docker Desktop or equivalent Docker Engine
- Git
- PowerShell on Windows or any shell that can create and activate a venv
- Chromium for Playwright live job-page checks: `playwright install chromium`

All Python dependencies are pinned in [requirements.txt](C:/Users/user/Documents/tenx_academy/conversion_engine/requirements.txt).

## Setup

Recommended Windows PowerShell bootstrap:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
playwright install chromium
git clone https://github.com/sierra-research/tau2-bench.git
pip install -e ./tau2-bench
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Configuration Variables

Use [.env.example](C:/Users/user/Documents/tenx_academy/conversion_engine/.env.example) as the source of truth. The most important groups are:

| Variable | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | Dev-tier LLM key for probes, synthetic runs, and most local development. |
| `DEV_MODEL` | Dev-tier model id. |
| `ANTHROPIC_API_KEY`, `EVAL_MODEL` | Eval-tier model settings for sealed held-out work only. |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | Outbound email provider credentials and sender identity. |
| `STAFF_SINK_EMAIL` | Safe sink inbox used when `LIVE_OUTBOUND` is off. |
| `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE` | Africa's Talking SMS credentials. |
| `AT_WEBHOOK_URL` | Public callback URL for Africa's Talking inbound SMS. |
| `STAFF_SINK_NUMBER` | Safe SMS sink number used when `LIVE_OUTBOUND` is off. |
| `HUBSPOT_MODE`, `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` | HubSpot backend selection plus developer sandbox credentials. Default is REST; MCP mode requires a configured MCP server command. |
| `HUBSPOT_MCP_COMMAND`, `HUBSPOT_MCP_ARGS`, `HUBSPOT_MCP_UPSERT_TOOL`, `HUBSPOT_MCP_NOTE_TOOL` | Optional HubSpot MCP server process and tool names when running in MCP mode. |
| `CALCOM_BASE_URL`, `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID` | Cal.com API base URL and booking configuration. |
| `CALCOM_WEBHOOK_SECRET` | Optional shared secret for the Cal.com booking webhook route. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Observability/tracing configuration. |
| `LIVE_OUTBOUND` | Safety switch; if not `1`, outbound email/SMS is rerouted to sink destinations. |
| `ENV`, `LOG_LEVEL`, `PORT` | Runtime configuration for the FastAPI server. |

## Local Run Order

1. Create and activate the virtual environment.
2. Install pinned dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and fill the required provider keys.
4. Provision HubSpot custom properties once on a fresh sandbox:
   `python -m scripts.provision_hubspot_properties`
5. Start the FastAPI app:
   `uvicorn agent.app:app --host 0.0.0.0 --port 8080 --reload`
6. If testing live callbacks locally, start a public tunnel:
   `ngrok http 8080`
7. Start Cal.com separately from `cal.com/` if you need real slot lookup / booking.
8. Run smoke tests:
   `python -m scripts.day0_smoke_test all`
9. Run synthetic traffic:
   `python -m scripts.synthetic_conversation --n 20 --out data/runs/synthetic.jsonl`

## Useful Commands

```bash
# unit tests
python -m pytest tests/ -v

# provider / stack smoke tests
python -m scripts.day0_smoke_test all

# synthetic conversations
python -m scripts.synthetic_conversation --n 20 --out data/runs/synthetic.jsonl

# adversarial probes
python -m scripts.run_probes

# Act IV ablation
python -m scripts.run_ablation
```

## Handoff Notes

Known limitations and next steps a successor will hit quickly:

1. HubSpot defaults to the official REST SDK. MCP mode is now wired as a backend option, but it still depends on an actual HubSpot MCP server being available in the runtime environment.
2. Live job-page scraping now checks `robots.txt` and stays on a single public page, but broad source coverage still depends on the provided `careers_url` and frozen snapshots.
3. AI maturity now exposes all six rubric categories in code, but some categories depend on optional public inputs that are sparse in the current Crunchbase sample.
4. Competitor-gap evidence is stronger now, but peer quality is still limited by the committed sample dataset rather than a full market crawl.
5. Cal.com webhook handling now exists for booking lifecycle events, but production hardening would still want signature verification against the exact hosted Cal.com scheme you deploy with.

## Data Handling

All challenge-week prospects are synthetic, derived from public firmographics with fictitious contact details. Outbound remains sink-routed by default. See [data_policy.md](C:/Users/user/Documents/tenx_academy/conversion_engine/docs/data_policy.md) for the governing policy.

## Status

Live project status and rubric self-assessment live in [STATUS.md](C:/Users/user/Documents/tenx_academy/conversion_engine/STATUS.md).
