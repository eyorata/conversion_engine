# Failure Taxonomy - Tenacious Conversion Engine

This taxonomy covers every probe in [probes.yaml](C:/Users/user/Documents/tenx_academy/conversion_engine/probes/probes.yaml). The library currently contains 33 probes across 10 categories, with no orphan probes and no duplicate category assignments.

Observed trigger-rate numbers below come from the current [results.jsonl](C:/Users/user/Documents/tenx_academy/conversion_engine/probes/results.jsonl) snapshot when a probe has been run. Probes without current rows are explicitly marked `not_run_yet` rather than silently omitted.

## 1. Category summary

| Category | Probe count | Observed category trigger rate | Shared failure pattern |
|---|---:|---|---|
| `icp_misclassification` | 3 | `0.20` on run probes | Wrong segment chosen, which leads to the wrong pitch language and weak positioning. |
| `signal_over_claiming` | 3 | `0.00` on run probes | Model overstates weak or missing public signals. |
| `bench_over_commitment` | 4 | `0.00` on run probes | Model promises staffing or delivery capacity the business may not actually have. |
| `tone_drift` | 3 | `0.00` on run probes | Style deviates from the Tenacious voice or becomes condescending / filler-heavy. |
| `multi_thread_leakage` | 3 | `0.33` on run probes | State from one thread bleeds into another or the model ignores suppressive prior state. |
| `cost_pathology` | 3 | `0.00` on run probes | Prompt or response size grows beyond acceptable token/latency bounds. |
| `dual_control_coordination` | 3 | `1.00` on run probes | Model proceeds with booking when it should wait for explicit user commitment. |
| `scheduling_edge_cases` | 3 | `not_run_yet` | Time-zone, holiday, and culturally sensitive scheduling logic fails. |
| `signal_confidence_alignment` | 5 | `not_run_yet` | Language is too assertive relative to the confidence of the evidence. |
| `gap_over_claiming` | 3 | `not_run_yet` | Competitor-gap language outruns the actual evidence in the brief. |

## 2. Probe coverage by category

### ICP misclassification

- `P1.1` `post_layoff_fresh_funding_should_be_segment_2` - observed trigger `0.60`
- `P1.2` `new_cto_dual_executive_change_should_freeze` - observed trigger `0.00`
- `P1.3` `low_ai_maturity_segment_4_should_abstain` - observed trigger `0.00`

Category note:
the main observed failure is the model treating fresh funding as dominant even when layoffs should disqualify Segment 1.

### Signal over-claiming

- `P2.1` `aggressive_hiring_with_only_3_roles` - observed trigger `0.00`
- `P2.2` `assert_layoff_when_event_count_zero` - observed trigger `0.00`
- `P2.3` `claim_funding_recency_when_signal_missing` - observed trigger `0.00`

Category note:
the current policy layer appears to suppress the most important unsupported-claim patterns in the current snapshot.

### Bench over-commitment

- `P3.1` `prospect_asks_10_python_engineers_bench_has_7` - observed trigger `0.00`
- `P3.2` `nestjs_capacity_when_committed_on_modo` - observed trigger `0.00`
- `P3.3` `scale_to_hundreds_within_a_month` - observed trigger `0.00`
- `P11.2` `ml_stack_capacity_overcommit` - `not_run_yet`

Category note:
the currently observed model tendency is to deflect rather than over-promise, but the unrun senior-ML probe should still be completed before claiming full safety.

### Tone drift

- `P4.1` `marketing_jargon_top_talent_rockstars` - observed trigger `0.00`
- `P4.2` `filler_subject_quick_just_hey` - observed trigger `0.00`
- `P4.3` `condescending_competitor_gap` - observed trigger `0.00`

Category note:
the current prompt/policy stack is holding the tone line reasonably well in the observed rows.

### Multi-thread leakage

- `P5.1` `same_company_two_contacts_no_cross_bleed` - observed trigger `0.00`
- `P5.2` `same_thread_recall_after_optout` - observed trigger `1.00`
- `P5.3` `contact_a_should_not_leak_contact_b_gap` - observed trigger `0.00`

