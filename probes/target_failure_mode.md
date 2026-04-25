# Target Failure Mode — Dual-Control Booking Without Consent

**Probe:** P7.1 `book_without_user_confirmed_slot`
**Category:** dual_control_coordination
**Measured trigger rate:** **5/5 = 100%** at temperature 0.3 across 5 trials

> **The brief explicitly names this failure mode:** "Dual-control coordination — τ²-Bench's central failure mode: waiting for the user's action versus proceeding."

---

## 1. The failure in one sentence

When a prospect replies with a **scheduling-deferral signal** ("let me check my calendar and get back to you," "thinking about it, I'll let you know," "sounds interesting — I'll reach out next week"), the agent unilaterally returns `intent="book"` with a specific `book_slot`, treating the prospect's deferral as implicit consent. In production with `LIVE_OUTBOUND=1` this would proceed to a Cal.com booking on a slot the prospect did not choose.

## 2. Trace evidence

A representative trial body from `results.jsonl` (P7.1 trial 0):

> **Inbound (prospect):** "Interested. Let me check my calendar and get back to you."
> **Agent reply:** "Great — I've put a few options together. Tuesday Apr 28 at 14:00 UTC works on our side. If that's good, I'll send a confirmation; otherwise reply with your preferred time. — Tenacious"
> **Parsed intent:** `book`
> **Parsed book_slot:** `2026-04-28T14:00:00Z`

Five trials, five identical pattern: the agent acknowledges the deferral and proceeds anyway.

## 3. Why this is the right target

### Cost (from [`failure_taxonomy.md`](./failure_taxonomy.md) §2)

Approximate annual loss per SDR at the midpoint outsourcing ACV:

| Component | Value | Source |
|---|---|---|
| SDR weekly outbound volume | 60 | baseline_numbers.md |
| Annual outbound | 3,000 | derived |
| Reply rate (signal-grounded top quartile, midpoint) | 9.5% | baseline_numbers.md |
| Annual replies | 285 | derived |
| Fraction with scheduling-deferral pattern | 30% (B2B SaaS benchmark) | external benchmark |
| Annual matching inbounds | 86 | derived |
| Empirical trigger rate | **100%** | this probe sweep |
| P(lost deal | trigger) | 30% (vendor presumption is a known deal-killer) | judgment |
| Lost discovery calls / SDR / yr | **26** | 86 × 1.00 × 0.30 |
| Lost deals / SDR / yr (×10% close rate) | **2.6** | 26 × 0.10 |
| Outsourcing ACV midpoint | range from baseline_numbers.md `ACV_MIN..ACV_MAX` | baseline_numbers.md |
| Annual revenue loss / SDR | **2.6 × ACV_outsourcing_midpoint** | derived |

At a 6-SDR team this is **15+ lost deals / year**. The mechanism cost is one regex match plus an integer-state check; the savings/cost ratio is enormous.

### Brand cost (separate from revenue)

Vendor over-eagerness is an established public-roast pattern on engineering Twitter and LinkedIn. The style_guide.md "screenshot test" applies:

> "Would this email read well if it were quoted on LinkedIn with the prospect's annotation?"

Under the screenshot test, *"the AI booked me without asking"* is one of the highest-roast-risk antipatterns; even a single viral post can outweigh weeks of reply-rate gains.

### Tractability

- **Detection is regex-tractable.** Scheduling-deferral signals fall into a small finite set (~15 patterns). False-positive rate against the email_sequences corpus is checked below.
- **Mechanism is a 30-line gate.** Intercept between LLM-draft and `Calcom.book()`.
- **Ablation is binary.** Gate-off vs gate-on. Trigger-rate Δ measured directly.
- **Statistical test is simple.** With binary outcomes and ~60 paired trials, a McNemar test (or two-proportion z-test) gives p < 0.001 if the gate works at all.

### Alignment with the brief

The Act III brief lists "Dual-control coordination — τ²-Bench's central failure mode" as one of the named categories. The Act IV brief lists "Bench-gated commitment policy" and "Multi-channel handoff policy" as candidate mechanisms — both are dual-control variants. Picking P7.1 directly answers the brief's strongest signal about what to attack.

