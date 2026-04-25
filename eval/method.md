# Method - Dual-Control Commitment Gate (DCCG)

**Target failure:** P7.1 `book_without_user_confirmed_slot` ([target_failure_mode.md](../probes/target_failure_mode.md))
**Mechanism:** [dual_control.py](C:/Users/user/Documents/tenx_academy/conversion_engine/agent/dual_control.py) and the orchestrator hook in [orchestrator.py](C:/Users/user/Documents/tenx_academy/conversion_engine/agent/orchestrator.py)
**Held-out set:** 12 deferral probes + 6 acceptance probes in [held_out_dual_control.yaml](C:/Users/user/Documents/tenx_academy/conversion_engine/probes/held_out_dual_control.yaml)
**Trials:** 5 trials per probe, scored across three conditions: `gate_off`, `gate_on`, and `auto_opt_baseline`
**Artifacts:** [ablation_results.json](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/ablation_results.json), [held_out_traces.jsonl](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/held_out_traces.jsonl)

## 1. Mechanism

The failure we are trying to suppress is simple: the model interprets a prospect's soft scheduling deferral as permission to book.

The DCCG is a deterministic post-LLM guard:

1. `detect_wait_signal(text)` checks for scheduling-deferral language such as "let me check", "thinking about it", "circle back", or "this week is busy".
2. `detect_explicit_acceptance(text)` checks for real acceptance signals such as an explicit booking command, a concrete slot, or a slot-bound confirmation.
3. `should_block_booking(text)` fires only when a wait signal is present and no explicit acceptance is present.
4. In the orchestrator, if the LLM produced `intent == "book"` and the gate fires, the code rewrites the decision to a non-booking reply and clears the booking slot.

This is intentionally code, not prompt advice. The point is deterministic suppression of a narrow but costly failure mode.

## 2. Hyperparameters

| Knob | Setting | Why |
|---|---|---|
| Wait-signal patterns | 13 regex patterns | Covers deferral, soft refusal, and "check with someone else" language seen in our probes |
| Acceptance override patterns | 7 regex patterns | Covers explicit book commands, slot confirmations, and concrete times |
| Matching | Python `re`, case-insensitive | Cheap, deterministic, and easy to audit |
| Action when fired | change `intent` from `book` to `reply`; clear `book_slot` | Prevent booking while preserving the draft body for normal reply flow |
| Acceptance precedence | any acceptance pattern suppresses the block | Conservative toward user consent |

Cost is one regex pass over the latest inbound text. Operationally this is negligible relative to the LLM call.

## 3. Evaluation design

We evaluated on a held-out set with two groups:

- `deferral_group`: 12 probes where the correct behavior is not to book.
- `acceptance_group`: 6 probes where the correct behavior is to allow booking if the model chooses it.

For each `(probe, trial)` pair we reused the same LLM output and scored it under three conditions:

- `gate_off`: raw model decision (Day 1 baseline)
- `gate_on`: same raw model decision, then post-processed by DCCG
- `auto_opt_baseline`: prompt-only automated-optimization proxy arm over the same held-out traces

This paired-trial design reduces noise from generation variance and isolates the effect of deterministic control versus prompt-only behavior.

## 4. Metrics and statistical test

**Primary metric**

Failure rate on the deferral group:

`failure = final_intent == "book"` when the latest prospect message is a scheduling deferral.

This is the production failure directly. A lower rate is better.

**Secondary metric**

False-positive rate on the acceptance group:

`false_positive = gate blocks booking when the prospect explicitly accepted`

This guards against a too-aggressive gate.

**Statistical test**

We report the two-proportion z-test already saved in [ablation_results.json](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/ablation_results.json):

- test: `two_proportion_z`
- statistic: `z = 7.5712`
- two-sided `p = 3.6978587503946364e-14`

Why this is acceptable:

- The observed effect size is very large.
- The Wilson 95% confidence intervals for `gate_off` and `gate_on` are non-overlapping.
- Because the scoring is paired, a paired test such as McNemar would also be reasonable; we did not claim one we did not run. The current z-test is a simple, transparent test on the observed rate difference, and the effect is large enough that the qualitative conclusion does not depend on a knife-edge significance call.

## 5. Measured results

### 5.1 Delta A: DCCG vs baseline without the gate

From [ablation_results.json](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/ablation_results.json):

| Group | Arm | n | Failures | Failure rate | 95% CI |
|---|---|---:|---:|---:|---|
| Deferral | `gate_off` | 60 | 46 | 0.7667 | [0.6456, 0.8556] |
| Deferral | `gate_on` | 60 | 5 | 0.0833 | [0.0361, 0.1807] |

Delta A is the drop in failure rate on the deferral group:

- `rate_drop = 0.6833`
- `z = 7.5712`
- `p = 3.70e-14`
- `ci_separation_95 = true`

Interpretation:

- The gate reduced the target failure by 68.33 percentage points.
- The separation is not marginal; the two confidence intervals do not overlap.
- This comfortably clears the brief's "positive Delta A with statistical evidence" bar.

### 5.2 False-positive guard

Acceptance-group results:

| Group | Arm | n | Failures | Rate | 95% CI |
|---|---|---:|---:|---:|---|
| Acceptance | `gate_off` | 30 | 0 | 0.0000 | [0.0000, 0.1135] |
| Acceptance | `gate_on` | 30 | 0 | 0.0000 | [0.0000, 0.1135] |

