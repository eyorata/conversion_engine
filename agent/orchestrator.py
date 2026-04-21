"""Orchestrates one inbound SMS turn end-to-end.

Flow:
  1. classify inbound (stop/help/message)
  2. load conversation state
  3. if first touch, run enrichment pipeline (Crunchbase + CFPB + news)
  4. call LLM with briefs + turns + available slots
  5. policy check on proposed reply; regenerate once on violation
  6. if intent=book, call Cal.com
  7. upsert HubSpot contact + note
  8. send SMS (kill switch applies)
  9. persist conversation state
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from agent import state
from agent.calcom_client import Booking, CalcomClient
from agent.hubspot_client import HubSpotClient
from agent.llm import LLMClient
from agent.policy import check_reply
from agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION, build_user_prompt
from agent.sms_gateway import SMSGateway, classify_inbound
from agent.tracing import get_tracer
from enrichment.pipeline import enrich_sync

log = logging.getLogger(__name__)

_STOP_REPLY = "You are unsubscribed. Reply HELP for help."
_HELP_REPLY = "Acme ComplianceOS SDR. Reply STOP to opt out, or a brief note about your compliance workflow."


class Orchestrator:
    def __init__(self) -> None:
        self.llm = LLMClient(tier="dev")
        self.sms = SMSGateway()
        self.hubspot = HubSpotClient()
        self.calcom = CalcomClient()
        self.tracer = get_tracer()

    def handle_inbound(
        self,
        *,
        phone: str,
        text: str,
        email: Optional[str] = None,
        company_hint: Optional[str] = None,
    ) -> dict:
        started = datetime.now(tz=timezone.utc)
        with self.tracer.span(
            "inbound_turn",
            phone=phone,
            prompt_version=SYSTEM_PROMPT_VERSION,
        ) as trace:
            trace_id = getattr(trace, "id", None) or "untraced"
            conv = state.load(phone)
            conv.turns.append(state.Turn(role="user", text=text, at=started.isoformat(), trace_id=trace_id))

            kind = classify_inbound(text)
            if kind == "stop":
                conv.opted_out = True
                conv.stage = "opted_out"
                self.sms.send(phone, _STOP_REPLY)
                conv.turns.append(state.Turn(role="agent", text=_STOP_REPLY, at=datetime.now(tz=timezone.utc).isoformat(), trace_id=trace_id))
                state.save(conv)
                return {"trace_id": trace_id, "kind": "stop", "reply": _STOP_REPLY}

            if kind == "help":
                self.sms.send(phone, _HELP_REPLY)
                conv.turns.append(state.Turn(role="agent", text=_HELP_REPLY, at=datetime.now(tz=timezone.utc).isoformat(), trace_id=trace_id))
                state.save(conv)
                return {"trace_id": trace_id, "kind": "help", "reply": _HELP_REPLY}

            if conv.opted_out:
                return {"trace_id": trace_id, "kind": "ignored_opted_out", "reply": None}

            enrichment = {"enrichment_brief": {}, "compliance_brief": {}, "news_brief": {}}
            if conv.stage in ("new",):
                try:
                    enrichment = enrich_sync(email=email, company=company_hint, phone=phone)
                    eb = enrichment["enrichment_brief"]
                    conv.crunchbase_id = eb.get("crunchbase_id")
                    conv.company = eb.get("company") or company_hint
                    conv.stage = "enriched"
                except Exception as e:
                    log.exception("enrichment failed: %s", e)
                    enrichment["enrichment_brief"] = {"match": "no_crunchbase_hit", "error": str(e)}

            slots = self.calcom.available_slots()
            user_prompt = build_user_prompt(
                enrichment_brief=enrichment["enrichment_brief"],
                compliance_brief=enrichment["compliance_brief"],
                news_brief=enrichment["news_brief"],
                conversation_turns=[asdict(t) for t in conv.turns],
                available_slots=slots,
            )

            parsed, raw_text = self._call_llm(user_prompt)
            reply = parsed.get("reply")
            policy = check_reply(
                reply or "",
                enrichment_brief=enrichment["enrichment_brief"],
                compliance_brief=enrichment["compliance_brief"],
            )
            regen_info: Optional[dict] = None
            if not policy.ok:
                log.warning("policy violations: %s; regenerating", policy.violations)
                redo_prompt = (
                    user_prompt
                    + "\n\nPREVIOUS_DRAFT_REJECTED:\n"
                    + json.dumps({"draft": reply, "violations": policy.violations}, indent=2)
                    + "\n\nRewrite strictly within the HARD RULES."
                )
                parsed, raw_text = self._call_llm(redo_prompt)
                reply = parsed.get("reply")
                policy2 = check_reply(
                    reply or "",
                    enrichment_brief=enrichment["enrichment_brief"],
                    compliance_brief=enrichment["compliance_brief"],
                )
                regen_info = {"first_violations": policy.violations, "resolved": policy2.ok}
                if not policy2.ok:
                    log.error("policy still failing; dropping reply")
                    reply = None

            booking: Optional[Booking] = None
            if parsed.get("intent") == "book" and parsed.get("book_slot"):
                booking = self.calcom.book(
                    start_at=parsed["book_slot"],
                    name=conv.company or "Prospect",
                    email=email or f"{phone}@sink.test",
                    phone=phone,
                    company=conv.company,
                )
                conv.booked = booking.booking_id is not None and booking.error in (None, "dry_run")

            contact = self.hubspot.upsert_contact(
                phone=phone,
                email=email,
                company=conv.company,
                crunchbase_id=conv.crunchbase_id,
                compliance_brief=enrichment["compliance_brief"],
                stage=conv.stage,
            )
            if contact.contact_id and reply:
                self.hubspot.log_note(contact.contact_id, f"Inbound: {text}\nOutbound: {reply}")

            send_result = None
            if reply:
                send_result = self.sms.send(phone, reply)
                conv.turns.append(state.Turn(role="agent", text=reply, at=datetime.now(tz=timezone.utc).isoformat(), trace_id=trace_id))
                conv.last_outbound_at = datetime.now(tz=timezone.utc).isoformat()

            state.save(conv)

            latency_ms = (datetime.now(tz=timezone.utc) - started).total_seconds() * 1000
            result = {
                "trace_id": trace_id,
                "kind": "message",
                "reply": reply,
                "intent": parsed.get("intent"),
                "booking": asdict(booking) if booking else None,
                "policy": {"regen": regen_info} if regen_info else {"ok": True},
                "hubspot_contact_id": contact.contact_id,
                "latency_ms": latency_ms,
                "send_result": asdict(send_result) if send_result else None,
            }
            try:
                trace.update(output=json.dumps(result, default=str), metadata={"latency_ms": latency_ms})
            except Exception:
                pass
            return result

    def _call_llm(self, user_prompt: str) -> tuple[dict, str]:
        resp = self.llm.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=400,
            temperature=0.2,
        )
        raw = resp.text.strip()
        parsed: dict
        try:
            parsed = json.loads(raw)
        except Exception:
            # Some models wrap JSON in fences
            cleaned = raw.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                parsed = json.loads(cleaned)
            except Exception:
                log.warning("LLM returned non-JSON; falling back")
                parsed = {"reply": raw, "intent": "clarify", "book_slot": None, "confidence": 0.3, "reasoning": "parse_fail"}
        return parsed, raw