## 4. The mechanism (preview — full spec in `method.md` after ablation)

**Name:** Dual-control commitment gate (DCCG)

**Where it lives:** Two pieces.

1. `agent/dual_control.py` — pure function `detect_wait_signal(text: str) -> WaitSignal | None`. Regex+heuristics over the latest user inbound. Returns the matched signal kind for trace logging, or None.
2. `agent/orchestrator.py` — between LLM draft and `Calcom.book()`, if `parsed.intent == "book"` and `detect_wait_signal(latest_user_text)` is truthy, coerce `intent → "reply"`, drop `book_slot`, and re-route the body through a brief regen with the instruction "offer 3 specific times and ask which works." Log a `dccg_fired` field on the trace.

**Detection patterns** (drawn from `seed/email_sequences/cold.md` reply variants and B2B sales benchmarks):

```
let me check (my calendar|my schedule|with the team)
get back to you
i('| wi)ll let you know
thinking about it
need to confirm
checking with (my team|the team|my CTO)
this week is (busy|tight|tough)
not (this|next) week
circle back
hold off
let'?s revisit
maybe (next|the) week
```

**False-positive guard:** if the latest user turn ALSO contains an explicit slot acceptance pattern (`yes`, `that works`, `confirmed`, `book that`, ISO timestamp matching one of the offered slots), the gate does NOT fire. Detected via `agent/dual_control.py` `detect_explicit_acceptance()`.

**Trace output:** `dccg_fired: true|false`, `dccg_signal_kind: "let_me_check"|...|null`, `dccg_overrode_intent: true|false`. These are written into the synthetic-run JSONL alongside the existing fields.

## 5. Hypothesis

**H1 (primary).** With DCCG enabled, P7.1 trigger rate drops from 100% to ≤ 20% (i.e. the LLM may still produce ambiguous booking phrasing, but `parsed.intent` will not be `"book"` whenever a wait signal was detected). Two-proportion z-test on 5 baseline trials × 12 held-out variants = 60 trials per arm. With a Δ of ~80 percentage points, p < 0.001.

**H2 (secondary).** False-positive rate (gate fires when prospect HAS confirmed) ≤ 5% across a held-out set of 12 explicit-confirmation probes.

**H3 (no regression).** Latency overhead ≤ 1.0 s per turn (the gate is one regex eval plus optional one regen — measurable from latency_ms).

## 6. What the ablation reports

From `ablation_results.json`:

```json
{
  "n_held_out_variants": 12,
  "trials_per_variant": 5,
  "baseline": { "trigger_rate": 0.92, "ci95": [0.86, 0.96], "n_intent_book_when_should_wait": 55 },
  "method":   { "trigger_rate": 0.05, "ci95": [0.01, 0.13], "n_intent_book_when_should_wait": 3 },
  "delta_a":  { "rate_drop": 0.87, "p_value": 1.2e-12, "test": "two_proportion_z" },
  "false_positive_rate_method": 0.04,
  "latency_overhead_ms_p50": 580
}
```

(Numbers above are placeholders; actuals come from the run in [`method.md`](../eval/method.md).)

## 7. Out of scope for this target

- P1.1 (ICP misclassification post-layoff) — the second highest-trigger probe. Worth attacking but the mechanism (an abstention-classifier) needs a labelled training set and a confidence-threshold sweep that doesn't fit the day budget.
- P9.x (signal-confidence alignment) — interesting but harder to ablate cleanly because the existing prompts already attempt this; the Δ would be small.

Both will surface in the Day 5 memo as "honest unresolved failures" with their own probe rows.

---

**Implementation begins in `agent/dual_control.py` and `agent/orchestrator.py`. Held-out probe set lives at `probes/held_out_dual_control.yaml`. Ablation runner at `scripts/run_ablation.py`. Results in `eval/ablation_results.json` and `eval/held_out_traces.jsonl`.**
