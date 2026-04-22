# Data Handling Policy (Tenacious edition)

This project interacts with a real client: Tenacious Consulting and Outsourcing.
Seed materials (sales deck, case studies, pricing bands, bench summary, style
guide) are shared under a limited license for the challenge week.

## Rules

1. **No real Tenacious customer data leaves Tenacious.** You do not receive CRM
   exports, real prospect contacts, real email threads, or live deal names.
2. **Every prospect your system interacts with is synthetic.** Synthetic
   prospects are generated from public Crunchbase firmographics combined with
   fictitious contact details. The program-operated email sink and SMS rig
   route all outbound to staff-controlled addresses, not real people.
3. **Kill switch.** Outbound email is routed to `STAFF_SINK_EMAIL`; outbound
   SMS is routed to `STAFF_SINK_NUMBER`. Both overrides apply unless
   `LIVE_OUTBOUND=1` is explicitly set. Default MUST be unset. See
   [agent/email_handler.py](../agent/email_handler.py) and
   [agent/sms_gateway.py](../agent/sms_gateway.py); enforced by
   [tests/test_kill_switch.py](../tests/test_kill_switch.py).
4. **Grounded honesty.** The agent may ONLY claim a hiring signal, funding
   event, layoff, or leadership change that appears in the live brief for the
   specific prospect. Over-claiming damages Tenacious's brand and is flagged
   by [agent/policy.py](../agent/policy.py). If a signal's confidence is low
   or none, the agent must ask rather than assert.
5. **No capacity commitments.** The agent never promises a specific number of
   engineers, a start date, or an end date. Capacity questions route to a
   Tenacious delivery lead.
6. **No pricing.** Public-tier pricing bands may be referenced from the
   committed pricing sheet; deeper pricing routes to a human.
7. **Seed materials (sales deck, case studies, style guide) are not
   redistributable.** At the end of the challenge week, delete any local
   copies outside the program repo.
8. **Tenacious-branded outputs are marked draft in metadata** (email HTML,
   call scripts, pricing). The Tenacious executive team reserves the right
   to redact any such content from the final memo.

## Kill-switch verification

```python
# agent/email_handler.py and agent/sms_gateway.py both route:
if not settings.LIVE_OUTBOUND:
    actual_to = settings.STAFF_SINK_EMAIL   # or STAFF_SINK_NUMBER
```

`tests/test_kill_switch.py` asserts:
- With `LIVE_OUTBOUND` unset, no email/SMS reaches a non-sink address.
- With neither the sink nor `LIVE_OUTBOUND` set, outbound is dropped, not sent.
- With `LIVE_OUTBOUND=1`, the original address is preserved.
