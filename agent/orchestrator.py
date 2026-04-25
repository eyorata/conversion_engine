"""Orchestrates one turn end-to-end for Tenacious.

Email is primary. SMS is only used for warm-lead scheduling handoff after a
positive email reply. Voice (discovery call) is booked by the agent and
delivered by a human.

Flow for an inbound email reply:
  1. load conversation state
  2. run enrichment on first touch -> hiring_signal_brief + competitor_gap_brief
  3. call LLM with briefs + turns + slots
  4. policy check proposed message; regenerate once if violation
  5. if intent=book, call Cal.com
  6. upsert HubSpot contact + log note
  7. send via email (or SMS if LLM chose that channel for warm-lead scheduling)
  8. persist state

The same method also handles outbound-first flow (synthetic seeding), inbound
SMS replies from already-warm leads, and unsubscribe handling.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from agent import state
from agent.calcom_client import Booking, CalcomClient
from agent.dual_control import should_block_booking
from agent.email_handler import EmailHandler, classify_email_reply
from agent.hubspot_client import HubSpotClient
from agent.llm import LLMClient
from agent.policy import check_outbound
from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION, build_user_prompt
from agent.sms_gateway import SMSGateway, classify_inbound
from agent.tracing import get_tracer
from enrichment.pipeline import enrich

log = logging.getLogger(__name__)

_STOP_REPLY_EMAIL_SUBJECT = "Unsubscribed"
_STOP_REPLY_EMAIL_BODY = (
    "You're unsubscribed. We won't reach out again. "
    "If that was a mistake, reply and we'll resume — otherwise, all the best."
)
_STOP_REPLY_SMS = "Unsubscribed. Reply HELP for help."


class Orchestrator:
    def __init__(self) -> None:
        self.llm = LLMClient(tier="dev")
        self.email = EmailHandler()
        self.sms = SMSGateway()
        self.hubspot = HubSpotClient()
        self.calcom = CalcomClient()
        self.tracer = get_tracer()

    def handle_turn(
        self,
        *,
        channel_in: str,            # "email" | "sms" | "seed"
        inbound_text: str | None,
        contact_key: str,           # phone or email — used as conversation state key
        email: Optional[str] = None,
        phone: Optional[str] = None,
        company_hint: Optional[str] = None,
        domain_hint: Optional[str] = None,
    ) -> dict:
        started = datetime.now(tz=timezone.utc)
        with self.tracer.span(
            "turn",
            channel_in=channel_in,
            prompt_version=SYSTEM_PROMPT_VERSION,
        ) as trace:
            trace_id = getattr(trace, "id", None) or "untraced"
            conv = state.load(contact_key)
            if inbound_text:
                conv.turns.append(state.Turn(
                    role="user",
                    text=inbound_text,
                    at=started.isoformat(),
                    trace_id=trace_id,
                    channel=channel_in,
                ))

            # unsubscribe handling
            if channel_in == "sms" and classify_inbound(inbound_text or "") == "stop":
                conv.opted_out = True
                conv.stage = "opted_out"
                self.sms.send(phone or contact_key, _STOP_REPLY_SMS)
                conv.turns.append(state.Turn(role="agent", text=_STOP_REPLY_SMS,
                                             at=datetime.now(tz=timezone.utc).isoformat(),
                                             trace_id=trace_id, channel="sms"))
                state.save(conv)
                return {"trace_id": trace_id, "kind": "stop", "channel_out": "sms"}
            if channel_in == "email" and inbound_text and classify_email_reply(inbound_text) == "unsubscribe":
                conv.opted_out = True
                conv.stage = "opted_out"
                self.email.send(
                    to=email or contact_key,
                    subject=_STOP_REPLY_EMAIL_SUBJECT,
                    html=f"<p>{_STOP_REPLY_EMAIL_BODY}</p>",
                    text=_STOP_REPLY_EMAIL_BODY,
                )
                conv.turns.append(state.Turn(role="agent", text=_STOP_REPLY_EMAIL_BODY,
                                             at=datetime.now(tz=timezone.utc).isoformat(),
                                             trace_id=trace_id, channel="email"))
                state.save(conv)
                return {"trace_id": trace_id, "kind": "stop", "channel_out": "email"}

            if conv.opted_out:
                return {"trace_id": trace_id, "kind": "ignored_opted_out"}

            if conv.undeliverable:
                return {"trace_id": trace_id, "kind": "ignored_undeliverable"}

            # enrich on first touch
            enrichment = {"hiring_signal_brief": {}, "competitor_gap_brief": None}
            if conv.stage in ("new",):
                try:
                    enrichment = enrich(
                        email=email,
                        domain=domain_hint,
                        company=company_hint,
                        phone=phone,
                    )
                    hsb = enrichment["hiring_signal_brief"]
                    prospect = hsb.get("prospect") or {}
                    conv.crunchbase_id = prospect.get("crunchbase_id")
                    conv.company = prospect.get("company") or company_hint
                    conv.stage = "enriched"
                except Exception as e:
                    log.exception("enrichment failed: %s", e)
                    enrichment["hiring_signal_brief"] = {"match": "no_crunchbase_hit", "error": str(e)}

            slots = self.calcom.available_slots()
            # Channel hierarchy: SMS is warm-lead scheduling ONLY. Warm lead is
            # defined as a prospect who has previously replied via email
            # (not counting the current inbound). Everything else is email.
            prior_email_reply = any(
                (t.role == "user" and t.channel == "email")
                for t in conv.turns[:-1]  # exclude the current inbound (already appended)
            )
            is_warm_lead = prior_email_reply
            outbound_channel = "email"
            if channel_in == "sms" and is_warm_lead:
                outbound_channel = "sms"

            user_prompt = build_user_prompt(
                channel=outbound_channel,
                hiring_signal_brief=enrichment["hiring_signal_brief"],
                competitor_gap_brief=enrichment.get("competitor_gap_brief"),
                conversation_turns=[asdict(t) for t in conv.turns],
                available_slots=slots,
            )

            parsed, _raw = self._call_llm(user_prompt)
            subject = parsed.get("subject")
            body = parsed.get("body") or ""
            channel_out = parsed.get("channel") or outbound_channel
            if channel_out not in ("email", "sms"):
                channel_out = outbound_channel
            # HARD GATE: LLM cannot escalate a cold contact to SMS. If the
            # prospect hasn't replied via email yet, force email regardless
            # of what the LLM asked for.
            if channel_out == "sms" and not is_warm_lead:
                log.warning("LLM picked sms for cold prospect; forcing email (channel hierarchy)")
                channel_out = "email"
                if parsed.get("channel") == "sms":
                    parsed["channel"] = "email"

            policy = check_outbound(
                channel=channel_out,
                subject=subject,
                body=body,
                hiring_signal_brief=enrichment["hiring_signal_brief"],
                competitor_gap_brief=enrichment.get("competitor_gap_brief"),
            )
            regen_info = None
            if not policy.ok:
                log.warning("policy violations, regenerating: %s", policy.violations)
                redo = (
                    user_prompt
                    + "\n\nPREVIOUS_DRAFT_REJECTED:\n"
                    + json.dumps({"subject": subject, "body": body, "violations": policy.violations}, indent=2)
                    + "\n\nRewrite strictly within the HARD RULES. Do not repeat the rejected phrasing."
                )
                parsed2, _raw2 = self._call_llm(redo)
                subject2 = parsed2.get("subject") or subject
                body2 = parsed2.get("body") or ""
                channel_out2 = parsed2.get("channel") or channel_out
                policy2 = check_outbound(
                    channel=channel_out2,
                    subject=subject2,
                    body=body2,
                    hiring_signal_brief=enrichment["hiring_signal_brief"],
                    competitor_gap_brief=enrichment.get("competitor_gap_brief"),
                )
                regen_info = {"first_violations": policy.violations, "resolved": policy2.ok, "second_violations": policy2.violations}
                if policy2.ok:
                    parsed, subject, body, channel_out = parsed2, subject2, body2, channel_out2
                else:
                    log.error("policy still failing after regen; dropping outbound")
                    body = ""

            # Dual-control commitment gate (DCCG). If the prospect's latest
            # inbound contains a scheduling-deferral signal ("let me check my
            # calendar," "thinking about it," etc.) AND no explicit slot
            # acceptance, suppress the booking. See agent/dual_control.py and
            # probes/target_failure_mode.md for the full design.
            dccg_blocked, dccg_signal = should_block_booking(inbound_text or "")
            dccg_fired = False
            if dccg_blocked and parsed.get("intent") == "book":
                log.info("DCCG fired: kind=%s; coercing intent=book -> reply", dccg_signal.kind)
                parsed["intent"] = "reply"
                parsed["book_slot"] = None
                dccg_fired = True

            booking: Optional[Booking] = None
            if parsed.get("intent") == "book" and parsed.get("book_slot"):
                # Coerce to an actually-offered slot. The LLM sometimes
                # hallucinates or reformats times; Cal.com then rejects with
                # "User either already has booking at this time or is not
                # available" even when real availability exists.
                chosen = parsed["book_slot"]
                if slots and chosen not in slots:
                    log.warning("LLM picked %r not in offered slots; falling back to %r", chosen, slots[0])
                    chosen = slots[0]
                booking = self.calcom.book(
                    start_at=chosen,
                    name=conv.company or "Prospect",
                    email=email or f"{contact_key}@sink.test",
                    phone=phone or "",
                    company=conv.company,
                )
                conv.booked = booking.booking_id is not None and booking.error in (None, "dry_run")
                conv.stage = "booked"
                if booking.booking_url:
                    body = body.rstrip() + f"\n\nBooking link: {booking.booking_url}"

            contact = self.hubspot.upsert_contact(
                phone=phone or None,
                email=email,
                company=conv.company,
                crunchbase_id=conv.crunchbase_id,
                stage=conv.stage,
                hiring_signal_brief=enrichment.get("hiring_signal_brief"),
                booking_id=(booking.booking_id if booking else None),
            )
            if contact.contact_id and body:
                self.hubspot.log_note(
                    contact.contact_id,
                    f"Channel: {channel_out}\nInbound: {inbound_text or '(outbound-first)'}\n"
                    f"Subject: {subject or '-'}\nOutbound: {body}",
                )

            send_result = None
            if body:
                if channel_out == "email":
                    send_result = self.email.send(
                        to=email or contact_key,
                        subject=subject or "(no subject)",
                        html=f"<p>{body.replace(chr(10), '</p><p>')}</p>",
                        text=body,
                    )
                else:
                    send_result = self.sms.send(phone or contact_key, body)

                conv.turns.append(state.Turn(
                    role="agent",
                    text=body,
                    at=datetime.now(tz=timezone.utc).isoformat(),
                    trace_id=trace_id,
                    channel=channel_out,
                ))
                conv.last_outbound_at = datetime.now(tz=timezone.utc).isoformat()

            state.save(conv)
            latency_ms = (datetime.now(tz=timezone.utc) - started).total_seconds() * 1000
            result = {
                "trace_id": trace_id,
                "channel_in": channel_in,
                "channel_out": channel_out,
                "subject": subject,
                "reply": body,
                "intent": parsed.get("intent"),
                "segment_used": parsed.get("segment_used"),
                "booking": asdict(booking) if booking else None,
                "policy": {"regen": regen_info} if regen_info else {"ok": True},
                "dccg": {
                    "fired": dccg_fired,
                    "signal_kind": dccg_signal.kind if dccg_signal else None,
                },
                "hubspot_contact_id": contact.contact_id,
                "latency_ms": latency_ms,
                "send_result": asdict(send_result) if send_result else None,
                "enrichment_summary": {
                    "crunchbase_id": conv.crunchbase_id,
                    "icp_assignments": enrichment.get("hiring_signal_brief", {}).get("icp_assignments"),
                    "ai_maturity": (enrichment.get("hiring_signal_brief", {}).get("ai_maturity") or {}).get("score"),
                    "peer_count": (enrichment.get("competitor_gap_brief") or {}).get("peer_count"),
                },
            }
            try:
                trace.update(output=json.dumps(result, default=str), metadata={"latency_ms": latency_ms})
            except Exception:
                pass
            return result

    def _call_llm(self, user_prompt: str) -> tuple[dict, str]:
        try:
            resp = self.llm.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=600,
                temperature=0.2,
            )
            raw = resp.text.strip()
        except Exception as e:
            log.warning("LLM call failed: %s; using stub reply", e)
            return (
                {
                    "channel": "email",
                    "subject": "Quick note on your engineering capacity",
                    "body": "Hi — saw your public careers page list several engineering openings. Open to a 30-minute call to hear what you're prioritizing this quarter? No pitch in the first call.",
                    "intent": "greet",
                    "segment_used": None,
                    "book_slot": None,
                    "confidence": 0.35,
                    "reasoning": "LLM unavailable; canned neutral opener",
                },
                "",
            )
        try:
            parsed = json.loads(raw)
        except Exception:
            cleaned = raw.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                parsed = json.loads(cleaned)
            except Exception:
                log.warning("LLM returned non-JSON; falling back")
                parsed = {
                    "channel": "email",
                    "subject": "Quick note",
                    "body": raw,
                    "intent": "clarify",
                    "book_slot": None,
                    "confidence": 0.2,
                    "reasoning": "parse_fail",
                }
        return parsed, raw
