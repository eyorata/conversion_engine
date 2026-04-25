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
| HubSpot contact upsert + note logging | working (REST SDK + custom property provisioning) |
| Cal.com booking | working (slot lookup, booking create, booking webhook) |
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

34 passing. Covers:
- Kill switch on both channels (5 tests) — default-deny, force-sink, drop if no sink
- STOP/HELP classifier (4 tests)
- Tenacious policy (13 tests) — hiring, funding, layoff, leadership
  over-claims, capacity commitment, pricing, style filler, gap disparagement,
  per-channel length
- ICP classifier (6 tests) — all four segments + Segment 4 AI-maturity gate
- **Webhook events (4 tests)** — email bounce marks undeliverable, complaint
  opts-out, delivered/opened acked-not-orchestrated, malformed returns 400
- **SMS channel-hierarchy gate (2 tests)** — cold contact forced to email
  even when LLM picks SMS; warm contact (prior email reply) can receive SMS

## Rubric self-assessment

| Rubric | Target | Evidence |
|--------|--------|----------|
| Outbound email handler | Mastered | Resend provider; `/email/inbound` handles bounce / complaint / delivered / reply distinctly; send error + malformed payload handled |
| SMS handler | Mastered | Africa's Talking; bidirectional; **hard SMS gate on prior-email-reply** (orchestrator line refuses LLM's SMS choice for cold contacts, forces email) |
| CRM + calendar | Competent | HubSpot writes now include `icp_segment`, `icp_confidence`, `ai_maturity_score`, `ai_maturity_confidence`, `last_funding_type`, `layoffs_event_count_120d`, `job_velocity_ratio`, `leadership_change_role`, `last_enriched_at`, `tenacious_booking_id`. Booking -> HubSpot upsert links same `contact_id`; Cal.com booking lifecycle now has an inbound webhook route. Still REST, not MCP. |
| Signal enrichment | Mastered | All 4 sources (Crunchbase ODM, Playwright jobs, layoffs.fyi CSV, leadership overrides+press); no login/bypass; merged `hiring_signal_brief` with per-signal `confidence` field |
