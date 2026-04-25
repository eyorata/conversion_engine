"""Create the custom contact properties this project writes to.

Idempotent: skips any property that already exists. Run once per fresh
HubSpot Developer Sandbox before `scripts.synthetic_conversation` so writes
don't fail with INVALID_PROPERTY.

Usage:
    python -m scripts.provision_hubspot_properties
"""
from __future__ import annotations

import sys

import httpx

from agent.config import get_settings
from agent.logging_setup import setup_logging

setup_logging()

# (name, label, type, fieldType)
# type      = string | number | datetime | enumeration | bool
# fieldType = text   | number | date     | select      | booleancheckbox
PROPERTIES: list[tuple[str, str, str, str]] = [
    # identity
    ("crunchbase_id",              "Crunchbase ID",              "string",   "text"),
    # classification
    ("icp_segment",                "ICP Segment",                "string",   "text"),
    ("icp_segment_num",            "ICP Segment Number",         "string",   "text"),
    ("icp_confidence",             "ICP Confidence",             "string",   "text"),
    # AI maturity
    ("ai_maturity_score",          "AI Maturity Score",          "number",   "number"),
    ("ai_maturity_confidence",     "AI Maturity Confidence",     "string",   "text"),
    ("ai_role_share",              "AI Role Share",              "number",   "number"),
    # funding
    ("last_funding_type",          "Last Funding Type",          "string",   "text"),
    ("last_funding_at",            "Last Funding At",            "string",   "text"),
    ("total_funding_usd",          "Total Funding USD",          "number",   "number"),
    # layoffs
    ("layoffs_event_count_120d",   "Layoffs Event Count (120d)", "number",   "number"),
    ("layoffs_confidence",         "Layoffs Confidence",         "string",   "text"),
    # jobs
    ("job_roles_current",          "Job Roles Current",          "number",   "number"),
    ("job_velocity_ratio",         "Job Velocity Ratio",         "number",   "number"),
    ("jobs_confidence",            "Jobs Confidence",            "string",   "text"),
    # leadership
    ("leadership_change_role",     "Leadership Change Role",     "string",   "text"),
    ("leadership_change_days_ago", "Leadership Change Days Ago", "number",   "number"),
    # provenance
    ("last_enriched_at",           "Last Enriched At",           "string",   "text"),
    ("tenacious_status",           "Tenacious Status",           "string",   "text"),
    ("tenacious_booking_id",       "Tenacious Booking ID",       "string",   "text"),
]

GROUP_NAME = "contactinformation"


def main() -> int:
    settings = get_settings()
    if not settings.HUBSPOT_ACCESS_TOKEN:
        print("HUBSPOT_ACCESS_TOKEN unset; aborting")
        return 2

    headers = {
        "Authorization": f"Bearer {settings.HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    base = "https://api.hubapi.com/crm/v3/properties/contacts"

    existing_resp = httpx.get(base, headers=headers, timeout=30.0)
    existing_resp.raise_for_status()
    existing = {p["name"] for p in existing_resp.json().get("results", [])}
    print(f"portal has {len(existing)} contact properties already")

    created = skipped = failed = 0
    for name, label, dtype, field_type in PROPERTIES:
        if name in existing:
            print(f"  [=] {name:30} already exists")
            skipped += 1
            continue
        body = {
            "name": name,
            "label": label,
            "type": dtype,
            "fieldType": field_type,
            "groupName": GROUP_NAME,
        }
        r = httpx.post(base, headers=headers, json=body, timeout=30.0)
        if r.status_code in (200, 201):
            print(f"  [+] {name:30} created ({dtype}/{field_type})")
            created += 1
        else:
            print(f"  [!] {name:30} FAILED {r.status_code}: {r.text[:180]}")
            failed += 1

    print(f"\ncreated={created}  skipped={skipped}  failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
