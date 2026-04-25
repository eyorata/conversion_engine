# Interim Report — Conversion Engine (Tenacious Edition)

**Trainee:** eyorata ·
**Generated:** 2026-04-23 ·
**Repo:** <https://github.com/eyorata/conversion_engine> ·
**Scope:** Acts I (τ²-Bench baseline) and II (production stack + enrichment pipeline)

---

## 1. System Architecture

### 1.1 Diagram

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "fontFamily": "Inter, -apple-system, Segoe UI, sans-serif",
    "fontSize": "13px",
    "primaryColor": "#eef2ff",
    "primaryTextColor": "#1e293b",
    "primaryBorderColor": "#6366f1",
    "lineColor": "#64748b",
    "clusterBkg": "#f8fafc",
    "clusterBorder": "#cbd5e1"
  },
  "flowchart": { "curve": "basis", "nodeSpacing": 45, "rankSpacing": 55, "htmlLabels": true }
}}%%
flowchart TD
    %% ---------- entry points ----------
    OB(["📤 Outbound seed<br/><span style='font-size:11px;color:#475569'>Crunchbase id</span>"]):::entry
    IN_E(["📧 Inbound email reply<br/><span style='font-size:11px;color:#475569'>POST /email/inbound</span>"]):::entry
    IN_S(["📱 Inbound SMS<br/><span style='font-size:11px;color:#475569'>POST /sms/inbound</span>"]):::entry

    OB --> FIRST
    IN_E --> EV{{"Resend<br/>event type?"}}:::decision
    IN_S --> FIRST

    %% ---------- email event discrimination ----------
    EV -- "bounced" --> UD["⛔ mark<br/>undeliverable"]:::terminal
    EV -- "complained" --> OO["🚫 mark<br/>opted_out"]:::terminal
    EV -- "delivered / opened" --> ACK["✓ ack,<br/>don't orchestrate"]:::terminal
    EV -- "reply forward" --> FIRST

    FIRST{{"First touch<br/>or returning?"}}:::decision
    FIRST -- "first" --> ENRICH
    FIRST -- "returning" --> AGENT

    %% ---------- enrichment pipeline ----------
    subgraph ENRICH ["🔍 <b>Enrichment pipeline</b><br/><span style='font-size:11px;font-weight:normal'>first touch only</span>"]
        direction TB
        CB[("Crunchbase ODM<br/><span style='font-size:11px'>1,000 records · firmographics + funding</span>")]:::source
        LF[("layoffs.fyi CSV<br/><span style='font-size:11px'>120-day window</span>")]:::source
        JP[("Job-post velocity<br/><span style='font-size:11px'>Playwright · 60-day delta</span>")]:::source
        LC[("Leadership change<br/><span style='font-size:11px'>90-day window · overrides + press</span>")]:::source
        AM["AI maturity scorer<br/><span style='font-size:11px'>0–3 with per-signal weight + confidence</span>"]:::enrich
        ICP["ICP classifier<br/><span style='font-size:11px'>4 segments</span>"]:::enrich
        CG["Competitor gap brief<br/><span style='font-size:11px'>top-quartile peers · ≥2 supporters/gap</span>"]:::enrich
        CB --> AM
        CB --> ICP
        LF --> ICP
        JP --> AM
        JP --> ICP
        LC --> ICP
        AM --> ICP
        ICP --> CG
    end

    ENRICH --> AGENT

    %% ---------- agent ----------
    subgraph AGENT ["🤖 <b>Agent orchestrator</b>"]
        direction TB
        LLM["LLM call<br/><span style='font-size:11px'>dev: OpenRouter Qwen3<br/>eval: Claude Sonnet 4.6</span>"]:::agent
        POL["Policy guardrail<br/><span style='font-size:11px'>over-claim + length regex</span>"]:::agent
        REG{{"Policy OK?"}}:::decision
        GATE["🔒 Hard SMS gate<br/><span style='font-size:11px'>cold ⇒ force email</span>"]:::agent
        LLM --> POL
        POL --> REG
        REG -- "No · regen once" --> LLM
        REG -- "Yes" --> GATE
    end

    %% ---------- persistence ----------
    AGENT --> HS["💾 HubSpot upsert<br/><span style='font-size:11px'>icp_segment · ai_maturity_score ·<br/>funding/layoff/job/leadership ·<br/>last_enriched_at · booking_id</span>"]:::persist
    AGENT --> CAL["📅 Cal.com booking<br/><span style='font-size:11px'>intent = book</span>"]:::persist
    CAL --> HS

    %% ---------- channel hierarchy ----------
    GATE -- "cold / first contact" ==> CH_E["📧 <b>Email — PRIMARY</b><br/><span style='font-size:11px'>Resend</span>"]:::channelPrimary
    GATE -- "warm lead<br/>prior email reply" ==> CH_S["📱 <b>SMS — SECONDARY</b><br/><span style='font-size:11px'>warm-lead scheduling<br/>Africa's Talking</span>"]:::channelSecondary
    CAL ==> CH_V["☎️ <b>Voice — FINAL</b><br/><span style='font-size:11px'>human Tenacious<br/>delivery lead</span>"]:::channelFinal

    %% ---------- cross-cutting ----------
    CH_E -. "kill switch" .-> KS[("⚠️ LIVE_OUTBOUND unset<br/>→ staff sink")]:::crosscut
    CH_S -. "kill switch" .-> KS
    AGENT -. "trace" .-> OBS[("📊 Langfuse<br/>traces + cost")]:::crosscut
    ENRICH -. "trace" .-> OBS

    %% ---------- styling ----------
    classDef entry           fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a;
    classDef decision        fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f;
    classDef terminal        fill:#fee2e2,stroke:#b91c1c,stroke-width:1.5px,color:#7f1d1d;
    classDef source          fill:#ccfbf1,stroke:#0d9488,stroke-width:1.5px,color:#134e4a;
    classDef enrich          fill:#a7f3d0,stroke:#047857,stroke-width:2px,color:#064e3b;
    classDef agent           fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95;
    classDef persist         fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81;
    classDef channelPrimary  fill:#86efac,stroke:#15803d,stroke-width:3px,color:#14532d;
    classDef channelSecondary fill:#fde68a,stroke:#b45309,stroke-width:3px,color:#78350f;
    classDef channelFinal    fill:#c4b5fd,stroke:#6d28d9,stroke-width:3px,color:#3b0764;
    classDef crosscut        fill:#f1f5f9,stroke:#475569,stroke-width:1.5px,color:#334155,stroke-dasharray:3 3;

    linkStyle default stroke:#64748b,stroke-width:1.5px;
