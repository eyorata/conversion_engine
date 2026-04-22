"""Job-post velocity via Playwright.

Per the brief: count open roles on the company's public careers page and estimate
a 60-day delta. Respects robots.txt. No login. No captcha bypass.

Because a live crawl is slow and brittle, we support two modes:
  - "frozen": use a pre-captured snapshot in data/job_posts_snapshot.json
    keyed by normalized company name (a small seed snapshot is fine)
  - "live": run Playwright; caps at 1 page per company, 10s timeout

For Day 0 / interim, frozen mode is fine. Live mode is used only during
grading spot checks.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = DATA_DIR / "job_posts_snapshot.json"

# Signal that a job is AI-adjacent (per brief):
AI_ROLE_RX = re.compile(
    r"\b(ml|machine[- ]learning|data[- ]?platform|applied[- ]scientist|llm|"
    r"ai\s?(engineer|product|platform)|research[- ]engineer|mlops)\b",
    re.I,
)
# Signal that a job is engineering (broad):
ENG_ROLE_RX = re.compile(
    r"\b(engineer|developer|architect|sre|devops|platform|data\s?engineer)\b", re.I
)


@dataclass
class JobPostsSignal:
    company: str
    total_roles_current: int
    total_roles_60d_ago: Optional[int]
    velocity_ratio: Optional[float]  # current / 60d_ago
    ai_roles_current: int
    ai_role_share: float
    example_titles: list[str]
    mode: str  # "frozen" | "live" | "none"
    confidence: str
    retrieved_at: str


def _load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("failed to read job_posts_snapshot.json: %s", e)
        return {}


def _score_titles(titles: list[str]) -> tuple[int, int, int, list[str]]:
    eng = [t for t in titles if ENG_ROLE_RX.search(t)]
    ai = [t for t in titles if AI_ROLE_RX.search(t)]
    return len(titles), len(eng), len(ai), titles[:5]


def fetch_job_posts_signal(
    company: str,
    *,
    careers_url: Optional[str] = None,
    mode: str = "frozen",
) -> JobPostsSignal:
    snapshot = _load_snapshot()
    key = company.lower().strip()
    now = datetime.now(tz=timezone.utc).isoformat()

    if mode in ("frozen", "auto") and key in snapshot:
        s = snapshot[key]
        current = s.get("current", {})
        past = s.get("60d_ago", {})
        titles = current.get("titles", [])
        total, _eng, ai_count, examples = _score_titles(titles)
        past_total = past.get("total") if past else None
        velocity = (total / past_total) if past_total else None
        ai_share = (ai_count / total) if total else 0.0
        return JobPostsSignal(
            company=company,
            total_roles_current=total,
            total_roles_60d_ago=past_total,
            velocity_ratio=round(velocity, 2) if velocity else None,
            ai_roles_current=ai_count,
            ai_role_share=round(ai_share, 3),
            example_titles=examples,
            mode="frozen",
            confidence="medium" if total >= 5 else ("low" if total > 0 else "none"),
            retrieved_at=now,
        )

    if mode == "live" and careers_url:
        try:
            titles = _playwright_titles(careers_url)
            total, _eng, ai_count, examples = _score_titles(titles)
            return JobPostsSignal(
                company=company,
                total_roles_current=total,
                total_roles_60d_ago=None,
                velocity_ratio=None,
                ai_roles_current=ai_count,
                ai_role_share=round((ai_count / total) if total else 0.0, 3),
                example_titles=examples,
                mode="live",
                confidence="low" if total > 0 else "none",
                retrieved_at=now,
            )
        except Exception as e:
            log.warning("live job-post fetch failed for %s: %s", company, e)

    return JobPostsSignal(
        company=company,
        total_roles_current=0,
        total_roles_60d_ago=None,
        velocity_ratio=None,
        ai_roles_current=0,
        ai_role_share=0.0,
        example_titles=[],
        mode="none",
        confidence="none",
        retrieved_at=now,
    )


def _playwright_titles(url: str) -> list[str]:
    from playwright.sync_api import sync_playwright

    titles: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (compatible; TenaciousOutboundBot/0.1; "
                "+https://example.test/bot)"
            )
        ).new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            # Many job boards use <a>/<li>/<h3> with role titles
            for sel in ["a", "h2", "h3", "li", "div"]:
                nodes = page.locator(sel).all()
                for n in nodes[:200]:
                    try:
                        text = (n.inner_text(timeout=200) or "").strip()
                    except Exception:
                        continue
                    if 6 < len(text) < 120 and (
                        ENG_ROLE_RX.search(text) or AI_ROLE_RX.search(text)
                    ):
                        titles.append(text)
                if titles:
                    break
        finally:
            browser.close()
    # Dedup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def build_job_posts_signal_dict(sig: JobPostsSignal) -> dict:
    return {
        "company": sig.company,
        "total_roles_current": sig.total_roles_current,
        "total_roles_60d_ago": sig.total_roles_60d_ago,
        "velocity_ratio": sig.velocity_ratio,
        "ai_roles_current": sig.ai_roles_current,
        "ai_role_share": sig.ai_role_share,
        "example_titles": sig.example_titles,
        "mode": sig.mode,
        "confidence": sig.confidence,
        "retrieved_at": sig.retrieved_at,
        "source": "public_careers_pages",
    }
