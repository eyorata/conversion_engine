"""AI maturity 0-3 scorer with per-signal justification + overall confidence.

Weights from the brief:
  High weight: AI-adjacent open roles (fraction of eng openings), named AI/ML leadership
  Medium weight: public GitHub org activity, executive commentary on AI
  Low weight: modern ML stack signal, strategic-comms mention

This scorer runs on whatever subset of signals is available and is honest about
its confidence. A score of 2 from one medium signal should NOT be phrased the
same way as a 2 from multiple high-weight signals.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# Keyword hits in description / news / key_people imply AI/ML strategic posture.
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
    score: int               # 0..3
    confidence: str          # "low" | "medium" | "high"
    ai_role_share: float     # fraction from job posts
    signals: list[dict]      # [{signal, weight, evidence, contribution}, ...]
    retrieved_at: str


def _bucket(raw: float) -> int:
    # raw is 0..3 weighted aggregate; clamp then round.
    return int(max(0, min(3, round(raw))))


def score_ai_maturity(
    *,
    enrichment_brief: dict,
    jobs_signal: dict,
    news_items: Optional[list[dict]] = None,
    exec_commentary: Optional[str] = None,
) -> AIMaturityScore:
    """Return a 0-3 AI maturity score with per-signal evidence.

    Deliberately conservative: "high" confidence requires at least two high-weight
    inputs; one medium + one low is "low" confidence even if score hits 2.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    signals: list[dict] = []
    raw = 0.0
    high_count = 0
    med_count = 0
    low_count = 0

    # High: AI-adjacent open-role share
    ai_share = float(jobs_signal.get("ai_role_share") or 0.0)
    ai_count = int(jobs_signal.get("ai_roles_current") or 0)
    if ai_count > 0:
        contrib = min(1.5, ai_share * 4.0)  # 25% share -> +1.0, capped at +1.5
        raw += contrib
        high_count += 1
        signals.append({
            "signal": "ai_role_share",
            "weight": "high",
            "evidence": f"{ai_count} AI-adjacent roles / {jobs_signal.get('total_roles_current', 0)} total ({ai_share:.0%})",
            "contribution": round(contrib, 2),
        })

    # High: named AI/ML leadership from key_people or enrichment description
    key_people = str(enrichment_brief.get("key_people") or "")
    description = str(enrichment_brief.get("description") or "")
    leader_hit = AI_LEADERSHIP_RX.search(key_people) or AI_LEADERSHIP_RX.search(description)
    if leader_hit:
        raw += 1.0
        high_count += 1
        signals.append({
            "signal": "named_ai_leadership",
            "weight": "high",
            "evidence": leader_hit.group(0),
            "contribution": 1.0,
        })

    # Medium: exec commentary / news mentions AI
    blob = " ".join(
        [description, exec_commentary or ""]
        + [item.get("title", "") + " " + item.get("snippet", "") for item in (news_items or [])]
    )
    if AI_EXEC_COMMENT_RX.search(blob):
        raw += 0.6
        med_count += 1
        signals.append({
            "signal": "exec_commentary",
            "weight": "medium",
            "evidence": "AI-strategic language present in description or news",
            "contribution": 0.6,
        })

    # Low: modern ML/data stack signal
    if AI_STACK_RX.search(blob):
        raw += 0.3
        low_count += 1
        signals.append({
            "signal": "modern_ml_stack",
            "weight": "low",
            "evidence": "public mention of dbt/snowflake/databricks/vllm/etc.",
            "contribution": 0.3,
        })

    # Low: strategic-comms industry mention (inferred from industry taxonomy)
    industry = str(enrichment_brief.get("industry") or "").lower()
    if any(t in industry for t in ("artificial intelligence", "machine learning", "data science")):
        raw += 0.3
        low_count += 1
        signals.append({
            "signal": "industry_taxonomy",
            "weight": "low",
            "evidence": f"industry contains AI/ML tokens: {enrichment_brief.get('industry')}",
            "contribution": 0.3,
        })

    score = _bucket(raw)

    if high_count >= 2:
        conf = "high"
    elif high_count == 1 and (med_count + low_count) >= 1:
        conf = "medium"
    elif high_count == 1:
        conf = "medium"
    elif med_count + low_count >= 2:
        conf = "low"
    else:
        conf = "low"
    if score == 0:
        conf = "low"

    return AIMaturityScore(
        score=score,
        confidence=conf,
        ai_role_share=round(ai_share, 3),
        signals=signals,
        retrieved_at=now,
    )


def ai_maturity_to_dict(s: AIMaturityScore) -> dict:
    return {
        "score": s.score,
        "scale": "0-3",
        "confidence": s.confidence,
        "ai_role_share": s.ai_role_share,
        "signals": s.signals,
        "retrieved_at": s.retrieved_at,
    }
