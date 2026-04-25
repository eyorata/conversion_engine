"""Collection helpers for AI-maturity inputs.

These functions gather or derive the six input categories the challenge asks
for before the weighted scoring step in `ai_maturity.py`.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

GITHUB_ACTIVITY_RX = re.compile(r'(\d[\d,]*)\s+commits?|\b(\d[\d,]*)\s+repos?\b', re.I)
EXEC_COMMENTARY_RX = re.compile(r"\b(ai[-\s]?strateg(y|ic)|ai[-\s]?first|generative\s?ai|llm|agentic)\b", re.I)
STACK_RX = re.compile(
    r"\b(dbt|snowflake|databricks|weights\s?and\s?biases|wandb|ray|vllm|pinecone|mlflow|airflow|kubeflow)\b",
    re.I,
)


def collect_github_activity_signal(enrichment_brief: dict) -> dict:
    """Collect a lightweight public GitHub signal from the org URL if present."""
    org_url = enrichment_brief.get("github_url") or enrichment_brief.get("github_org")
    result = {
        "org": org_url,
        "recent_repo_count": None,
        "recent_commit_count": None,
        "confidence": "none",
        "source": "public_github",
    }
    if not org_url:
        return result

    url = str(org_url)
    if "github.com" not in url:
        url = f"https://github.com/{url.lstrip('@')}"

    try:
        r = httpx.get(url, timeout=10.0, follow_redirects=True)
        if r.status_code >= 400:
            return result
        text = r.text[:250000]
        matches = GITHUB_ACTIVITY_RX.findall(text)
        nums = []
        for commit_count, repo_count in matches:
            val = commit_count or repo_count
            if val:
                try:
                    nums.append(int(val.replace(",", "")))
                except Exception:
                    continue
        if nums:
            # This is intentionally coarse: the point is to capture visible public
            # activity, not precise analytics.
            result["recent_repo_count"] = max((n for n in nums if n < 10000), default=None)
            result["recent_commit_count"] = max((n for n in nums if n >= 10000), default=None)
            result["confidence"] = "medium"
    except Exception as e:
        log.warning("github activity collection failed for %s: %s", url, e)
    return result


def collect_exec_commentary_signal(enrichment_brief: dict, news_items: Optional[list[dict]] = None) -> dict:
    description = str(enrichment_brief.get("description") or "")
    snippets = " ".join(item.get("title", "") + " " + item.get("snippet", "") for item in (news_items or []))
    blob = " ".join([description, snippets])
    hit = EXEC_COMMENTARY_RX.search(blob)
    return {
        "present": bool(hit),
        "evidence": hit.group(0) if hit else None,
        "confidence": "medium" if hit else "none",
        "source": "public_description_and_news",
    }


def collect_modern_stack_signal(enrichment_brief: dict, news_items: Optional[list[dict]] = None) -> dict:
    description = str(enrichment_brief.get("description") or "")
    strategic = str(enrichment_brief.get("strategic_comms") or "")
    snippets = " ".join(item.get("title", "") + " " + item.get("snippet", "") for item in (news_items or []))
    blob = " ".join([description, strategic, snippets])
    hits = sorted(set(match.group(0) for match in STACK_RX.finditer(blob)))
    return {
        "present": bool(hits),
        "evidence": hits,
        "confidence": "low" if hits else "none",
        "source": "public_description_and_comms",
    }


def collect_strategic_comms_signal(enrichment_brief: dict, news_items: Optional[list[dict]] = None) -> dict:
    strategic = str(enrichment_brief.get("strategic_comms") or "")
    industry = str(enrichment_brief.get("industry") or "")
    snippets = " ".join(item.get("title", "") + " " + item.get("snippet", "") for item in (news_items or []))
    blob = " ".join([strategic, industry, snippets])
    hit = EXEC_COMMENTARY_RX.search(blob)
    return {
        "present": bool(hit),
        "evidence": hit.group(0) if hit else (industry if industry else None),
        "confidence": "low" if (hit or industry) else "none",
        "source": "public_industry_and_comms",
    }