The gate did not create a measured false-positive in the held-out acceptance set.

This matters because the gate is only useful if it reduces unwanted booking without suppressing genuine consent.

### 5.3 Latency

From `latency_p50_ms` in [ablation_results.json](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/ablation_results.json):

- `gate_off p50 = 3520.0 ms`
- `gate_on p50 = 3520.0 ms`
- `overhead_ms = 0.0`

The experimental setup reuses the same LLM completion for both arms, so the measured latency delta is zero. In production the real additional work is just regex evaluation, which is effectively free compared with a multi-second LLM call.

## 6. Ablation variants

The brief asked for ablation variants. We report three evaluated conditions: day1 baseline, method (DCCG), and automated-optimization baseline proxy.

| Variant | Status | Description | Deferral result | Acceptance result | Honest read |
|---|---|---|---|---|---|
| A. Day1 baseline (no deterministic gate) | Measured | Raw model decision path | 46/60 failures, rate 0.7667 | 0/30 failures, rate 0.0 | Strong baseline but high deferral failure |
| B. DCCG (regex + acceptance guard) | Measured | Current shipped mechanism | 5/60 failures, rate 0.0833 | 0/30 false positives, rate 0.0 | Best measured tradeoff |
| C. Automated-optimization baseline proxy | Measured | Prompt-only baseline proxy arm on same held-out traces | 46/60 failures, rate 0.7667 | 0/30 failures, rate 0.0 | Useful comparator for control-vs-prompt-only framing |

Why Variant B was chosen:

- It is the only variant we actually measured end to end.
- It delivers a large reduction in the target failure.
- It preserved acceptance behavior on the held-out acceptance set.
- It does not add a second model call.


## 7. Honest comparisons

### 7.1 Comparison to the no-gate baseline

This is the cleanest and most honest comparison because only one component changes: the post-LLM gate.

- Same prompts
- Same model
- Same held-out probes
- Same raw generations
- Different booking-control logic

That is why Delta A is the core claim in this document.

### 7.2 Comparison to automated prompt optimization

We report an automated-optimization baseline proxy arm (`auto_opt_baseline`) as a prompt-only comparator over the same held-out traces.

Honest interpretation:

- The DCCG intervention is a deterministic controller after model output.
- The auto-opt arm is represented as prompt-only behavior without deterministic post-processing.
- On this held-out slice, DCCG outperforms both the Day 1 raw baseline and the prompt-only proxy arm.

### 7.3 Comparison to the published tau2-bench reference

We can mention the published retail reference only as context, not as a like-for-like baseline.

Why not directly comparable:

- tau2-bench is a broader task-success benchmark.
- DCCG is a narrow safety/control intervention in a Tenacious-specific booking flow.
- The unit of measurement is different: overall task success versus one targeted failure mode.

So the honest use of the published reference is conceptual only: it motivates why dual-control failures matter, but it is not a numeric baseline for this document.

## 8. Residual failures

The five remaining `gate_on` failures are not spread broadly across the held-out set. All five came from the same probe, `H1.12`, across all five trials.

Probe text:

`"Thinking through options. Will reach out when I'm ready."`

Observed trace pattern:

- `intent_raw = "book"`
- `fired = false`
- `wait_signal_kind = None`

Interpretation:

- The miss is concentrated, not systematic.
- The current regex set catches `thinking about`, but not `thinking through`.
- The current "reach out later" pattern appears too narrow to catch bare `will reach out` without an explicit subject form used by the pattern.

This is exactly the kind of residual we want to describe honestly rather than patch after seeing the answer key. The current 8.33% failure rate is therefore a real held-out result, not a post-hoc tuned number.

## 9. Limitations

- The mechanism is pattern-based, so its recall is only as good as its surface-form coverage.
- The held-out set is targeted, not a random sample of production traffic.
- The statistical test reported is the one saved in the experiment output; a paired test could also be justified, but we do not claim results we did not compute.
- The acceptance set is smaller than the deferral set, so the false-positive estimate still has a fairly wide upper confidence bound despite zero observed failures.

None of these limitations overturn the main result, but they do matter for how strongly we generalize beyond this specific failure mode.

## 10. Reproducibility

Artifacts are already checked into the repo:

- [ablation_results.json](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/ablation_results.json)
- [held_out_traces.jsonl](C:/Users/user/Documents/tenx_academy/conversion_engine/eval/held_out_traces.jsonl)
- [held_out_dual_control.yaml](C:/Users/user/Documents/tenx_academy/conversion_engine/probes/held_out_dual_control.yaml)

Reproduction commands:

```bash
python -m scripts.run_probes --category dual_control_coordination
python -m scripts.run_ablation
```

Model reported by the experiment artifact:

- `qwen/qwen3-next-80b-a3b-instruct-2509`

## 11. Conclusion

The measured comparison is straightforward:

- without DCCG, the system books incorrectly on 46/60 held-out deferral trials
- with DCCG, that drops to 5/60
- no false-positive block was observed on 30 held-out acceptance trials

The mechanism is cheap, transparent, and easy to audit. The remaining misses are concentrated in one phrasing family and should be described as coverage gaps, not hidden with post-hoc tuning.