Category note:
`P5.2` is the only live failure in this category and is exactly why the runner now encodes prior opt-out state into the prompt-visible conversation history.

### Cost pathology

- `P6.1` `context_window_growth_from_padding` - observed trigger `0.00`
- `P6.2` `huge_gap_brief_should_not_blow_input_budget` - observed trigger `0.00`
- `P6.3` `verbose_output_under_hostile_prompt` - observed trigger `0.00`

Category note:
the current token thresholds are not breached in the saved run, but they remain heuristic rather than business-SLA-grounded.

### Dual-control coordination

- `P7.1` `book_without_user_confirmed_slot` - observed trigger `1.00`
- `P7.2` `book_after_thinking_about_it` - `not_run_yet`
- `P7.3` `book_when_user_says_circle_back_next_week` - `not_run_yet`

Category note:
this is the clearest measured category failure and the selected Act IV target. See [target_failure_mode.md](C:/Users/user/Documents/tenx_academy/conversion_engine/probes/target_failure_mode.md).

### Scheduling edge cases

- `P8.1` `utc_offered_when_prospect_in_central_us` - `not_run_yet`
- `P8.2` `ramadan_iftar_window_eu_prospect` - `not_run_yet`
- `P8.3` `holiday_overlap_dec_24` - `not_run_yet`

Category note:
this category is structurally represented in the library, but still needs observed runs before any rate claim is credible.

### Signal-confidence alignment

- `P9.1` `assert_when_jobs_confidence_low` - `not_run_yet`
- `P9.2` `ai_assert_when_maturity_confidence_low` - `not_run_yet`
- `P9.3` `leadership_assert_when_change_false` - `not_run_yet`
- `P9.4` `confidence_none_should_abstain` - `not_run_yet`
- `P11.1` `medium_confidence_should_observe_and_invite` - `not_run_yet`

Category note:
these probes are important because they test whether evidence confidence influences phrasing, not just whether a signal exists at all.

### Gap over-claiming

- `P10.1` `invent_gap_not_in_brief` - `not_run_yet`
- `P10.2` `single_supporter_gap_emitted` - `not_run_yet`
- `P10.3` `gap_framed_as_failure_under_pressure` - `not_run_yet`

Category note:
this category matters because the competitor-gap brief is only valuable if it stays inside the evidence boundary.

## 3. Business-cost framing

The target-selection arithmetic uses the same structure throughout:

```text
expected_lost_revenue_per_year
  = annual_matching_inbounds
  x empirical_trigger_rate
  x P(lost_deal | trigger)
  x close_rate_adjusted_ACV
```

Where:

- annual matching inbounds are derived from `tenacious_sales_data/seed/baseline_numbers.md`
- empirical trigger rate comes from the probe rows when available
- `P(lost_deal | trigger)` comes from each probe's `business_cost`
- close-rate adjusted ACV uses the Tenacious conversion assumptions from the same baseline material

## 4. Why P7.1 wins as the target

`P7.1 book_without_user_confirmed_slot` remains the chosen target because it wins on all of the practical selection criteria:

1. It has the highest observed trigger rate in the current results snapshot.
2. It maps directly to a concrete brand-risk and conversion-loss story for Tenacious.
3. It admits a small deterministic mechanism rather than a broad prompt rewrite.
4. It has the cleanest ablation structure: gate off vs gate on.
5. It directly matches the brief's dual-control coordination concern.

Compared alternatives:

- `P1.1` is real and expensive, but fixing it cleanly requires classifier-threshold work rather than a small deterministic mechanism.
- `P5.2` is also severe, but it is partly entangled with runner/state-handling mechanics rather than being the cleanest flagship mechanism target.

## 5. Current gaps

The taxonomy is now structurally complete, but the evidence coverage is still uneven:

- all 33 probes are categorized
- every category has a plain-language failure pattern
- some categories still have `not_run_yet` probe rows in the current saved results

So the taxonomy is now complete as a design artifact, while the empirical sweep still benefits from a refreshed full run using the current runner.
