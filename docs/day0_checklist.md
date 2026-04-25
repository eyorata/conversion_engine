# Day 0 Pre-flight Checklist (Tenacious Edition)

Approximate time: 3-4 hours. Complete before Day 1.

## 1. Resend (primary email channel)

1. Sign up at <https://resend.com>.
2. Verify a domain, or use `onboarding@resend.dev` for dev-only send tests.
3. Create an API key under **API Keys** with send permissions.
4. Fill `.env`: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `STAFF_SINK_EMAIL`.
5. Configure the inbound reply / event webhook to:
   `https://<your-public-url>/email/inbound`
6. Smoke test with the FastAPI server running and confirm webhook events hit `/email/inbound`.

## 2. Africa's Talking sandbox (secondary SMS channel)

Only used for warm-lead scheduling handoff after a prior email reply.

1. Sign up at <https://account.africastalking.com/register>.
2. In the sandbox app, copy `username` and API key.
3. Create a virtual short code under **SMS -> Short Codes**.
4. Set the inbound webhook URL to:
   `https://<your-public-url>/sms/inbound`
5. Fill `.env`: `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE`, `AT_WEBHOOK_URL`, `STAFF_SINK_NUMBER`.
6. Smoke test:
   `python -m scripts.day0_smoke_test sms`

## 3. HubSpot Developer Sandbox

1. Sign up at <https://developers.hubspot.com/>.
2. Create a Developer Account, then create a Test Account inside it.
3. Create a private app with scopes:
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.notes.read`
   - `crm.objects.notes.write`
   - `crm.schemas.contacts.read`
   - `crm.schemas.contacts.write`
4. Fill `.env`: `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID`.
5. Provision the custom properties this repo writes:
   `python -m scripts.provision_hubspot_properties`

Note:
the current repo uses the official HubSpot REST SDK, not an MCP server.

## 4. Cal.com (self-hosted)

```bash
git clone https://github.com/calcom/cal.com.git
cd cal.com
cp .env.example .env
docker compose up -d
```

Then:

1. Open <http://localhost:3000>.
2. Create an admin user and one event type.
3. Create an API key at `/settings/developer/api-keys`.
4. Note the event type id.
5. Fill `.env`: `CALCOM_BASE_URL`, `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`.
6. Optionally set `CALCOM_WEBHOOK_SECRET` and point Cal.com booking webhooks to:
   `https://<your-public-url>/calcom/webhook`

## 5. Langfuse cloud

1. Sign up at <https://cloud.langfuse.com>.
2. Create a project and copy keys from **Settings -> API keys**.
3. Fill `.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

## 6. OpenRouter (dev-tier LLM)

1. Sign up at <https://openrouter.ai>.
2. Add a small credit balance.
3. Fill `.env`: `OPENROUTER_API_KEY`.
4. Default model:
   `DEV_MODEL=qwen/qwen3-next-80b-a3b-instruct`

## 7. tau2-bench

```bash
cd <repo root>
git clone https://github.com/sierra-research/tau2-bench.git
pip install -e ./tau2-bench
python -m eval.tau2_runner --slice dev --trials 1 --num-tasks 3
```

## 8. Data-handling acknowledgement

Read [data_policy.md](C:/Users/user/Documents/tenx_academy/conversion_engine/docs/data_policy.md).

## Smoke test everything

```bash
python -m scripts.day0_smoke_test all
```

If anything blocks for more than 90 minutes, raise it in the program channel and note the exact provider/setup step that failed.