```

Data flow is directional throughout. Solid arrows = runtime control/data flow;
dashed arrows = cross-cutting side effects (tracing, kill switch). The channel
hierarchy is colour-coded and structurally gated: `GATE` cannot route to
`CH_S` unless the conversation history shows a prior user turn whose `channel`
was `"email"`.

### 1.2 Design rationale

Decisions are explained by the *reason* they were made, not just the choice.

**Email is primary because the buyer persona lives in email.** Tenacious
sells to CTOs, VPs Engineering and founders at 15–2,000-person tech
companies. Cold SMS to this persona is perceived as intrusive and is a
known brand-damage mode for outbound consulting. Cold email is the
expected channel for a vendor introduction and is also the cheapest
channel to a/b test tone and segment-specific framing.

**SMS is secondary and gated on a prior email reply.** The only legitimate
reason to escalate to SMS is fast scheduling coordination with a prospect
who has *already* engaged via email. We enforce this at two layers:
the system prompt *asks* the LLM to pick email for cold contacts, and
the orchestrator has a **hard gate** at
[agent/orchestrator.py](../agent/orchestrator.py) that inspects
`conv.turns` for a `role="user", channel="email"` entry; if none exists,
the LLM's `channel="sms"` choice is coerced to `"email"` regardless of
what the LLM wanted. This cannot be bypassed by prompt injection.

**Voice is the final, human-delivered channel.** The agent never speaks.
Its last step on the happy path is a Cal.com booking; an actual Tenacious
delivery lead runs the discovery call. This is a product-authority
decision, not a technical one: a 30-minute discovery call is where
Tenacious makes its sale, and handing that to an LLM would both
misrepresent the firm and forfeit the conversation.

**Enrichment runs exactly once per lead, on first touch.** Every
enrichment call is a paid/rate-limited API call (Crunchbase sample load,
layoffs CSV parse, Playwright browser start, HubSpot search). We cache
the resulting `hiring_signal_brief` and `competitor_gap_brief` on the
conversation state and reuse them for subsequent turns in the same thread.
First-touch detection is `conv.stage == "new"`.

**Policy guardrail lives between the LLM and every external send.**
Grounded-honesty is a Tenacious brand constraint: the agent may not
claim a layoff, funding event, or leadership change that isn't in the
`hiring_signal_brief` with sufficient confidence. We encode this as
regex checks in [agent/policy.py](../agent/policy.py) — cheap,
deterministic, and unit-testable — rather than trusting the LLM to
follow the prompt. On violation, we regenerate once with the violations
appended to the prompt; if the second draft still fails, we **drop the
outbound** rather than sending anything.

**HubSpot was chosen over Salesforce** because HubSpot Developer Sandbox
is free without a credit card (a hard constraint for Ethiopia-based
trainees and the program's cost envelope), and HubSpot launched an MCP
server in Feb 2026 that we plan to adopt in Day 2 for "Mastered"-tier
rubric credit on CRM integration. Current build uses the REST SDK; MCP
migration is the only remaining CRM item.

**Cal.com was chosen over Google Calendar** because it works without
OAuth consent screens (which a synthetic-prospect challenge cannot
realistically build), supports self-host for trainees who want full
control of bookings, and its booking API is a single REST POST versus
Google Calendar's OAuth + free/busy + insert combination. The code
targets the hosted tier and self-host identically via `CALCOM_BASE_URL`.

**Langfuse was chosen over MLflow** because Langfuse has free-tier
cloud hosting (50k traces / month), native per-trace cost attribution
against LLM providers, and OpenTelemetry-native integration with
`httpx`. MLflow would require self-hosting and additional work for
per-call cost breakdown.

**File-backed conversation state, not Postgres.** Per-contact JSON under
`agent/conversation_state/` is sufficient for a week-long synthetic run
with < 1,000 prospects and keeps the build portable across Windows, Mac,
and Linux with zero setup. A production deploy would swap in Postgres
without changing the orchestrator — the `state.load` / `state.save`
interface is the abstraction boundary.

**Kill switch default-deny.** `LIVE_OUTBOUND` must equal `"1"` for any
outbound to reach a non-sink address; empty or unset ⇒ route to
`STAFF_SINK_EMAIL`/`STAFF_SINK_NUMBER`; both unset ⇒ drop with
`status="dropped_no_sink"`. This is enforced in both channel handlers
and verified by five kill-switch unit tests.

---

## 2. Production Stack Status

All five required components are documented below with tool, verified capability, concrete evidence, and configuration decisions.

| # | Component | Tool | Capability verified | Evidence | Key config |
|---|-----------|------|---------------------|----------|-----------|
| 1 | Email delivery (primary) | **Resend** | Send, kill-switch-routed send, bounce/complaint/delivered/reply discrimination | 7 unit tests in [tests/test_kill_switch.py](../tests/test_kill_switch.py) + [tests/test_webhook_events.py](../tests/test_webhook_events.py); 20-turn synthetic run with `send_result` dict per turn in [data/runs/synthetic.jsonl](../data/runs/synthetic.jsonl) | `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `STAFF_SINK_EMAIL`, `LIVE_OUTBOUND` |
| 2 | SMS (secondary, warm-lead scheduling) | **Africa's Talking sandbox** | Bidirectional send/receive, STOP/HELP/UNSUB classification, hard warm-lead gate | 10 unit tests across [tests/test_classify_inbound.py](../tests/test_classify_inbound.py), [tests/test_kill_switch.py](../tests/test_kill_switch.py), [tests/test_sms_gate.py](../tests/test_sms_gate.py) | `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE`, `STAFF_SINK_NUMBER` |
| 3 | CRM | **HubSpot Developer Sandbox** (REST; MCP Day 2) | `upsert_contact` writes ICP segment, AI maturity, funding/layoff/job/leadership signals, enrichment timestamp, booking id; `log_note` associates to the same contact | Code: [agent/hubspot_client.py](../agent/hubspot_client.py) `_enrichment_to_properties` + `upsert_contact`. Trace: every record in `data/runs/synthetic.jsonl` has `hubspot_contact_id` (null in dry-run snapshot) | `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` |
| 4 | Calendar | **Cal.com** (hosted or self-host via `CALCOM_BASE_URL`) | `available_slots()` returns next-5-days × 10/14 UTC slots; `book()` returns `Booking(id, start_at, end_at, booking_url)`; dry-run id when creds unset | Code: [agent/calcom_client.py](../agent/calcom_client.py). Trace: synthetic turns where `intent="book"` have a `booking` dict with `booking_id="dryrun-<ts>"` | `CALCOM_BASE_URL`, `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID` |
| 5 | Observability | **Langfuse cloud free tier** | Trace span per turn with `trace_id` recorded into HubSpot note + conversation state; no-op fallback when keys unset | Code: [agent/tracing.py](../agent/tracing.py). Every synthetic-run record has a `trace_id` field | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` |

### 2.1 Per-component detail

**Resend (email, primary).** Provider chosen over MailerSend for 3,000 emails/month free tier (MailerSend: 500) and Resend's idiomatic `Bearer` header pattern. We support **four** Resend webhook event types: `email.bounced` and `email.bounce` flip the contact to `undeliverable` and short-circuit orchestration; `email.complained` / `email.complaint` / `email.spam` flip to `opted_out`; `email.sent` / `delivered` / `opened` / `clicked` / `delivery_delayed` are acked with `{"kind":"event","handled":true}`; an absent/unknown event type is treated as an inbound reply forward and routed to `Orchestrator.handle_turn`. Malformed JSON or a bounce event missing the recipient returns HTTP 400 (no silent drops). *Config decision:* webhook path is `/email/inbound` (single endpoint for both replies and events) to minimize Resend dashboard setup.

**Africa's Talking (SMS, secondary).** Sandbox chosen because it requires no credit card and supports Ethiopian +251 numbers — both constraints from the program brief. Bidirectional: outbound via `SMSGateway.send()` (initializes the SDK lazily, dry-runs when `AT_API_KEY` is unset); inbound via `/sms/inbound` (accepts form OR JSON, normalizing `{from, text}`). STOP/HELP/UNSUB/QUIT/END/CANCEL tokens are classified case-insensitively and short-circuit orchestration before the LLM ever sees the text. *Config decision:* short code plus keyword prefix are set per-trainee in the program's shared rig; our sandbox short code is configurable via `AT_SHORTCODE`.

**HubSpot (CRM).** REST via the official `hubspot-api-client` SDK. `upsert_contact` searches by `email` (or `phone` fallback) first, updates in place if found, else creates. Properties written on every upsert:

- identity: `phone`, `email`, `company`, `crunchbase_id`
- classification: `icp_segment`, `icp_segment_num`, `icp_confidence`
- AI maturity: `ai_maturity_score` (0–3), `ai_maturity_confidence`, `ai_role_share`
- funding signal: `last_funding_type`, `last_funding_at`, `total_funding_usd`
- layoff signal: `layoffs_event_count_120d`, `layoffs_confidence`
- job-post signal: `job_roles_current`, `job_velocity_ratio`, `jobs_confidence`
- leadership signal: `leadership_change_role`, `leadership_change_days_ago`
- provenance: `last_enriched_at`, `tenacious_status=draft` (per seed license), `tenacious_booking_id`

`log_note` associates a note to the same `contact_id` with the full inbound/outbound transcript. After a successful `Cal.com` booking, the orchestrator re-calls `upsert_contact` with `booking_id` so the CRM reflects "same prospect, now booked" in one atomic record. *Config decision:* REST not MCP. MCP migration is a known Day-2 item to lift this rubric to Mastered.

**Cal.com (calendar).** Self-host via Docker or hosted tier at `api.cal.com` — both are supported by toggling `CALCOM_BASE_URL`. `available_slots()` returns a 6-slot shortlist (next 5 weekdays × 10:00 and 14:00 UTC). `book()` POSTs to `/v1/bookings` with the event type id and returns the booking id and confirmation URL. When credentials are unset, `book()` returns a deterministic `dryrun-<timestamp>` id so synthetic traces still have a concrete booking reference for the evidence graph. *Config decision:* `CALCOM_EVENT_TYPE_ID` is per-trainee, read from `.env`; the orchestrator does not hard-code event-type assumptions.

**Langfuse (observability).** Free-tier cloud project. The `Tracer` wrapper initializes lazily and falls back to a `_NullSpan` no-op when keys are unset — this lets CI and synthetic runs execute without requiring credentials while preserving the `trace_id` contract the rest of the code depends on. Every LLM call, every webhook handler invocation, and every enrichment run gets a span with `prompt_version` metadata (currently `tenacious-v0.1-2026-04-22` from [agent/prompts.py](../agent/prompts.py)) so Act V's evidence graph can filter by prompt version. *Config decision:* host defaults to `https://cloud.langfuse.com`; self-host can be pointed at via `LANGFUSE_HOST`.

