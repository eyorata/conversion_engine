"""layoffs.fyi parser.

The layoffs.fyi dataset is published as a structured CSV (mirrored on HuggingFace).
We fetch the CSV, index by normalized company name, and look up recent events.

Per the brief: a layoff in the last 120 days is signal for Segment 2
(mid-market restructuring) and disqualifies Segment 1 (recently funded).
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LAYOFFS_PATH = DATA_DIR / "layoffs.csv"
LAYOFFS_SEED = DATA_DIR / "layoffs_seed.csv"
# Community mirrors of layoffs.fyi; CC-BY. If both rotate, the committed
# layoffs_seed.csv is used as a honest fallback with the same schema.
LAYOFFS_URLS = [
    "https://raw.githubusercontent.com/aliceevewonderbread/layoffs-fyi-data/main/layoffs.csv",
    "https://huggingface.co/datasets/theSLWayne/layoffs-2020-to-now/resolve/main/layoffs.csv",
]


@dataclass
class LayoffEvent:
    company: str
    date: str
    headcount: Optional[int]
    percentage: Optional[float]
    source: Optional[str]


def _fetch_csv() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LAYOFFS_PATH.exists() and LAYOFFS_PATH.stat().st_size > 0:
        return LAYOFFS_PATH
    for url in LAYOFFS_URLS:
        try:
            r = httpx.get(url, timeout=60.0, follow_redirects=True)
            r.raise_for_status()
            LAYOFFS_PATH.write_bytes(r.content)
            log.info("Fetched layoffs.csv from %s (%d bytes)", url, len(r.content))
            return LAYOFFS_PATH
        except Exception as e:
            log.warning("layoffs fetch failed %s: %s", url, e)
    if LAYOFFS_SEED.exists():
        log.info("layoffs mirrors unavailable; using committed seed at %s", LAYOFFS_SEED)
        return LAYOFFS_SEED
    raise RuntimeError("could not fetch layoffs.csv and no seed present")


def _parse_int(v) -> Optional[int]:
    if v in (None, "", "null"):
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return None


def _parse_float(v) -> Optional[float]:
    if v in (None, "", "null"):
        return None
    try:
        s = str(v).replace("%", "").replace(",", "").strip()
        f = float(s)
        # normalize percentage to fraction (some datasets store 25 as 0.25 or 25.0)
        if f > 1.0:
            f = f / 100.0
        return f
    except Exception:
        return None


class LayoffsIndex:
    def __init__(self) -> None:
        self.by_name: dict[str, list[LayoffEvent]] = {}

    @classmethod
    def load(cls) -> "LayoffsIndex":
        path = _fetch_csv()
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        idx = cls()
        for row in reader:
            # Handle common column-name variants
            name = (
                row.get("company")
                or row.get("Company")
                or row.get("name")
                or ""
            ).strip()
            if not name:
                continue
            date = (
                row.get("date")
                or row.get("Date")
                or row.get("date_announced")
                or ""
            ).strip()
            headcount = _parse_int(
                row.get("total_laid_off")
                or row.get("Laid_Off")
                or row.get("laid_off")
                or row.get("headcount")
            )
            percentage = _parse_float(
                row.get("percentage")
                or row.get("percentage_laid_off")
                or row.get("Percentage")
            )
            src = (
                row.get("source")
                or row.get("Source")
                or row.get("url")
                or None
            )
            ev = LayoffEvent(company=name, date=date, headcount=headcount, percentage=percentage, source=src)
            idx.by_name.setdefault(name.lower(), []).append(ev)
        log.info("Loaded layoffs index: %d companies", len(idx.by_name))
        return idx

    def recent(self, company: str, *, within_days: int = 120) -> list[LayoffEvent]:
        events = self.by_name.get(company.lower(), [])
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=within_days)).date()
        out: list[LayoffEvent] = []
        for e in events:
            try:
                dt = datetime.strptime(e.date[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if dt >= cutoff:
                out.append(e)
        return sorted(out, key=lambda x: x.date, reverse=True)


def build_layoffs_signal(company: str, index: "LayoffsIndex") -> dict:
    events = index.recent(company, within_days=120)
    return {
        "company": company,
        "window_days": 120,
        "event_count": len(events),
        "events": [asdict(e) for e in events],
        "confidence": "high" if events else "none",
        "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": "layoffs.fyi_mirror",
    }
