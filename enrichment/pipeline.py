"""Unified enrichment pipeline for Tenacious prospects.

Runs:
  Crunchbase ODM -> firmographics
  layoffs.fyi     -> layoff events (120d)
  Job posts       -> open roles, AI role share, 60d velocity (if snapshot present)
  Leadership      -> new CTO / VP Eng (90d)
  AI maturity     -> 0-3 score with per-signal justification
  ICP classifier  -> ranked segment assignments
  Competitor gap  -> top-quartile peer practices the prospect lacks

Produces the two deliverable documents per the brief:
  - hiring_signal_brief.json  (merged firmographics + signals + maturity + ICP)
  - competitor_gap_brief.json (peers + gap practices)
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from enrichment.ai_maturity import ai_maturity_to_dict, score_ai_maturity
from enrichment.ai_signal_collection import (
    collect_exec_commentary_signal,
    collect_github_activity_signal,
    collect_modern_stack_signal,
    collect_strategic_comms_signal,
)
from enrichment.competitor_gap import build_competitor_gap_brief, competitor_gap_brief_to_dict
from enrichment.crunchbase import CrunchbaseIndex, build_enrichment_brief
from enrichment.icp import classify, icp_assignments_to_list
from enrichment.jobs import build_job_posts_signal_dict, fetch_job_posts_signal
from enrichment.layoffs import LayoffsIndex, build_layoffs_signal
from enrichment.leadership import build_leadership_signal_dict, fetch_leadership_signal

log = logging.getLogger(__name__)

_cb_index: Optional[CrunchbaseIndex] = None
_layoffs_index: Optional[LayoffsIndex] = None


def _crunchbase() -> CrunchbaseIndex:
    global _cb_index
    if _cb_index is None:
        _cb_index = CrunchbaseIndex.load()
    return _cb_index


def _layoffs() -> Optional[LayoffsIndex]:
    global _layoffs_index
    if _layoffs_index is None:
        try:
            _layoffs_index = LayoffsIndex.load()
        except Exception as e:
            log.warning("layoffs index unavailable: %s", e)
            _layoffs_index = LayoffsIndex()  # empty
    return _layoffs_index


def enrich(
    *,
    email: Optional[str] = None,
    domain: Optional[str] = None,
    company: Optional[str] = None,
    phone: Optional[str] = None,
    careers_url: Optional[str] = None,
    include_competitor_gap: bool = True,
) -> dict:
    cb = _crunchbase()
    rec = cb.lookup(email=email, domain=domain, name=company)
    if rec is None:
        return {
            "hiring_signal_brief": {
                "match": "no_crunchbase_hit",
                "email": email,
                "domain": domain,
                "company_hint": company,
                "phone": phone,
                "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            "competitor_gap_brief": None,
        }

    enrichment_brief = build_enrichment_brief(rec)
    resolved_company = rec.name

    # Signals
    jobs_signal = build_job_posts_signal_dict(
        fetch_job_posts_signal(resolved_company, careers_url=careers_url, mode="frozen")
    )
    layoffs_idx = _layoffs()
    layoffs_signal = build_layoffs_signal(resolved_company, layoffs_idx) if layoffs_idx else {}
    leadership_signal = build_leadership_signal_dict(fetch_leadership_signal(resolved_company))
    github_activity = collect_github_activity_signal(enrichment_brief)
    exec_commentary_signal = collect_exec_commentary_signal(enrichment_brief)
    modern_stack_signal = collect_modern_stack_signal(enrichment_brief)
    strategic_comms_signal = collect_strategic_comms_signal(enrichment_brief)

    ai_maturity = ai_maturity_to_dict(
        score_ai_maturity(
            enrichment_brief=enrichment_brief,
            jobs_signal=jobs_signal,
            github_activity=github_activity,
            exec_commentary=exec_commentary_signal.get("evidence"),
        )
    )

    icp = icp_assignments_to_list(classify(
        enrichment_brief=enrichment_brief,
        layoffs_signal=layoffs_signal,
        leadership_signal=leadership_signal,
        ai_maturity=ai_maturity,
    ))

    hiring_signal_brief = {
        "prospect": enrichment_brief,
        "funding_signal": {
            "last_funding_type": enrichment_brief.get("last_funding_type"),
            "last_funding_at": enrichment_brief.get("last_funding_at"),
            "total_funding_usd": enrichment_brief.get("total_funding_usd"),
            "confidence": "high" if enrichment_brief.get("last_funding_type") else "none",
            "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": "crunchbase_odm_sample",
        },
        "layoffs_signal": layoffs_signal,
        "jobs_signal": jobs_signal,
        "leadership_signal": leadership_signal,
        "github_activity_signal": github_activity,
        "exec_commentary_signal": exec_commentary_signal,
        "modern_stack_signal": modern_stack_signal,
        "strategic_comms_signal": strategic_comms_signal,
        "ai_maturity": ai_maturity,
        "icp_assignments": icp,
        "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    gap_brief = None
    if include_competitor_gap:
        try:
            gb = build_competitor_gap_brief(
                prospect_record=rec,
                prospect_jobs_signal=jobs_signal,
                index=cb,
            )
            gap_brief = competitor_gap_brief_to_dict(gb)
        except Exception as e:
            log.warning("competitor gap brief failed for %s: %s", resolved_company, e)

    return {
        "hiring_signal_brief": hiring_signal_brief,
        "competitor_gap_brief": gap_brief,
    }
