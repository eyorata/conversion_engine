"""Crunchbase ODM sample loader.

Source: github.com/luminati-io/Crunchbase-dataset-samples
File: crunchbase-companies-information.csv (~4.8 MB, Apache 2.0)

Loaded into memory once. Lookup by domain / email / fuzzy company name.
Every record keeps its crunchbase_id and gets a last_enriched_at timestamp on use.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLE_PATH = DATA_DIR / "crunchbase_sample.csv"
SAMPLE_URL = (
    "https://raw.githubusercontent.com/luminati-io/"
    "Crunchbase-dataset-samples/main/crunchbase-companies-information.csv"
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
    key_people: Optional[str]
    raw: dict


def _ensure_sample() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PATH.exists() and SAMPLE_PATH.stat().st_size > 0:
        return SAMPLE_PATH
    log.info("Fetching Crunchbase ODM sample CSV from %s", SAMPLE_URL)
    r = httpx.get(SAMPLE_URL, timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    SAMPLE_PATH.write_bytes(r.content)
    log.info("Saved Crunchbase sample: %d bytes", len(r.content))
    return SAMPLE_PATH


_DOMAIN_RX = re.compile(r"^https?://(www\.)?", re.I)


def _clean_domain(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = _DOMAIN_RX.sub("", v.strip()).rstrip("/").split("/")[0]
    return v.lower() or None


def _coerce_year(v) -> Optional[int]:
    try:
        return int(str(v).strip()[:4]) if v else None
    except Exception:
        return None


def _coerce_float(v) -> Optional[float]:
    if v in (None, "", "null"):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except Exception:
        return None


def _coerce(row: dict) -> CrunchbaseRecord:
    name = (row.get("name") or row.get("Name") or row.get("company_name") or "").strip()
    domain = _clean_domain(
        row.get("website")
        or row.get("Website")
        or row.get("homepage_url")
        or row.get("url")
    )
    cb_id = (
        row.get("id")
        or row.get("uuid")
        or row.get("crunchbase_url")
        or row.get("permalink")
        or name.lower().replace(" ", "-")
    )
    return CrunchbaseRecord(
        crunchbase_id=str(cb_id).strip() or name.lower().replace(" ", "-"),
        name=name,
        domain=domain,
        industry=(row.get("industries") or row.get("industry") or row.get("category_groups_list")),
        employee_count=(row.get("num_employees") or row.get("employees") or row.get("employee_count")),
        country=(row.get("country_code") or row.get("country") or row.get("headquarters_country")),
        state=(row.get("region") or row.get("state_code") or row.get("headquarters_region")),
        founded_year=_coerce_year(row.get("founded_date") or row.get("founded_year")),
        total_funding_usd=_coerce_float(
            row.get("total_funding_usd") or row.get("total_funding") or row.get("funding_total_usd")
        ),
        last_funding_type=(row.get("last_funding_type") or row.get("last_round_type")),
        last_funding_at=(row.get("last_funding_at") or row.get("last_funding_on") or row.get("last_funding_date")),
        description=(row.get("short_description") or row.get("description") or row.get("about")),
        key_people=(row.get("founders") or row.get("founder_names") or row.get("key_employees")),
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
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        idx = cls()
        for row in reader:
            rec = _coerce(row)
            if not rec.name:
                continue
            idx.all.append(rec)
            if rec.domain:
                idx.by_domain[rec.domain] = rec
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
            hit = self.by_domain.get(_clean_domain(domain) or "")
            if hit:
                return hit
        if name:
            hit = self.by_name.get(name.lower())
            if hit:
                return hit
            needle = name.lower()
            for n, rec in self.by_name.items():
                if needle in n or n in needle:
                    return rec
        return None

    def peers(
        self,
        record: CrunchbaseRecord,
        *,
        max_n: int = 10,
    ) -> list[CrunchbaseRecord]:
        """Return up to max_n sector peers: same industry token, similar size."""
        if not record.industry:
            return []
        industry_toks = {t.strip().lower() for t in str(record.industry).split(",") if t.strip()}
        peers: list[CrunchbaseRecord] = []
        for rec in self.all:
            if rec.crunchbase_id == record.crunchbase_id or not rec.industry:
                continue
            toks = {t.strip().lower() for t in str(rec.industry).split(",") if t.strip()}
            if industry_toks & toks:
                peers.append(rec)
        # Sort peers: same employee band first, then by funding desc
        def band_match(r: CrunchbaseRecord) -> int:
            return 0 if r.employee_count == record.employee_count else 1
        peers.sort(
            key=lambda r: (
                band_match(r),
                -(r.total_funding_usd or 0),
            )
        )
        return peers[:max_n]


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
        "key_people": rec.key_people,
        "github_url": rec.raw.get("github_url") or rec.raw.get("github") or rec.raw.get("github_org"),
        "github_org": rec.raw.get("github_org") or rec.raw.get("github_handle"),
        "strategic_comms": rec.raw.get("tagline") or rec.raw.get("category_groups_list"),
        "source": "crunchbase_odm_sample",
    }