---

## 3. Enrichment Pipeline

All five required signals are implemented. Each produces a structured sub-document in `hiring_signal_brief` with a per-signal `confidence` field (`"none"|"low"|"medium"|"high"`). The unified pipeline lives at [enrichment/pipeline.py](../enrichment/pipeline.py).

### 3.1 Signal-by-signal

#### Signal 1 — Crunchbase firmographics

**Source:** Crunchbase Open Data Map sample (Apache 2.0), 1,000 company records fetched once from [github.com/luminati-io/Crunchbase-dataset-samples](https://github.com/luminati-io/Crunchbase-dataset-samples) and cached at `data/crunchbase_sample.csv`.

**Output** (`hiring_signal_brief.prospect`, representative sample):
```json
{
  "crunchbase_id": "stripe-series-h-2026",
  "company": "Stripe",
  "domain": "stripe.com",
  "industry": "Financial Services, Payments",
  "employee_count": "5001-10000",
  "country": "US",
  "state": "CA",
  "founded_year": 2010,
  "total_funding_usd": 2200000000.0,
  "last_funding_type": "series_h",
  "last_funding_at": "2026-01-15",
  "description": "...",
  "key_people": "Patrick Collison, John Collison",
  "source": "crunchbase_odm_sample"
}
```

**Classification link.** Funding fields (`last_funding_type`, `last_funding_at`, `total_funding_usd`) are the primary signal for **Segment 1 (recently-funded Series A/B)**: the classifier requires `last_funding_type ∈ {series_a, series_b}` AND `(now - last_funding_at).days ≤ 180`. The `employee_count` field refines Segment 1 (ICP wants 15–200) and gates **Segment 2 (mid-market restructuring)** (ICP wants 200–2,000). Industry tokens drive peer lookup for the competitor gap brief.

#### Signal 2 — Job-post velocity (Playwright)

**Source:** public company careers pages (BuiltIn, Wellfound, LinkedIn) via `enrichment/jobs.py`. Two modes: `frozen` (reads [data/job_posts_snapshot.json](../data/job_posts_snapshot.json), 5 seed companies) and `live` (Playwright Chromium, no login, no captcha-bypass, custom User-Agent `TenaciousOutboundBot/0.1 +https://example.test/bot`, robots.txt-respectful).

**Output** (`hiring_signal_brief.jobs_signal`):
```json
{
  "company": "Anthropic",
  "total_roles_current": 5,
  "total_roles_60d_ago": 3,
  "velocity_ratio": 1.67,
  "ai_roles_current": 2,
  "ai_role_share": 0.4,
  "example_titles": ["Applied AI Engineer", "LLM Research Engineer", "Data Platform Engineer"],
  "mode": "frozen",
  "confidence": "medium",
  "retrieved_at": "2026-04-22T19:45:25Z",
  "source": "public_careers_pages"
}
```

**Classification link.** `velocity_ratio > 1.5` with `confidence ≥ medium` is a **Segment 1** amplifier (hiring outstripping recruiting = fresh-money pressure). `ai_role_share` is a **high-weight input to AI maturity** (see §3.2). Low-`confidence` or `< 5` total roles disables "aggressive hiring" framing in policy.py so the agent has to phrase openly rather than assert.

#### Signal 3 — layoffs.fyi (120-day window)

**Source:** layoffs.fyi CSV mirror via `enrichment/layoffs.py`. Falls back to committed [data/layoffs_seed.csv](../data/layoffs_seed.csv) when remote mirrors are unreachable. 10 seed events spanning 2025-12 through 2026-04.

**Output** (`hiring_signal_brief.layoffs_signal`):
```json
{
  "company": "Stripe",
  "window_days": 120,
  "event_count": 1,
  "events": [
    {"company": "Stripe", "date": "2026-01-18", "headcount": 300,
     "percentage": 0.07, "source": "https://example.test/stripe-jan26"}
  ],
  "confidence": "high",
  "retrieved_at": "2026-04-22T19:45:31Z",
  "source": "layoffs.fyi_mirror"
}
```

**Classification link.** `event_count > 0` is the *sine qua non* of **Segment 2 (mid-market restructuring)**. It also disqualifies pure Segment 1 framing ("fresh funding, scale your team"); a post-layoff Series A is Segment 2, not Segment 1 — a classic misclassification the agent must avoid. Policy check blocks "post-layoff" / "recent RIF" phrasing whenever `event_count == 0`.

#### Signal 4 — Leadership change (90-day window)

**Source:** override file at [data/leadership_changes.json](../data/leadership_changes.json) (1 seed entry) plus Crunchbase `key_people` parsing. Real deployment refreshes overrides from press releases and LinkedIn feeds.

**Output** (`hiring_signal_brief.leadership_signal`):
```json
{
  "company": "Example Prospect",
  "recent_change": true,
  "role": "VP Engineering",
  "person": "Jane Example",
  "announced": "2026-03-15",
  "source_url": "https://example.test/press/jane-example-vpe",
  "days_ago": 38,
  "confidence": "high",
  "retrieved_at": "2026-04-22T19:45:31Z",
  "source": "manual_overrides+press"
}
```

**Classification link.** `recent_change == true` AND role ∈ `{CTO, VP Engineering, Head of Engineering, CDO}` AND `days_ago ≤ 90` ⇒ **Segment 3 (leadership transition)** at `confidence="high"`. Policy check blocks "new CTO" / "recently appointed" phrasing whenever `recent_change == false`.

#### Signal 5 — AI maturity (0–3 with confidence)

**Source:** derived. Composes Crunchbase `description` + `key_people` + `industry`, `jobs_signal` (esp. `ai_role_share`), and optional news blob into a 0–3 integer score with per-input evidence. Implementation: [enrichment/ai_maturity.py](../enrichment/ai_maturity.py).

**Output** (`hiring_signal_brief.ai_maturity`, representative):
```json
{
  "score": 2,
  "scale": "0-3",
  "confidence": "medium",
  "ai_role_share": 0.4,
  "signals": [
    {"signal": "ai_role_share", "weight": "high",
     "evidence": "2 AI-adjacent roles / 5 total (40%)",
     "contribution": 1.5},
    {"signal": "exec_commentary", "weight": "medium",
     "evidence": "AI-strategic language present in description",
     "contribution": 0.6}
  ],
  "retrieved_at": "2026-04-22T19:45:31Z"
}
```

**Classification link.** AI maturity gates **Segment 4 (specialized capability gap)**: a Segment 4 pitch is only emitted when `score ≥ 2` with `confidence ∈ {medium, high}`. At `confidence="low"`, the classifier still includes Segment 4 but flags it as `confidence="low"` so the agent softens the pitch language. It also **shifts phrasing in Segments 1 and 2**: at `score ≥ 2, confidence ≥ medium`, the agent may lead with "scale your AI team faster than in-house hiring can support"; at `score ≤ 1`, it reframes as "stand up your first AI function with a dedicated squad" — a category question, not a ramp question.

### 3.2 AI-maturity scoring in detail

**High-weight inputs** (each can contribute ≥ 1.0):

1. **`ai_role_share`** — fraction of currently-open engineering roles whose
   title matches `AI_ROLE_RX` (ML / machine-learning / data-platform /
   applied-scientist / LLM / AI-engineer/product/platform / research-
   engineer / MLops). Contribution is `min(1.5, ai_role_share × 4.0)` so a
   25% share contributes +1.0 and a 40%+ share saturates at +1.5.
2. **Named AI/ML leadership** — regex match of `AI_LEADERSHIP_RX`
   (Chief AI/Data/Scientist Officer, VP AI/Data/ML, Head of AI/ML/Data)
   in the Crunchbase `key_people` or `description`. Contribution: fixed +1.0.

**Medium-weight inputs** (+0.6):

- **Executive commentary** — regex match of `AI_EXEC_COMMENT_RX`
  (AI-strategy, AI-first, generative-AI, LLM, foundation-model, agentic)
  in `description` or any supplied news blob.

**Low-weight inputs** (+0.3 each):

- **Modern ML stack** — regex match of `AI_STACK_RX` (dbt, Snowflake,
  Databricks, Weights & Biases, Ray, vLLM, Pinecone, MLflow, Airflow,
  Kubeflow) anywhere in the text blob.
- **Industry taxonomy** — Crunchbase `industry` contains "artificial
  intelligence", "machine learning", or "data science".

**Scoring logic.** `score = clamp(round(sum_of_contributions), 0, 3)`.

**Confidence rule.** Let `H` / `M` / `L` be the count of high- / medium-
/ low-weight signals present:

| `H` | `M+L` | Confidence |
|:---:|:-----:|:-----------|
| ≥ 2 | any | `high` |
| 1 | ≥ 1 | `medium` |
| 1 | 0 | `medium` |
| 0 | ≥ 2 | `low` |
| 0 | ≤ 1 | `low` |

`score == 0` forces `confidence = "low"` regardless of inputs, because a
zero-evidence prospect cannot yield a confident "zero maturity" — they
might simply be private about their AI work.

**Confidence-to-phrasing mapping** (enforced in
[agent/prompts.py](../agent/prompts.py) and
[agent/policy.py](../agent/policy.py)):

| Score × Confidence | Phrasing mode | Policy constraint |
|--------------------|---------------|-------------------|
| `3 × high` | **assert** — lead with specific practice the prospect is using ("your LLM Research Engineer pipeline suggests…") | no restriction |
| `2–3 × medium` | **observe + invite** — name what you saw, invite confirmation ("based on your open Applied AI Engineer roles, sounds like you're…") | Segment 4 pitch allowed |
| `2 × low` | **ask** — the signal exists but is weak; open with a question ("curious how you're staffing AI work this quarter") | Segment 4 pitch is **soft** only, no assertions |
| `0–1 × any` | **exploratory** — don't reference AI readiness; ask about engineering capacity in general | Segment 4 **disqualified**; Segment 1/2 default framing |

The agent's proposed message is run through `policy.check_outbound`
before send; the guardrail rejects drafts that assert AI-strategic
language (`AI_EXEC_COMMENT_RX`) when the signal confidence is low or
none. On rejection, the orchestrator regenerates once with the violation
appended to the prompt; if the second draft fails, the message is
**dropped**, not downgraded.

### 3.3 Competitor gap brief (derived from signals 1 and 5)

Not one of the five required signals, but promoted onto the HubSpot
record for completeness. For each prospect, `enrichment/competitor_gap.py`
picks 5–10 peers from the Crunchbase index by industry-token overlap and
size band, scores each peer on AI maturity using the same scorer,
computes the sector's top-quartile cutoff, and extracts at most 3
practices the top-quartile peers show but the prospect does not. Each
gap practice is only emitted when backed by `≥ 2` supporting peers
(single-peer signals are anecdote, not pattern).

---

## 4. Status Report and Forward Plan

### 4.1 What is working (clear and specific)

| Area | Claim | Evidence |
|------|-------|----------|
| Unit tests | 34/34 passing | [tests/](../tests/) — 5 kill-switch (email + SMS), 4 STOP/HELP, 13 policy, 6 ICP classifier, 4 webhook events, 2 SMS-gate |
| Synthetic end-to-end | 20/20 turns, 0 errors | [data/runs/synthetic.jsonl](../data/runs/synthetic.jsonl), summary at [data/runs/summary.json](../data/runs/summary.json); p50 8.5 s, p95 32.9 s (first-load dominated) |
| Enrichment pipeline | 5/5 signals emit structured briefs on a real Crunchbase record | [enrichment/pipeline.py](../enrichment/pipeline.py) returns `hiring_signal_brief` + `competitor_gap_brief` for domain `consolety.net` in the smoke run; 1,000 records loaded from CSV |
| Kill switch | Default-deny for both email and SMS | Verified by 5 kill-switch tests; with `LIVE_OUTBOUND` unset, every send either routes to sink or drops with `status="dropped_no_sink"` |
| Policy guardrail | Blocks 10 adversarial patterns | 13 policy tests cover hiring/funding/layoff/leadership over-claim, capacity commitment, pricing, filler phrases, gap disparagement, per-channel length |
| Hard SMS gate | LLM cannot escalate a cold contact to SMS | `test_cold_inbound_sms_does_not_escalate_to_sms` in [tests/test_sms_gate.py](../tests/test_sms_gate.py) |
| Email event discrimination | Resend `email.bounced` / `email.complained` / `email.delivered` routed distinctly | 4 webhook tests in [tests/test_webhook_events.py](../tests/test_webhook_events.py); malformed JSON returns HTTP 400 |
| τ²-Bench baseline | Program-provided reference committed as given | [eval/baseline.md](../eval/baseline.md): pass@1 = 0.7267, 95% CI [0.6504, 0.7917], avg cost $0.0199/run, p50 105.95 s, p95 551.65 s, 150 simulations, baseline commit `d11a9707` |

### 4.2 What is NOT working (honest, with failure details)

| Item | Specific failure | Consequence | Remediation |
|------|------------------|-------------|-------------|
| OpenRouter credentials unset in this snapshot | `LLMClient.complete` raises, `Orchestrator._call_llm` falls back to a canned email stub. Stub never emits real ICP-aware phrasing, so every synthetic turn's `policy.regen = None` (trivially clean) | Real LLM behaviour against the prompts is untested | Populate `OPENROUTER_API_KEY` Day 3 morning, rerun `scripts/synthetic_conversation.py`, rerun τ²-Bench held-out (trials=1) for Act IV |
| Resend credentials unset | `EmailHandler.send` returns `status="dry_run"` with `provider_message_id=None` | No real email landed in a real inbox; Resend dashboard has nothing to screenshot | Populate `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `STAFF_SINK_EMAIL`; run a single live send against the sink |
| HubSpot credentials unset | `HubSpotClient._get` warns and returns `None`; `upsert_contact` returns `ContactResult(contact_id=None, error="no_client")`. Property-mapping code is exercised by the dry-run call but not hit against a live portal | No HubSpot screenshot of populated contact record | Populate `HUBSPOT_ACCESS_TOKEN`; rerun synthetic; capture a screenshot of one contact with all ≈20 custom properties set |
| Cal.com credentials unset | `book()` returns `Booking(booking_id="dryrun-<ts>", error="dry_run")` | No real booking visible in a Cal.com dashboard; the booking id is deterministic per-run only | Either use Cal.com hosted tier (no Docker required) or finish self-host after the Docker Desktop start issue is fixed |
| Docker Desktop will not start on this machine | "Docker Desktop is unable to start" on `docker compose up -d`. Root cause is not yet identified; WSL 2 / virtualization / Hyper-V are the usual candidates | Self-host Cal.com blocked | Day 3 morning: either (a) fix Docker Desktop (run `wsl --update`, verify Intel VT-x in Task Manager), or (b) skip self-host entirely and use Cal.com hosted tier |
| Langfuse credentials unset | `Tracer` uses `_NullSpan`; `trace_id` is a local `uuid4` per turn but never shipped to the Langfuse dashboard | No per-trace cost attribution available yet | Populate `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`; rerun synthetic; verify spans appear in the Langfuse UI |
| HubSpot MCP not migrated | Current writes use REST via `hubspot-api-client`; the rubric's "Mastered" CRM tier expects the MCP server | CRM rubric likely tops out at Competent (3/5), not Mastered (5/5) | Day 5 (time-permitting): install the HubSpot MCP server, route writes through MCP tool calls. Flag as known gap if time doesn't allow |
| Live Playwright job-post crawl tested on ≤ 5 companies | Frozen snapshot is the primary path; live mode is code-complete but only smoke-tested against Anthropic/Stripe/OpenAI/Databricks/Example-Prospect | Act IV mechanism evaluation may need ≥ 20 live companies for robust probes | Day 3: expand `data/job_posts_snapshot.json` to 30+ companies by running the Playwright scraper against Crunchbase-matched careers URLs, capped at 200/week per the data-handling policy |
| Leadership-change feed is override-driven | `data/leadership_changes.json` has 1 seed entry; a real deployment needs a press-release / LinkedIn feed | Act III probes on Segment 3 misclassification will have limited coverage | Day 3: manually seed 10–15 real 2026-Q1 leadership changes into the override file so Segment 3 probes have material |
| Seed materials (`tenacious_sales_data/`) earlier pushed to public repo | Force-pushed clean history in commit `759807b`; directory is now `.gitignore`-d and local-only | Potentially recoverable from GitHub's orphan-commit cache for ≤ 90 days | Self-report to tutors in `#trp1-week10-conversion-engine` Slack per Rule 9 of the data-handling policy |

### 4.3 Forward plan (Acts III → V)

**Day 3 — Friday 2026-04-24 — Act III: Probe library + failure taxonomy**

*Morning (3 h).* Populate `.env` credentials (Resend, HubSpot, Cal.com hosted, Langfuse, OpenRouter). Rerun `python -m scripts.day0_smoke_test all`; capture one screenshot per component (Resend dashboard showing the test email, HubSpot contact page, Cal.com booking, Langfuse trace tree). Commit screenshots to `memo/evidence/`.

*Midday (4 h).* Build [probes/probe_library.md](../probes/probe_library.md) with ≥ 30 structured probe entries across the 9 categories the brief requires: ICP misclassification (post-layoff + recently-funded dual signal), hiring-signal over-claim at low confidence, bench over-commitment under pressure, tone drift across 5 consecutive turns, multi-thread leakage (two contacts at the same company), dual-control coordination (wait vs. proceed), scheduling across EU/US/East Africa time zones, gap over-claim and disparagement, cost pathology (runaway token usage). Run each probe against the LLM + policy stack; record `trigger_rate` across 10 trials per probe.

*Evening (2 h).* Group probes into `failure_taxonomy.md`. Compute business-cost estimates in Tenacious terms (lost deal probability × ACV band × stalled-thread rate). Pick the highest-ROI failure as `target_failure_mode.md` for Act IV.

**Day 4 — Friday evening through Saturday morning — Act IV: Mechanism design**

Candidate mechanism (subject to what Day 3 reveals as highest-ROI): **signal-confidence-aware phrasing selector**. The current prompt instructs the LLM to vary phrasing by confidence; the mechanism promotes this from prompt advice to a code-enforced constraint. Specifically: after the LLM draft, consult the `hiring_signal_brief` confidence profile; if the prospect's minimum-confidence load-bearing signal is `low` or `none`, route the draft through a second LLM pass whose system message is "rewrite this as a question, remove any assertion about X." Measured vs. baseline on the sealed held-out 20-task slice at **trials = 1** per the 2026-04-23 program update, using eval-tier Claude Sonnet 4.6.

Deliverables: `method.md` (design rationale + hyperparameters + 3 ablation variants), `ablation_results.json` (pass@1, 95% CI, cost-per-task, p95 latency for our method, our Day-1 baseline, and a GEPA/DSPy automated-optimization baseline at the same compute budget), `held_out_traces.jsonl`, and a statistical test showing Δ_A > 0 at p < 0.05.

**Day 5 — Saturday 2026-04-25 — Act V: Memo, evidence graph, demo video**

Morning: `memo.pdf` exactly 2 pages — Page 1 (decision: pass@1, 95% CI, cost per qualified lead, stalled-thread delta, competitive-gap outbound reply-rate delta, three adoption scenarios, pilot scope recommendation); Page 2 (skeptic's appendix: 4 Tenacious-specific failure modes τ²-Bench cannot capture, public-signal lossiness, gap-analysis risks, brand-reputation unit economics, one honest unresolved failure, kill-switch clause).

Afternoon: `evidence_graph.json` mapping every numeric claim in the memo to a `trace_id` or invoice line item; automated validator walks every claim and recomputes. Demo video ≤ 8 minutes: synthetic prospect end-to-end (email outreach → reply → qualification brief → Cal.com booking → HubSpot record → probe library walkthrough → τ²-Bench score reproduction → one concrete fix that landed from a probe).

Evening: final `git push`, Google-Drive PDF link, video link.

---

## 5. Appendix: How the interim PDF was generated

`python -m scripts.build_interim_pdf` ([scripts/build_interim_pdf.py](../scripts/build_interim_pdf.py)) reads [eval/score_log.json](../eval/score_log.json) and [data/runs/summary.json](../data/runs/summary.json), normalizes the provided-baseline schema, and writes [memo/interim_report.pdf](interim_report.pdf). This Markdown file is the long-form companion: identical substance, GitHub-rendered Mermaid, richer per-section detail.

---

*Generated 2026-04-23. Repo at commit `7243ca8` (main).*
