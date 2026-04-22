"""Tenacious outbound policy tests."""
from agent.policy import check_outbound


def _brief(
    jobs_total=0,
    jobs_conf="none",
    layoff_count=0,
    leadership_recent=False,
    funding_type=None,
):
    return {
        "jobs_signal": {
            "total_roles_current": jobs_total,
            "confidence": jobs_conf,
            "ai_role_share": 0.0,
        },
        "layoffs_signal": {"event_count": layoff_count, "confidence": "high" if layoff_count else "none"},
        "leadership_signal": {"recent_change": leadership_recent},
        "funding_signal": {"last_funding_type": funding_type, "last_funding_at": None, "total_funding_usd": None},
    }


def test_aggressive_hiring_blocked_with_low_signal():
    r = check_outbound(
        channel="email",
        subject="Capacity question",
        body="We saw your aggressive hiring over the last quarter and wanted to chat.",
        hiring_signal_brief=_brief(jobs_total=2, jobs_conf="low"),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("hiring_over_claim" in v for v in r.violations)


def test_aggressive_hiring_allowed_with_strong_signal():
    r = check_outbound(
        channel="email",
        subject="Capacity",
        body="Aggressive hiring in Q1 can outrun recruiting. 30 minutes?",
        hiring_signal_brief=_brief(jobs_total=12, jobs_conf="medium"),
        competitor_gap_brief=None,
    )
    assert r.ok is True


def test_funding_claim_blocked_without_funding_signal():
    r = check_outbound(
        channel="email",
        subject="Congrats on the raise",
        body="You raised a Series B — timing matters here.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("funding_over_claim" in v for v in r.violations)


def test_funding_claim_allowed_with_funding_signal():
    r = check_outbound(
        channel="email",
        subject="Post-Series-B capacity",
        body="With your Series B closing recently, staffing often lags.",
        hiring_signal_brief=_brief(funding_type="series_b"),
        competitor_gap_brief=None,
    )
    assert r.ok is True


def test_layoff_mention_blocked_without_event():
    r = check_outbound(
        channel="email",
        subject="",
        body="Post-layoff restructuring often creates a gap we can help cover.",
        hiring_signal_brief=_brief(layoff_count=0),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("layoff_over_claim" in v for v in r.violations)


def test_leadership_claim_blocked_without_event():
    r = check_outbound(
        channel="email",
        subject="",
        body="A new CTO usually reassesses vendors in 90 days.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("leadership_over_claim" in v for v in r.violations)


def test_capacity_commitment_always_blocked():
    r = check_outbound(
        channel="email",
        subject="Start Monday",
        body="We can deploy a team of 6 Python engineers starting next week.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("capacity_commitment" in v for v in r.violations)


def test_pricing_mention_blocked():
    r = check_outbound(
        channel="email",
        subject="",
        body="Our rate starts at $6k/month per engineer.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("pricing_mention" in v for v in r.violations)


def test_filler_phrase_blocked():
    r = check_outbound(
        channel="email",
        subject="Just checking in",
        body="Just checking in on our last thread.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert any("style_filler" in v for v in r.violations)


def test_gap_disparaging_peer_blocked():
    gap_brief = {
        "peers": [{"name": "PeerCorp", "ai_maturity": 3}],
        "gap_practices": [{"practice": "ai_role_share", "supporting_peer_count": 3, "supporting_peers": ["PeerCorp"]}],
    }
    r = check_outbound(
        channel="email",
        subject="Sector gap",
        body="PeerCorp is crushing you on AI hiring — time to catch up.",
        hiring_signal_brief=_brief(),
        competitor_gap_brief=gap_brief,
    )
    assert r.ok is False
    assert any("gap_disparaging" in v for v in r.violations)


def test_long_email_blocked():
    r = check_outbound(
        channel="email",
        subject="ok",
        body="x" * 2100,
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert "email_body_too_long" in r.violations


def test_sms_too_long_blocked():
    r = check_outbound(
        channel="sms",
        subject=None,
        body="x" * 400,
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is False
    assert "sms_too_long" in r.violations


def test_clean_email_passes():
    r = check_outbound(
        channel="email",
        subject="Research note on your engineering posture",
        body=(
            "Hi — 30 minutes this week to hear how you're thinking about engineering "
            "capacity through Q3? No pitch in the first call."
        ),
        hiring_signal_brief=_brief(),
        competitor_gap_brief=None,
    )
    assert r.ok is True
    assert r.violations == []
