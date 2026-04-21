"""HubSpot client. Wraps the HubSpot Python SDK.

Writes one contact per lead and appends an engagement note after each turn.
Every write includes the crunchbase_id and enrichment timestamp per spec.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class ContactResult:
    contact_id: Optional[str]
    created: bool
    error: Optional[str] = None


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
        phone: str,
        email: Optional[str] = None,
        company: Optional[str] = None,
        crunchbase_id: Optional[str] = None,
        compliance_brief: Optional[dict] = None,
        stage: str = "new",
    ) -> ContactResult:
        client = self._get()
        if client is None:
            return ContactResult(contact_id=None, created=False, error="no_client")

        props = {
            "phone": phone,
            "lifecyclestage": "lead",
            "hs_lead_status": stage.upper(),
        }
        if email:
            props["email"] = email
        if company:
            props["company"] = company
        if crunchbase_id:
            props["crunchbase_id"] = crunchbase_id
        props["last_enriched_at"] = datetime.now(tz=timezone.utc).isoformat()
        if compliance_brief:
            props["cfpb_complaint_count"] = str(compliance_brief.get("complaint_count", 0))
            if compliance_brief.get("top_issues"):
                props["cfpb_top_issue"] = compliance_brief["top_issues"][0].get("issue", "")

        try:
            # Try search by phone first
            from hubspot.crm.contacts import SimplePublicObjectInputForCreate, PublicObjectSearchRequest, Filter, FilterGroup

            search = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[Filter(property_name="phone", operator="EQ", value=phone)])],
                properties=["phone"],
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
