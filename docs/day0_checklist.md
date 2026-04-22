# Day 0 Pre-flight Checklist (Tenacious edition)

Approximate time: 3–4 hours. Complete before Day 1.

## 1. Resend (PRIMARY email channel)

1. Sign up at <https://resend.com>. Free tier = 3,000 emails/month, no credit card.
2. Verify a domain OR use `onboarding@resend.dev` for dev.
3. Create an API key under **API Keys**. Scope: Full Access.
4. Fill `.env`: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `STAFF_SINK_EMAIL`.
5. Configure an inbound-reply webhook at `/email/inbound` (for grading spot checks).
6. Smoke test: `python -m scripts.day0_smoke_test openrouter` (LLM-dependent) — Resend smoke test is implicit via the synthetic-conversation run.

## 2. Africa's Talking sandbox (SECONDARY SMS channel)

Only used for warm-lead scheduling handoffs.

1. Sign up at <https://account.africastalking.com/register>
2. Sandbox App -> copy `username` and API key.
3. Create a virtual short code under **SMS → Short Codes**.
4. Set the inbound webhook URL to `https://<your-public-tunnel>/sms/inbound` (use `ngrok http 8080` locally).
5. Fill `.env`: `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE`, `STAFF_SINK_NUMBER`.
6. Smoke test: `python -m scripts.day0_smoke_test sms`.

## 3. HubSpot Developer Sandbox

1. Sign up at <https://developers.hubspot.com/>.
2. Create a Developer Account -> inside it, a Test Account (Developer Sandbox).
3. Private App with scopes:
   - `crm.objects.contacts.read`, `crm.objects.contacts.write`
   - `crm.objects.notes.read`, `crm.objects.notes.write`
4. Fill `.env`: `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID`.

## 4. Cal.com (self-hosted)

```bash
git clone https://github.com/calcom/cal.com.git
cd cal.com && cp .env.example .env
docker compose up -d
```

Open <http://localhost:3000>, create admin + one event type.
Get an API key at `/settings/developer/api-keys`. Note the event type ID.

Fill `.env`: `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`.

## 5. Langfuse cloud

1. Sign up at <https://cloud.langfuse.com>.
2. Create project, copy keys from Settings -> API keys.
3. Fill `.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

## 6. OpenRouter (dev-tier LLM)

1. Sign up at <https://openrouter.ai>, add $5 credit.
2. Fill `.env`: `OPENROUTER_API_KEY`.
3. Default `DEV_MODEL=qwen/qwen3-next-80b-a3b`.

## 7. τ²-Bench

```bash
cd <repo root>
git clone https://github.com/sierra-research/tau2-bench.git
pip install -e ./tau2-bench
python -m eval.tau2_runner --slice dev --trials 1 --num-tasks 3
```

## 8. Data-handling acknowledgement

Read [data_policy.md](data_policy.md). Acknowledge: `echo "<your name> 2026-04-22" > .ack`.

## Smoke test everything

```bash
python -m scripts.day0_smoke_test all
```

If any step blocks > 90 minutes, raise in the program channel.
