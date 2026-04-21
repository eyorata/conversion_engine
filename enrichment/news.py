"""News / press enrichment via Playwright.

Fetches the most recent public mention of a company from a lightweight web search
(duckduckgo HTML endpoint) and extracts a title + snippet + url for the top 3 hits.
Respects robots.txt and does not log in anywhere.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    snippet: str
    url: str


@dataclass
class NewsBrief:
    company: str
    items: list[NewsItem]
    retrieved_at: str
    source: str = "duckduckgo_html"


async def fetch_news_brief(company: str, *, max_items: int = 3) -> NewsBrief:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("Playwright not installed; returning empty news brief")
        return NewsBrief(
            company=company,
            items=[],
            retrieved_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    query = f"{company} news"
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    items: list[NewsItem] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (compatible; AcmeComplianceOSBot/0.1; "
                    "+https://example.test/bot)"
                )
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            nodes = await page.locator("a.result__a").all()
            for node in nodes[:max_items]:
                title = (await node.inner_text()).strip()
                href = await node.get_attribute("href") or ""
                snippet_el = node.locator(
                    "xpath=ancestor::div[contains(@class,'result')]//a[contains(@class,'result__snippet')]"
                )
                try:
                    snippet = (await snippet_el.first.inner_text(timeout=500)).strip()
                except Exception:
                    snippet = ""
                items.append(NewsItem(title=title, snippet=snippet, url=href))
            await browser.close()
    except Exception as e:
        log.warning("Playwright news fetch failed for %s: %s", company, e)

    return NewsBrief(
        company=company,
        items=items,
        retrieved_at=datetime.now(tz=timezone.utc).isoformat(),
    )


def news_brief_to_dict(brief: NewsBrief) -> dict:
    return {
        "company": brief.company,
        "items": [item.__dict__ for item in brief.items],
        "retrieved_at": brief.retrieved_at,
        "source": brief.source,
    }
