"""Crunchbase ODM sample loader.

Source: https://github.com/luminati-io/Crunchbase-dataset-samples (Apache 2.0, 1,001 records).

Loaded into memory once. Lookup by phone / email / domain / fuzzy company name.
Every hit includes the crunchbase_id and last_enriched_at timestamp per spec.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLE_PATH = DATA_DIR / "crunchbase_sample.json"
# Bright Data's sample lives under releases; users can also run scripts/fetch_crunchbase.py
SAMPLE_URL = (
    "https://raw.githubusercontent.com/luminati-io/Crunchbase-dataset-samples/main/"
    "crunchbase-companies-information-sample.json"
)


@dataclass
class CrunchbaseRecord:
    crunchbase_id: str
    name: str
    domain: Optional[str]
    industry: Optional[str]
    employee_count: Optional[str]
    country: Optional[str]
    state: Optional[str]
    founded_year: Optional[int]
    total_funding_usd: Optional[float]
    last_funding_type: Optional[str]
    last_funding_at: Optional[str]
    description: Optional[str]
    raw: dict


def _ensure_sample() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PATH.exists() and SAMPLE_PATH.stat().st_size > 0:
        return SAMPLE_PATH
    log.info("Fetching Crunchbase ODM sample from %s", SAMPLE_URL)
    r = httpx.get(SAMPLE_URL, timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    SAMPLE_PATH.write_bytes(r.content)
    return SAMPLE_PATH


def _coerce(row: dict) -> CrunchbaseRecord:
    # The Bright Data sample has inconsistent keys across releases; be defensive.
    name = row.get("name") or row.get("company_name") or row.get("organization_name") or ""
    domain = row.get("domain") or row.get("website") or row.get("homepage_url")
    if domain:
        domain = re.sub(r"^https?://(www\.)?", "", domain).rstrip("/").split("/")[0] or None
    cb_id = (
        row.get("uuid")
        or row.get("crunchbase_uuid")
        or row.get("permalink")
        or row.get("id")
        or name.lower().replace(" ", "-")
    )
    return CrunchbaseRecord(
        crunchbase_id=str(cb_id),
        name=name,
        domain=domain,
        industry=row.get("industry") or row.get("category_groups_list") or row.get("categories"),
        employee_count=row.get("num_employees_enum") or row.get("employee_count"),
        country=row.get("country_code") or row.get("country"),
        state=row.get("state_code") or row.get("region"),
        founded_year=row.get("founded_year"),
        total_funding_usd=row.get("total_funding_usd") or row.get("total_funding"),
        last_funding_type=row.get("last_funding_type"),
        last_funding_at=row.get("last_funding_at") or row.get("last_funding_on"),
        description=row.get("short_description") or row.get("description"),
        raw=row,
    )


class CrunchbaseIndex:
    """In-memory index over the ODM sample."""

    def __init__(self) -> None:
        self.by_domain: dict[str, CrunchbaseRecord] = {}
        self.by_name: dict[str, CrunchbaseRecord] = {}
        self.all: list[CrunchbaseRecord] = []

    @classmethod
    def load(cls) -> "CrunchbaseIndex":
        path = _ensure_sample()
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Some releases wrap rows in a list, others in {"data": [...]}
        rows = raw if isinstance(raw, list) else raw.get("data") or raw.get("companies") or []
        idx = cls()
        for row in rows:
            rec = _coerce(row)
            idx.all.append(rec)
            if rec.domain:
                idx.by_domain[rec.domain.lower()] = rec
            if rec.name:
                idx.by_name[rec.name.lower()] = rec
        log.info("Loaded %d Crunchbase records", len(idx.all))
        return idx

    def lookup(
        self,
        *,
        email: Optional[str] = None,
        domain: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[CrunchbaseRecord]:
        if email and "@" in email:
            domain = domain or email.split("@", 1)[1]
        if domain:
            hit = self.by_domain.get(domain.lower())
            if hit:
                return hit
        if name:
            hit = self.by_name.get(name.lower())
            if hit:
                return hit
            for n, rec in self.by_name.items():
                if name.lower() in n or n in name.lower():
                    return rec
        return None


def build_enrichment_brief(rec: CrunchbaseRecord) -> dict:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "crunchbase_id": rec.crunchbase_id,
        "last_enriched_at": now,
        "company": rec.name,
        "domain": rec.domain,
        "industry": rec.industry,
        "employee_count": rec.employee_count,
        "country": rec.country,
        "state": rec.state,
        "founded_year": rec.founded_year,
        "total_funding_usd": rec.total_funding_usd,
        "last_funding_type": rec.last_funding_type,
        "last_funding_at": rec.last_funding_at,
        "description": rec.description,
        "source": "crunchbase_odm_sample",
    }
