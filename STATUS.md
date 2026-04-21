# Status

Last updated: 2026-04-21 (Day 0 → interim)

## Day 0 — Pre-flight

| Item | Status | Note |
|------|--------|------|
| Africa's Talking sandbox | [ ] | User to create account; fill AT_API_KEY and AT_SHORTCODE in .env |
| HubSpot Developer Sandbox | [ ] | User to create app; fill HUBSPOT_ACCESS_TOKEN in .env |
| Cal.com via Docker | [ ] | `docker compose up` from cal.com repo; fill CALCOM_* in .env |
| Langfuse cloud | [ ] | Free tier account; fill LANGFUSE_* in .env |
| τ²-Bench cloned | [x] scaffold ready | `git clone sierra-research/tau2-bench` into repo root |
| Shared Voice Rig | skip | bonus tier only |
| Evidence-graph scaffold | [x] | see `memo/evidence_graph.schema.json` |

## Act I — τ²-Bench baseline

| Deliverable | Status |
|-------------|--------|
| `eval/score_log.json` (dev-tier baseline + reproduction check, 95% CI) | pending |
| `eval/trace_log.jsonl` (full dev-slice trajectories) | pending |
| `eval/baseline.md` (≤400 words) | pending |

## Act II — Production stack

| Integration | Status |
|-------------|--------|
| SMS webhook (Africa's Talking) | scaffolded |
| HubSpot MCP | scaffolded |
| Cal.com booking | scaffolded |
| Crunchbase ODM enrichment | scaffolded |
| CFPB API enrichment | scaffolded |
| Playwright news enrichment | scaffolded |
| Conversation agent (OpenRouter dev tier) | scaffolded |
| Langfuse tracing | scaffolded |

## Interim (Wed Apr 22, 21:00 UTC)

- [ ] End-to-end SMS conversation transcript
- [ ] HubSpot contact screenshot with all fields populated
- [ ] Cal.com booking screenshot
- [ ] p50/p95 latency across ≥20 interactions
- [ ] PDF interim report
