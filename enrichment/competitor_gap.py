"""Competitor gap brief.

For a prospect, identify 5-10 peers in the same sector and employee-size band,
score them on AI maturity, rank them, and extract top-quartile practices the
prospect does not show public signal for.

Selection criteria are deterministic and documented here because this file is
part of the deliverable:
  - same industry token overlap as the prospect
  - similar employee band when available
  - highest-funded peers first within that slice
  - return up to 10 peers
  - mark `sparse_sector=True` when fewer than 5 viable peers are found
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from enrichment.ai_maturity import score_ai_maturity
from enrichment.ai_signal_collection import collect_exec_commentary_signal, collect_github_activity_signal
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
    prospect_quartile: Optional[int]
    distribution_position: Optional[dict]
    sector: Optional[str]
    peer_count: int
    sparse_sector: bool
    selection_criteria: list[str]
    peers: list[PeerProfile]
    top_quartile_ai_maturity_min: Optional[int]
    gap_practices: list[dict]
    retrieved_at: str


def _score_peer(rec: CrunchbaseRecord, jobs_signal: dict) -> PeerProfile:
    brief = build_enrichment_brief(rec)
    score = score_ai_maturity(
        enrichment_brief=brief,
        jobs_signal=jobs_signal,
        github_activity=collect_github_activity_signal(brief),
        exec_commentary=collect_exec_commentary_signal(brief).get("evidence"),
    )
    return PeerProfile(
        crunchbase_id=rec.crunchbase_id,
        name=rec.name,
        ai_maturity=score.score,
        ai_role_share=score.ai_role_share,
        total_funding_usd=rec.total_funding_usd,
        signals=score.signals,
    )


def _gap_practices(prospect: PeerProfile, top_peers: list[PeerProfile]) -> list[dict]:
    prospect_sig_names = {signal["signal"] for signal in prospect.signals}
    practice_map: dict[str, list[str]] = {}
    evidence_map: dict[str, list[dict]] = {}
    for peer in top_peers:
        for signal in peer.signals:
            if signal["signal"] in prospect_sig_names:
                continue
            practice_map.setdefault(signal["signal"], []).append(peer.name)
            evidence_map.setdefault(signal["signal"], []).append(
                {
                    "peer": peer.name,
                    "signal": signal["signal"],
                    "weight": signal["weight"],
                    "evidence": signal["evidence"],
                }
            )

    gaps: list[dict] = []
    for practice, supporters in practice_map.items():
        if len(supporters) < 2:
            continue
        confidence = "high" if len(supporters) >= 3 else "medium"
        gaps.append(
            {
                "practice": practice,
                "supporting_peers": supporters[:5],
                "supporting_peer_count": len(supporters),
                "confidence": confidence,
                "evidence": evidence_map.get(practice, [])[:5],
            }
        )
    gaps.sort(key=lambda gap: (-gap["supporting_peer_count"], gap["practice"]))
    return gaps[:3]


def build_competitor_gap_brief(
    *,
    prospect_record: CrunchbaseRecord,
    prospect_jobs_signal: dict,
    index: CrunchbaseIndex,
    max_peers: int = 10,
) -> CompetitorGapBrief:
    now = datetime.now(tz=timezone.utc).isoformat()
    criteria = [
        "same industry token overlap",
        "same employee band preferred",
        "highest funding within peer slice",
    ]
    peers_records = index.peers(prospect_record, max_n=max_peers)
    prospect_profile = _score_peer(prospect_record, prospect_jobs_signal)

    if not peers_records:
        log.info("no peers found for %s", prospect_record.name)
        return CompetitorGapBrief(
            prospect_company=prospect_record.name,
            prospect_ai_maturity=prospect_profile.ai_maturity,
            prospect_quartile=None,
            distribution_position=None,
            sector=prospect_record.industry,
            peer_count=0,
            sparse_sector=True,
            selection_criteria=criteria,
            peers=[],
            top_quartile_ai_maturity_min=None,
            gap_practices=[],
            retrieved_at=now,
        )

    peer_profiles = []
    for record in peers_records:
        peer_jobs_signal = build_job_posts_signal_dict(fetch_job_posts_signal(record.name, mode="frozen"))
        peer_profiles.append(_score_peer(record, peer_jobs_signal))

    all_scores = sorted([peer.ai_maturity for peer in peer_profiles] + [prospect_profile.ai_maturity])
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

    top_peers = [peer for peer in peer_profiles if peer.ai_maturity >= (tq_min or 99)]
    gaps = _gap_practices(prospect_profile, top_peers) if top_peers else []

    return CompetitorGapBrief(
        prospect_company=prospect_record.name,
        prospect_ai_maturity=prospect_profile.ai_maturity,
        prospect_quartile=quartile,
        distribution_position={
            "quartile": quartile,
            "score": prospect_profile.ai_maturity,
            "peer_scores": sorted(peer.ai_maturity for peer in peer_profiles),
        },
        sector=prospect_record.industry,
        peer_count=len(peer_profiles),
        sparse_sector=len(peer_profiles) < 5,
        selection_criteria=criteria,
        peers=peer_profiles,
        top_quartile_ai_maturity_min=tq_min,
        gap_practices=gaps,
        retrieved_at=now,
    )


def competitor_gap_brief_to_dict(brief: CompetitorGapBrief) -> dict:
    return {
        "prospect_company": brief.prospect_company,
        "prospect_ai_maturity": brief.prospect_ai_maturity,
        "prospect_quartile": brief.prospect_quartile,
        "distribution_position": brief.distribution_position,
        "sector": brief.sector,
        "peer_count": brief.peer_count,
        "sparse_sector": brief.sparse_sector,
        "selection_criteria": brief.selection_criteria,
        "peers": [
            {
                "name": peer.name,
                "crunchbase_id": peer.crunchbase_id,
                "ai_maturity": peer.ai_maturity,
                "ai_role_share": peer.ai_role_share,
                "total_funding_usd": peer.total_funding_usd,
                "signals": peer.signals,
            }
            for peer in brief.peers
        ],
        "top_quartile_ai_maturity_min": brief.top_quartile_ai_maturity_min,
        "gap_practices": brief.gap_practices,
        "retrieved_at": brief.retrieved_at,
        "source": "crunchbase_odm_sample+derived",
    }
