# Data Handling Policy

This project handles a hypothetical client (Acme ComplianceOS). The Crunchbase and CFPB data are real and public; the leads the agent talks to during the challenge week are synthetic.

## Rules

1. **No real customer data.** All prospects during the challenge week are synthetic profiles derived from public Crunchbase records. Staff-managed sink numbers receive all outbound.
2. **Kill switch.** Outbound SMS is routed to `STAFF_SINK_NUMBER` unless `LIVE_OUTBOUND=1`. Default is unset. See [agent/sms_gateway.py](../agent/sms_gateway.py).
3. **Compliance claims.** The agent refuses any compliance claim not grounded in the CFPB API response for the specific company. Over-claiming exposes Acme to misrepresentation liability.
4. **STOP / HELP / UNSUB.** TCPA-compliant: STOP sets `opted_out=true` in conversation state and blocks all future outbound for the number. HELP returns boilerplate help text.
5. **CFPB data.** Public and freely redistributable. Cache hits under `data/cfpb_cache/` — gitignored — with a 7-day TTL.
6. **Crunchbase ODM sample.** Apache 2.0, redistributable. Not checked in (large); fetched on first run via `scripts.fetch_crunchbase.py`.
7. **Seed materials (sales deck, case studies, pricing sheet).** Not applicable in this Acme edition — seed materials are public-sourced.

## Kill switch verification

```python
# agent/sms_gateway.py routes every outbound through this check:
if not settings.LIVE_OUTBOUND:
    target_number = settings.STAFF_SINK_NUMBER
```

A unit test (`tests/test_kill_switch.py`) asserts that with `LIVE_OUTBOUND` unset, no message is delivered to a non-sink number regardless of what the agent requests.
