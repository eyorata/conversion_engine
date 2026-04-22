"""Competitor gap brief.

For a prospect, identify 5-10 peers in the same sector and employee-size band,
score them on AI maturity, rank them, extract top-quartile practices the prospect
does NOT show public signal for.

Per brief: the value proposition shifts from "Tenacious offers X" to
"three companies in your sector are doing X and you are not".

Honesty constraint: we only name a gap when (a) the peer clearly shows the
signal and (b) the prospect clearly does not. Ambiguous cases become "ask"
framing, not "assert" framing.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from enrichment.ai_maturity import score_ai_maturity
from enrichment.crunchbase import CrunchbaseIndex, CrunchbaseRecord, build_enrichment_brief
from enrichment.jobs import build_job_posts_signal_dict, fetch_job_posts_signal

log = logging.getLogger(__name__)


@dataclass
class PeerProfile:
    crunchbase_id: str
    name: str
    ai_maturity: int
    ai_role_share: float
    total_funding_usd: Optional[float]
    signals: list[dict]


@dataclass
class CompetitorGapBrief:
    prospect_company: str
    prospect_ai_maturity: int
    prospect_quartile: Optional[int]     # 1 = top quartile, 4 = bottom
    sector: Optional[str]
    peer_count: int
    peers: list[PeerProfile]
    top_quartile_ai_maturity_min: Optional[int]
    gap_practices: list[dict]   # [{practice: str, supporting_peers: [name], confidence: str}, ...]
    retrieved_at: str


def _score_peer(
    rec: CrunchbaseRecord,
    jobs_signal: dict,
) -> PeerProfile:
    score = score_ai_maturity(
        enrichment_brief=build_enrichment_brief(rec),
        jobs_signal=jobs_signal,
    )
    return PeerProfile(
        crunchbase_id=rec.crunchbase_id,
        name=rec.name,
        ai_maturity=score.score,
        ai_role_share=score.ai_role_share,
        total_funding_usd=rec.total_funding_usd,
        signals=score.signals,
    )


def _gap_practices(
    prospect: PeerProfile,
    top_peers: list[PeerProfile],
) -> list[dict]:
    """Extract practices the top-quartile peers show signal for that the prospect does not."""
    prospect_sig_names = {s["signal"] for s in prospect.signals}
    practice_map: dict[str, list[str]] = {}
    for peer in top_peers:
        for s in peer.signals:
            if s["signal"] in prospect_sig_names:
                continue
            practice_map.setdefault(s["signal"], []).append(peer.name)
    gaps: list[dict] = []
    for practice, supporters in practice_map.items():
        if len(supporters) < 2:
            continue  # require at least 2 peers to avoid one-off anecdote
        confidence = "high" if len(supporters) >= 3 else "medium"
        gaps.append({
            "practice": practice,
            "supporting_peers": supporters[:5],
            "supporting_peer_count": len(supporters),
            "confidence": confidence,
        })
    gaps.sort(key=lambda g: (-g["supporting_peer_count"], g["practice"]))
    return gaps[:3]


def build_competitor_gap_brief(
    *,
    prospect_record: CrunchbaseRecord,
    prospect_jobs_signal: dict,
    index: CrunchbaseIndex,
    max_peers: int = 10,
) -> CompetitorGapBrief:
    now = datetime.now(tz=timezone.utc).isoformat()
    peers_records = index.peers(prospect_record, max_n=max_peers)
    if not peers_records:
        log.info("no peers found for %s", prospect_record.name)
        prospect_profile = _score_peer(prospect_record, prospect_jobs_signal)
        return CompetitorGapBrief(
            prospect_company=prospect_record.name,
            prospect_ai_maturity=prospect_profile.ai_maturity,
            prospect_quartile=None,
            sector=prospect_record.industry,
            peer_count=0,
            peers=[],
            top_quartile_ai_maturity_min=None,
            gap_practices=[],
            retrieved_at=now,
        )

    # Score prospect and peers with the SAME jobs signal placeholder for peers
    # (we only have the prospect's live jobs data during a single run; for peers we use
    # a nil jobs signal which means peer AI maturity derives from enrichment alone).
    peer_nil_jobs = {"ai_role_share": 0.0, "ai_roles_current": 0, "total_roles_current": 0}
    prospect_profile = _score_peer(prospect_record, prospect_jobs_signal)
    peer_profiles = [_score_peer(r, peer_nil_jobs) for r in peers_records]

    all_scores = sorted([p.ai_maturity for p in peer_profiles] + [prospect_profile.ai_maturity])
    # Quartile: 1 = top 25% by AI maturity. Small peer set -> approximate.
    n = len(all_scores)
    if n == 0:
        quartile = None
        tq_min = None
    else:
        tq_cutoff_idx = max(0, int(0.75 * n))
        tq_min = all_scores[tq_cutoff_idx]
        if prospect_profile.ai_maturity >= tq_min:
            quartile = 1
        elif prospect_profile.ai_maturity >= statistics.median(all_scores):
            quartile = 2
        elif prospect_profile.ai_maturity > 0:
            quartile = 3
        else:
            quartile = 4

    top_peers = [p for p in peer_profiles if p.ai_maturity >= (tq_min or 99)]
    gaps = _gap_practices(prospect_profile, top_peers) if top_peers else []

    return CompetitorGapBrief(
        prospect_company=prospect_record.name,
        prospect_ai_maturity=prospect_profile.ai_maturity,
        prospect_quartile=quartile,
        sector=prospect_record.industry,
        peer_count=len(peer_profiles),
        peers=peer_profiles,
        top_quartile_ai_maturity_min=tq_min,
        gap_practices=gaps,
        retrieved_at=now,
    )


def competitor_gap_brief_to_dict(b: CompetitorGapBrief) -> dict:
    return {
        "prospect_company": b.prospect_company,
        "prospect_ai_maturity": b.prospect_ai_maturity,
        "prospect_quartile": b.prospect_quartile,
        "sector": b.sector,
        "peer_count": b.peer_count,
        "peers": [
            {
                "name": p.name,
                "crunchbase_id": p.crunchbase_id,
                "ai_maturity": p.ai_maturity,
                "ai_role_share": p.ai_role_share,
                "total_funding_usd": p.total_funding_usd,
            }
            for p in b.peers
        ],
        "top_quartile_ai_maturity_min": b.top_quartile_ai_maturity_min,
        "gap_practices": b.gap_practices,
        "retrieved_at": b.retrieved_at,
        "source": "crunchbase_odm_sample+derived",
    }
