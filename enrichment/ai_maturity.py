"""AI maturity 0-3 scorer with per-signal justification + overall confidence.

The challenge asks for six input categories:
  High weight:
    - AI-adjacent open roles
    - named AI/ML leadership
  Medium weight:
    - public GitHub org activity
    - executive commentary about AI
  Low weight:
    - modern data / ML stack
    - strategic communications about AI posture

This module keeps those categories explicit, even when some inputs are absent
for a given prospect. A silent company should score 0 with an explicit note
that absence of public signal is not proof of absence.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

AI_LEADERSHIP_RX = re.compile(
    r"\b(chief\s?(ai|data|scientist)\s?officer|vp\s+(ai|data|ml)|head\s+of\s+(ai|ml|data))\b",
    re.I,
)
AI_STACK_RX = re.compile(
    r"\b(dbt|snowflake|databricks|weights\s?and\s?biases|wandb|ray|vllm|"
    r"pinecone|mlflow|airflow|kubeflow)\b",
    re.I,
)
AI_EXEC_COMMENT_RX = re.compile(
    r"\b(ai[-\s]?strateg(y|ic)|ai[-\s]?first|generative\s?ai|llm|llms|"
    r"foundation\s?model|agentic)\b",
    re.I,
)


@dataclass
class AIMaturityScore:
    score: int
    confidence: str
    ai_role_share: float
    signals: list[dict]
    silent_company_note: str
    retrieved_at: str


def _bucket(raw: float) -> int:
    return int(max(0, min(3, round(raw))))


def _blob_from_inputs(
    enrichment_brief: dict,
    news_items: Optional[list[dict]],
    exec_commentary: Optional[str],
) -> str:
    return " ".join(
        [str(enrichment_brief.get("description") or ""), exec_commentary or ""]
        + [item.get("title", "") + " " + item.get("snippet", "") for item in (news_items or [])]
    )


def _collect_ai_role_signal(jobs_signal: dict) -> Optional[dict]:
    ai_share = float(jobs_signal.get("ai_role_share") or 0.0)
    ai_count = int(jobs_signal.get("ai_roles_current") or 0)
    total_roles = int(jobs_signal.get("total_roles_current") or 0)
    if ai_count <= 0:
        return None
    contrib = min(1.5, ai_share * 4.0)
    return {
        "signal": "ai_role_share",
        "weight": "high",
        "evidence": f"{ai_count} AI-adjacent roles / {total_roles} total ({ai_share:.0%})",
        "contribution": round(contrib, 2),
    }


def _collect_named_ai_leadership_signal(enrichment_brief: dict) -> Optional[dict]:
    key_people = str(enrichment_brief.get("key_people") or "")
    description = str(enrichment_brief.get("description") or "")
    leader_hit = AI_LEADERSHIP_RX.search(key_people) or AI_LEADERSHIP_RX.search(description)
    if not leader_hit:
        return None
    return {
        "signal": "named_ai_leadership",
        "weight": "high",
        "evidence": leader_hit.group(0),
        "contribution": 1.0,
    }


def _collect_github_activity_signal(enrichment_brief: dict, github_activity: Optional[dict]) -> Optional[dict]:
    activity = github_activity or {}
    repo_count = activity.get("recent_repo_count")
    commit_count = activity.get("recent_commit_count")
    org = activity.get("org") or enrichment_brief.get("github_org") or enrichment_brief.get("github_url")
    if not (repo_count or commit_count or org):
        return None
    evidence_bits = []
    if org:
        evidence_bits.append(str(org))
    if repo_count:
        evidence_bits.append(f"recent repos={repo_count}")
    if commit_count:
        evidence_bits.append(f"recent commits={commit_count}")
    return {
        "signal": "github_org_activity",
        "weight": "medium",
        "evidence": ", ".join(evidence_bits) or "public GitHub org activity present",
        "contribution": 0.6,
    }


def _collect_exec_commentary_signal(blob: str) -> Optional[dict]:
    if not AI_EXEC_COMMENT_RX.search(blob):
        return None
    return {
        "signal": "exec_commentary",
        "weight": "medium",
        "evidence": "AI-strategic language present in description or news",
        "contribution": 0.6,
    }


def _collect_modern_stack_signal(blob: str) -> Optional[dict]:
    if not AI_STACK_RX.search(blob):
        return None
    return {
        "signal": "modern_ml_stack",
        "weight": "low",
        "evidence": "public mention of dbt/snowflake/databricks/vllm/etc.",
        "contribution": 0.3,
    }


def _collect_strategic_comms_signal(enrichment_brief: dict, blob: str) -> Optional[dict]:
    industry = str(enrichment_brief.get("industry") or "").lower()
    if any(t in industry for t in ("artificial intelligence", "machine learning", "data science")):
        return {
            "signal": "industry_taxonomy",
            "weight": "low",
            "evidence": f"industry contains AI/ML tokens: {enrichment_brief.get('industry')}",
            "contribution": 0.3,
        }
    if AI_EXEC_COMMENT_RX.search(blob):
        return {
            "signal": "strategic_comms",
            "weight": "low",
            "evidence": "strategic communications mention AI themes",
            "contribution": 0.3,
        }
    return None


def score_ai_maturity(
    *,
    enrichment_brief: dict,
    jobs_signal: dict,
    news_items: Optional[list[dict]] = None,
    exec_commentary: Optional[str] = None,
    github_activity: Optional[dict] = None,
) -> AIMaturityScore:
    """Return a 0-3 AI maturity score with per-signal evidence."""
    now = datetime.now(tz=timezone.utc).isoformat()
    ai_share = float(jobs_signal.get("ai_role_share") or 0.0)
    blob = _blob_from_inputs(enrichment_brief, news_items, exec_commentary)

    signals = [
        _collect_ai_role_signal(jobs_signal),
        _collect_named_ai_leadership_signal(enrichment_brief),
        _collect_github_activity_signal(enrichment_brief, github_activity),
        _collect_exec_commentary_signal(blob),
        _collect_modern_stack_signal(blob),
        _collect_strategic_comms_signal(enrichment_brief, blob),
    ]
    signals = [signal for signal in signals if signal]

    raw = sum(float(signal["contribution"]) for signal in signals)
    high_count = sum(1 for signal in signals if signal["weight"] == "high")
    med_count = sum(1 for signal in signals if signal["weight"] == "medium")
    low_count = sum(1 for signal in signals if signal["weight"] == "low")
    score = _bucket(raw)

    if high_count >= 2:
        conf = "high"
    elif high_count == 1:
        conf = "medium"
    elif med_count >= 2:
        conf = "medium"
    elif med_count + low_count >= 2:
        conf = "low"
    else:
        conf = "low"
    if score == 0:
        conf = "low"

    silent_company_note = ""
    if not signals:
        silent_company_note = "No public AI signal found; absence of public signal is not proof of absence."

    return AIMaturityScore(
        score=score,
        confidence=conf,
        ai_role_share=round(ai_share, 3),
        signals=signals,
        silent_company_note=silent_company_note,
        retrieved_at=now,
    )


def ai_maturity_to_dict(s: AIMaturityScore) -> dict:
    return {
        "score": s.score,
        "scale": "0-3",
        "confidence": s.confidence,
        "ai_role_share": s.ai_role_share,
        "signals": s.signals,
        "silent_company_note": s.silent_company_note,
        "retrieved_at": s.retrieved_at,
    }
