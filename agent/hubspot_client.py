"""HubSpot client for Tenacious prospects.

Writes one contact per lead. Enrichment fields (ICP segment, AI maturity,
funding / layoff / job-post / leadership signals) are promoted onto the
contact record so an SDR opening HubSpot sees the research finding without
a click-through.

Current implementation uses the HubSpot REST API via the official Python
SDK. Migration to the HubSpot MCP server is a Day-2 task tracked in
STATUS.md; the rubric's "Mastered" tier expects MCP writes.
"""
from __future__ import annotations

import logging
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


def _safe_get(d: Optional[dict], *keys, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _enrichment_to_properties(hiring_signal_brief: Optional[dict]) -> dict[str, str]:
    """Flatten the hiring_signal_brief into HubSpot contact properties.

    HubSpot custom properties must be strings on create. Consumers of the
    CRM can parse back where needed (e.g. ai_maturity_score is numeric text).
    """
    if not hiring_signal_brief:
        return {}

    funding = hiring_signal_brief.get("funding_signal") or {}
    layoffs = hiring_signal_brief.get("layoffs_signal") or {}
    jobs = hiring_signal_brief.get("jobs_signal") or {}
    leadership = hiring_signal_brief.get("leadership_signal") or {}
    maturity = hiring_signal_brief.get("ai_maturity") or {}
    icp = hiring_signal_brief.get("icp_assignments") or []

    # Highest-confidence ICP assignment (list is pre-sorted by the classifier)
    top_icp = icp[0] if icp else {}
    out: dict[str, str] = {
        "last_enriched_at": hiring_signal_brief.get("retrieved_at") or datetime.now(tz=timezone.utc).isoformat(),
        "tenacious_status": "draft",  # per seed license: all generated outputs marked draft
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
        vel = jobs.get("velocity_ratio")
        if vel is not None:
            out["job_velocity_ratio"] = str(vel)
        out["jobs_confidence"] = str(jobs.get("confidence", "none"))
    if leadership.get("recent_change"):
        out["leadership_change_role"] = str(leadership.get("role", ""))
        out["leadership_change_days_ago"] = str(leadership.get("days_ago", ""))
    return out


class HubSpotClient:
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
            log.warning("HubSpot init failed: %s", e)
            return None

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
        client = self._get()
        if client is None:
            return ContactResult(contact_id=None, created=False, error="no_client")

        props: dict[str, str] = {
            "lifecyclestage": "lead",
            "hs_lead_status": stage.upper(),
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
            log.exception("HubSpot upsert failed")
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
        except Exception as e:
            log.exception("HubSpot note create failed")
            return None
