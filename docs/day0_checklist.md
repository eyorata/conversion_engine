# Day 0 Pre-flight Checklist

Approximate time: 3–4 hours. Complete before starting Act I.

## 1. Africa's Talking sandbox

1. Sign up at <https://account.africastalking.com/register>
2. Go to **Sandbox App** (not live). Copy the `username` (usually `sandbox`) and API key.
3. Create a virtual short code under **SMS → Short Codes**. Note the short code number.
4. Under **SMS → Callback URLs**, set the inbound URL to `https://<your-public-tunnel>/sms/inbound`.
   - For local dev: `ngrok http 8080` or `cloudflared tunnel --url http://localhost:8080`.
5. Fill `.env`: `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE`, `AT_WEBHOOK_URL`.
6. Smoke test: `python -m scripts.day0_smoke_test sms`.

## 2. HubSpot Developer Sandbox

1. Sign up at <https://developers.hubspot.com/>.
2. Create a **Developer Account** → inside it, create a **Test Account** (Developer Sandbox).
3. Create a **Private App** in the Test Account. Grant scopes:
   - `crm.objects.contacts.read`, `crm.objects.contacts.write`
   - `crm.objects.deals.read`, `crm.objects.deals.write`
   - `crm.schemas.contacts.read`, `crm.schemas.contacts.write`
   - `crm.objects.notes.read`, `crm.objects.notes.write`
4. Copy the access token. Fill `.env`: `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID`.
5. Smoke test: `python -m scripts.day0_smoke_test hubspot`.

## 3. Cal.com (self-hosted)

```bash
git clone https://github.com/calcom/cal.com.git
cd cal.com
cp .env.example .env
# edit .env: NEXTAUTH_SECRET, CALENDSO_ENCRYPTION_KEY (both 32-char hex)
docker compose up -d
# open http://localhost:3000, create admin user, create one event type
```

Get an API key at `/settings/developer/api-keys`. Note the event type ID (numeric, in the URL when editing the event type).

Fill `.env`: `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`.

## 4. Langfuse cloud

1. Sign up at <https://cloud.langfuse.com>.
2. Create a project. Copy the public + secret keys from **Settings → API keys**.
3. Fill `.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
4. Smoke test: `python -m scripts.day0_smoke_test langfuse`.

## 5. OpenRouter (dev-tier LLM)

1. Sign up at <https://openrouter.ai>.
2. Add $5 credit. Copy API key.
3. Fill `.env`: `OPENROUTER_API_KEY`.
4. Default `DEV_MODEL=qwen/qwen3-next-80b-a3b`. Alternative: `deepseek/deepseek-v3.2`.

## 6. τ²-Bench

```bash
cd <repo root>
git clone https://github.com/sierra-research/tau2-bench.git
cd tau2-bench
pip install -e .
python -m tau2 run --domain retail --model qwen/qwen3-next-80b-a3b --num-tasks 3
```

## 7. Data-handling acknowledgement

Read [data_policy.md](data_policy.md). Acknowledge by creating `.ack` with your name + date:

```bash
echo "<your name> 2026-04-21" > .ack
```

## Smoke-test everything

```bash
python -m scripts.day0_smoke_test all
```

Expected output: green checkmarks for SMS, HubSpot, Cal.com, Langfuse, OpenRouter. Red X for any missing credential. If any step blocks > 90 minutes, raise in the program channel.
