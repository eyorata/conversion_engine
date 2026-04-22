"""ICP classifier + competitor-gap shape tests."""
from datetime import datetime, timedelta, timezone

from enrichment.icp import classify


def _brief_funded_recent():
    return {"last_funding_type": "series b", "last_funding_at": (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), "total_funding_usd": 12_000_000, "employee_count": "51-100"}


def _jobs(ai=0, total=0, conf="none"):
    return {"ai_roles_current": ai, "total_roles_current": total, "ai_role_share": (ai/total if total else 0.0), "confidence": conf}


def test_segment_1_recent_funding_series_b():
    assignments = classify(
        enrichment_brief=_brief_funded_recent(),
        layoffs_signal={"event_count": 0},
        leadership_signal={"recent_change": False},
        ai_maturity={"score": 1, "confidence": "low"},
    )
    names = [a["name"] for a in [a.__dict__ for a in assignments]]
    assert "recently_funded_series_ab" in names


def test_segment_2_layoffs_and_size():
    assignments = classify(
        enrichment_brief={"last_funding_type": None, "employee_count": "501-1000"},
        layoffs_signal={"event_count": 1},
        leadership_signal={"recent_change": False},
        ai_maturity={"score": 0, "confidence": "low"},
    )
    names = [a.name for a in assignments]
    assert "mid_market_restructuring" in names


def test_segment_3_leadership_recent():
    assignments = classify(
        enrichment_brief={"last_funding_type": None},
        layoffs_signal={"event_count": 0},
        leadership_signal={"recent_change": True, "role": "VP Engineering", "days_ago": 30, "source_url": "x"},
        ai_maturity={"score": 0, "confidence": "low"},
    )
    names = [a.name for a in assignments]
    assert "leadership_transition" in names


def test_segment_4_gated_by_ai_maturity():
    # Score 2 with medium confidence -> should qualify
    assignments = classify(
        enrichment_brief={"last_funding_type": None},
        layoffs_signal={"event_count": 0},
        leadership_signal={"recent_change": False},
        ai_maturity={"score": 2, "confidence": "medium"},
    )
    names = [a.name for a in assignments]
    assert "specialized_capability_gap" in names


def test_segment_4_low_confidence_still_emits_but_soft():
    assignments = classify(
        enrichment_brief={"last_funding_type": None},
        layoffs_signal={"event_count": 0},
        leadership_signal={"recent_change": False},
        ai_maturity={"score": 2, "confidence": "low"},
    )
    a4 = [a for a in assignments if a.name == "specialized_capability_gap"]
    assert a4 and a4[0].confidence == "low"


def test_no_signal_returns_empty():
    assignments = classify(
        enrichment_brief={"last_funding_type": None},
        layoffs_signal={"event_count": 0},
        leadership_signal={"recent_change": False},
        ai_maturity={"score": 0, "confidence": "low"},
    )
    assert assignments == []
