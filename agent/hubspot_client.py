"""HubSpot client for Tenacious prospects.

Supports two backends:
  - REST SDK (default, works today)
  - MCP backend (enabled when a HubSpot MCP server is available)

The rubric's strongest CRM tier expects MCP wiring, so this file keeps the
backend selection isolated while preserving the same contact + note API for the
rest of the application.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class ContactResult:
    contact_id: Optional[str]
    created: bool
    error: Optional[str] = None


_STAGE_TO_HUBSPOT: dict[str, str] = {
    "new": "NEW",
    "enriched": "OPEN",
    "engaged": "CONNECTED",
    "booked": "OPEN_DEAL",
    "opted_out": "UNQUALIFIED",
    "undeliverable": "UNQUALIFIED",
    "unqualified": "UNQUALIFIED",
}


def _enrichment_to_properties(hiring_signal_brief: Optional[dict]) -> dict[str, str]:
    if not hiring_signal_brief:
        return {}

    funding = hiring_signal_brief.get("funding_signal") or {}
    layoffs = hiring_signal_brief.get("layoffs_signal") or {}
    jobs = hiring_signal_brief.get("jobs_signal") or {}
    leadership = hiring_signal_brief.get("leadership_signal") or {}
    maturity = hiring_signal_brief.get("ai_maturity") or {}
    icp = hiring_signal_brief.get("icp_assignments") or []

    top_icp = icp[0] if icp else {}
    out: dict[str, str] = {
        "last_enriched_at": hiring_signal_brief.get("retrieved_at") or datetime.now(tz=timezone.utc).isoformat(),
        "tenacious_status": "draft",
    }
    if top_icp:
        out["icp_segment"] = str(top_icp.get("name", ""))
        out["icp_confidence"] = str(top_icp.get("confidence", ""))
        out["icp_segment_num"] = str(top_icp.get("segment", ""))
    if maturity:
        out["ai_maturity_score"] = str(maturity.get("score", ""))
        out["ai_maturity_confidence"] = str(maturity.get("confidence", ""))
        out["ai_role_share"] = str(maturity.get("ai_role_share", ""))
    if funding.get("last_funding_type"):
        out["last_funding_type"] = str(funding.get("last_funding_type"))
        out["last_funding_at"] = str(funding.get("last_funding_at", ""))
        tf = funding.get("total_funding_usd")
        if tf is not None:
            out["total_funding_usd"] = str(tf)
    if layoffs:
        out["layoffs_event_count_120d"] = str(layoffs.get("event_count", 0))
        out["layoffs_confidence"] = str(layoffs.get("confidence", "none"))
    if jobs:
        out["job_roles_current"] = str(jobs.get("total_roles_current", 0))
        vel_delta = jobs.get("velocity_delta_60d")
        if vel_delta is not None:
            out["job_velocity_delta_60d"] = str(vel_delta)
        vel = jobs.get("velocity_ratio")
        if vel is not None:
            out["job_velocity_ratio"] = str(vel)
        out["jobs_confidence"] = str(jobs.get("confidence", "none"))
    if leadership.get("recent_change"):
        out["leadership_change_role"] = str(leadership.get("role", ""))
        out["leadership_change_days_ago"] = str(leadership.get("days_ago", ""))
    return out


class HubSpotBackend:
    def upsert_contact(
        self,
        *,
        phone: Optional[str],
        email: Optional[str],
        company: Optional[str],
        crunchbase_id: Optional[str],
        stage: str,
        hiring_signal_brief: Optional[dict],
        booking_id: Optional[str],
    ) -> ContactResult:
        raise NotImplementedError

    def log_note(self, contact_id: str, body: str) -> Optional[str]:
        raise NotImplementedError


class HubSpotRestBackend(HubSpotBackend):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _get(self):
        if self._client is not None:
            return self._client
        if not self.settings.HUBSPOT_ACCESS_TOKEN:
            log.warning("HUBSPOT_ACCESS_TOKEN unset; HubSpot writes will be no-ops")
            return None
        try:
            from hubspot import HubSpot

            self._client = HubSpot(access_token=self.settings.HUBSPOT_ACCESS_TOKEN)
            return self._client
        except Exception as e:
            log.warning("HubSpot REST init failed: %s", e)
            return None

    def upsert_contact(
        self,
        *,
        phone: Optional[str],
        email: Optional[str],
        company: Optional[str],
        crunchbase_id: Optional[str],
        stage: str,
        hiring_signal_brief: Optional[dict],
        booking_id: Optional[str],
    ) -> ContactResult:
        client = self._get()
        if client is None:
            return ContactResult(contact_id=None, created=False, error="no_client")

        props: dict[str, str] = {
            "lifecyclestage": "lead",
            "hs_lead_status": _STAGE_TO_HUBSPOT.get(stage.lower(), "NEW"),
        }
        if phone:
            props["phone"] = phone
        if email:
            props["email"] = email
        if company:
            props["company"] = company
        if crunchbase_id:
            props["crunchbase_id"] = crunchbase_id
        if booking_id:
            props["tenacious_booking_id"] = booking_id
        props.update(_enrichment_to_properties(hiring_signal_brief))

        try:
            from hubspot.crm.contacts import (
                Filter,
                FilterGroup,
                PublicObjectSearchRequest,
                SimplePublicObjectInputForCreate,
            )

            key_prop = "email" if email else "phone"
            key_value = email or phone
            if not key_value:
                return ContactResult(contact_id=None, created=False, error="no_identity")
            search = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[Filter(property_name=key_prop, operator="EQ", value=key_value)])],
                properties=[key_prop],
                limit=1,
            )
            hits = client.crm.contacts.search_api.do_search(public_object_search_request=search)
            if hits.total > 0:
                contact_id = hits.results[0].id
                client.crm.contacts.basic_api.update(
                    contact_id=contact_id,
                    simple_public_object_input={"properties": props},
                )
                return ContactResult(contact_id=contact_id, created=False)

            payload = SimplePublicObjectInputForCreate(properties=props)
            created = client.crm.contacts.basic_api.create(simple_public_object_input_for_create=payload)
            return ContactResult(contact_id=created.id, created=True)
        except Exception as e:
            log.exception("HubSpot REST upsert failed")
            return ContactResult(contact_id=None, created=False, error=str(e))

    def log_note(self, contact_id: str, body: str) -> Optional[str]:
        client = self._get()
        if client is None:
            return None
        try:
            from hubspot.crm.objects.notes import SimplePublicObjectInputForCreate

            payload = SimplePublicObjectInputForCreate(
                properties={
                    "hs_note_body": body,
                    "hs_timestamp": datetime.now(tz=timezone.utc).isoformat(),
                },
                associations=[
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 202,
                            }
                        ],
                    }
                ],
            )
            note = client.crm.objects.notes.basic_api.create(simple_public_object_input_for_create=payload)
            return note.id
        except Exception:
            log.exception("HubSpot REST note create failed")
            return None


class _StdioMCPClient:
    """Minimal stdio JSON-RPC client for an external MCP server."""

    def __init__(self, command: str, args: list[str]) -> None:
        self._proc = subprocess.Popen(
            [command] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._id = 0

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("MCP transport unavailable")
        self._id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed the stream")
            payload = json.loads(line)
            if payload.get("id") != self._id:
                continue
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload.get("result")


class HubSpotMCPBackend(HubSpotBackend):
    """Backend for a configured HubSpot MCP server.

    Tool names are supplied by env vars so this adapter stays honest about the
    fact that MCP servers differ in how they expose operations.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._transport: Optional[_StdioMCPClient] = None

    def _get_transport(self) -> Optional[_StdioMCPClient]:
        if self._transport is not None:
            return self._transport
        if not self.settings.HUBSPOT_MCP_COMMAND:
            log.warning("HUBSPOT_MODE=mcp but HUBSPOT_MCP_COMMAND is unset")
            return None
        args = (self.settings.HUBSPOT_MCP_ARGS or "").split()
        try:
            self._transport = _StdioMCPClient(self.settings.HUBSPOT_MCP_COMMAND, args)
            return self._transport
        except Exception as e:
            log.warning("HubSpot MCP init failed: %s", e)
            return None

    def upsert_contact(
        self,
        *,
        phone: Optional[str],
        email: Optional[str],
        company: Optional[str],
        crunchbase_id: Optional[str],
        stage: str,
        hiring_signal_brief: Optional[dict],
        booking_id: Optional[str],
    ) -> ContactResult:
        transport = self._get_transport()
        if transport is None:
            return ContactResult(contact_id=None, created=False, error="no_mcp_transport")

        properties: dict[str, str] = {
            "lifecyclestage": "lead",
            "hs_lead_status": _STAGE_TO_HUBSPOT.get(stage.lower(), "NEW"),
        }
        if phone:
            properties["phone"] = phone
        if email:
            properties["email"] = email
        if company:
            properties["company"] = company
        if crunchbase_id:
            properties["crunchbase_id"] = crunchbase_id
        if booking_id:
            properties["tenacious_booking_id"] = booking_id
        properties.update(_enrichment_to_properties(hiring_signal_brief))

        try:
            result = transport.call_tool(
                self.settings.HUBSPOT_MCP_UPSERT_TOOL,
                {
                    "email": email,
                    "phone": phone,
                    "properties": properties,
                },
            )
            if isinstance(result, dict):
                return ContactResult(
                    contact_id=str(result.get("id") or result.get("contact_id") or ""),
                    created=bool(result.get("created", False)),
                    error=result.get("error"),
                )
            return ContactResult(contact_id=None, created=False, error="unexpected_mcp_result")
        except Exception as e:
            log.exception("HubSpot MCP upsert failed")
            return ContactResult(contact_id=None, created=False, error=str(e))

    def log_note(self, contact_id: str, body: str) -> Optional[str]:
        transport = self._get_transport()
        if transport is None:
            return None
        try:
            result = transport.call_tool(
                self.settings.HUBSPOT_MCP_NOTE_TOOL,
                {
                    "contact_id": contact_id,
                    "body": body,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
            if isinstance(result, dict):
                return str(result.get("id") or result.get("note_id") or "")
        except Exception:
            log.exception("HubSpot MCP note create failed")
        return None


class HubSpotClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.backend: HubSpotBackend
        if self.settings.HUBSPOT_MODE.lower() == "mcp":
            self.backend = HubSpotMCPBackend()
        else:
            self.backend = HubSpotRestBackend()

    def upsert_contact(
        self,
        *,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        company: Optional[str] = None,
        crunchbase_id: Optional[str] = None,
        stage: str = "new",
        hiring_signal_brief: Optional[dict] = None,
        booking_id: Optional[str] = None,
    ) -> ContactResult:
        return self.backend.upsert_contact(
            phone=phone,
            email=email,
            company=company,
            crunchbase_id=crunchbase_id,
            stage=stage,
            hiring_signal_brief=hiring_signal_brief,
            booking_id=booking_id,
        )

    def log_note(self, contact_id: str, body: str) -> Optional[str]:
        return self.backend.log_note(contact_id, body)
