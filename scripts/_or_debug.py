"""Temporary OpenRouter debug probe. Delete after use."""
import os
import httpx

key = os.environ.get("OPENROUTER_API_KEY")
if not key:
    raise SystemExit("OPENROUTER_API_KEY not in env; run: $env:OPENROUTER_API_KEY = '<paste>'")

print(f"== key length: {len(key)} (prefix: {key[:8]}...)\n")

print("== 1. Test current DEV_MODEL ==")
r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json={
        "model": "qwen/qwen3-next-80b-a3b",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    },
    timeout=30,
)
print(f"status: {r.status_code}")
print(f"body:   {r.text[:400]}\n")

print("== 2. List available Qwen models ==")
r = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {key}"},
    timeout=30,
)
data = r.json()
qwens = sorted(m["id"] for m in data.get("data", []) if "qwen" in m["id"].lower())
for q in qwens[:30]:
    print(f"  {q}")
print(f"\n(total qwen models: {len(qwens)})")
