"""Run all three enrichments in order and return the merged context for the agent."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Optional

from enrichment.cfpb import fetch_compliance_brief
from enrichment.crunchbase import CrunchbaseIndex, build_enrichment_brief
from enrichment.news import fetch_news_brief, news_brief_to_dict

log = logging.getLogger(__name__)

_cb_index: Optional[CrunchbaseIndex] = None


def _index() -> CrunchbaseIndex:
    global _cb_index
    if _cb_index is None:
        _cb_index = CrunchbaseIndex.load()
    return _cb_index


async def enrich(
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    domain: Optional[str] = None,
) -> dict:
    rec = _index().lookup(email=email, domain=domain, name=company)
    if rec is None:
        enrichment_brief = {
            "crunchbase_id": None,
            "match": "no_crunchbase_hit",
            "company": company,
            "domain": domain,
            "email": email,
            "phone": phone,
        }
        resolved_company = company or (domain.split(".")[0] if domain else None)
    else:
        enrichment_brief = build_enrichment_brief(rec)
        resolved_company = rec.name

    compliance_brief = {}
    news_brief = {}
    if resolved_company:
        compliance_brief = asdict(fetch_compliance_brief(resolved_company, window_days=180))
        news_brief = news_brief_to_dict(await fetch_news_brief(resolved_company))

    return {
        "enrichment_brief": enrichment_brief,
        "compliance_brief": compliance_brief,
        "news_brief": news_brief,
    }


def enrich_sync(**kwargs) -> dict:
    return asyncio.run(enrich(**kwargs))
