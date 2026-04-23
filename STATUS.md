# Status

Last updated: 2026-04-22 (interim day, Tenacious edition)

## Day 0 — Pre-flight

| Item | Status | Note |
|------|--------|------|
| Resend (primary email) | [ ] | Free tier; fill `RESEND_API_KEY` + `RESEND_FROM_EMAIL` in .env |
| Africa's Talking sandbox (secondary SMS) | [ ] | User to create; fill `AT_API_KEY` + `AT_SHORTCODE` |
| HubSpot Developer Sandbox | [ ] | User to create; fill `HUBSPOT_ACCESS_TOKEN` |
| Cal.com via Docker | [ ] | `docker compose up` from cal.com repo; fill `CALCOM_*` |
| Langfuse cloud | [ ] | Free tier; fill `LANGFUSE_*` |
| OpenRouter dev-tier LLM | [ ] | $5 credit; fill `OPENROUTER_API_KEY` |
| τ²-Bench cloned | [x] scaffold ready | `git clone sierra-research/tau2-bench` into repo root |
| Evidence-graph scaffold | planned | `memo/evidence_graph.schema.json` on Day 5 |

## Act I — τ²-Bench baseline

Program update 2026-04-23: baseline is provided by staff; trainees no longer
run their own. Evaluation in Act IV uses 1 trial, not 5. Budget is $10/person.

| Deliverable | Status |
|-------------|--------|
| `eval/score_log.json` (provided: pass@1=0.7267, 95% CI [0.65, 0.79]) | committed as given |
| `eval/trace_log.jsonl` (provided: 150 simulations across 30 retail tasks) | committed as given |
| `eval/baseline.md` (provided) | committed as given |
| `eval/tau2_runner.py` (retained for Act IV 1-trial held-out eval) | scaffolded |

## Act II — Production stack + enrichment

| Integration | Status |
|-------------|--------|
| Email (Resend) primary — handler + kill switch | scaffolded + tested |
| SMS (Africa's Talking) secondary — handler + kill switch + STOP/HELP | scaffolded + tested |
| HubSpot contact upsert + note logging | scaffolded |
| Cal.com booking | scaffolded |
| Crunchbase ODM enrichment | working (CSV loader, 1000 records) |
| layoffs.fyi signal (120d) | working (with seed fallback) |
| Job-post velocity (60d) | working (frozen snapshot + live mode) |
| Leadership change (90d) | working (override file + extensible) |
| AI maturity 0–3 scorer | working (per-signal justification, confidence) |
| ICP classifier (4 segments) | working |
| Competitor gap brief | working (peer lookup + gap practices) |
| Unified pipeline -> 2 briefs | working |
| Conversation agent (OpenRouter dev tier) | scaffolded |
| Langfuse tracing | scaffolded (no-op fallback) |

## Interim (Wed Apr 22, 21:00 UTC)

- [x] Architecture + stack documented in README
- [ ] End-to-end email conversation transcript (synthetic)
- [ ] HubSpot contact screenshot
- [ ] Cal.com booking screenshot
- [ ] Resend, AT, HubSpot, Cal.com, Langfuse "verified running" evidence
- [ ] Enrichment pipeline sample output (`hiring_signal_brief.json` + `competitor_gap_brief.json`)
- [ ] τ²-Bench baseline on dev slice with 95% CI
- [ ] p50/p95 latency across ≥20 email+SMS interactions
- [ ] Interim PDF report

## Final (Sat Apr 25, 21:00 UTC)

- [ ] 30+ adversarial probes, failure taxonomy, target failure mode
- [ ] Mechanism on sealed held-out slice with Δ_A > 0 at p<0.05
- [ ] 2-page memo + evidence graph
- [ ] Demo video (≤8 min)

## Tests

28 passing. Covers kill switch (both channels), STOP classifier, Tenacious
policy (hiring/funding/layoff/leadership over-claims, capacity commitment,
pricing, style filler, gap disparagement, length budgets), ICP classifier
across all four segments.
