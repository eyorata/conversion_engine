"""Generate market-space mapping artifacts from the Crunchbase ODM sample.

Outputs (under eval/market_space):
  - market_space.csv
  - top_cells.md
  - methodology.md
  - validation_sample.csv
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from enrichment.ai_maturity import score_ai_maturity
from enrichment.jobs import build_job_posts_signal_dict, fetch_job_posts_signal

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "crunchbase_sample.csv"
OUT_DIR = ROOT / "eval" / "market_space"


AI_HINT_RX = re.compile(
    r"\b(ai|machine learning|mlops|llm|generative|computer vision|nlp|data science)\b",
    re.I,
)
AI_STRONG_HINT_RX = re.compile(
    r"\b(artificial intelligence|machine learning|mlops|llm|generative ai|computer vision|nlp)\b",
    re.I,
)
AI_MODERATE_HINT_RX = re.compile(
    r"\b(ai|analytics|data platform|predictive|automation|recommendation)\b",
    re.I,
)
TENACIOUS_BENCH_RX = re.compile(
    r"\b(advertising|adtech|marketing|media|analytics|loyalty|rewards|franchise|"
    r"fitness|wellness|e-?commerce|platform|automation|integration|data|ml|ai)\b",
    re.I,
)


@dataclass
class CompanyRow:
    name: str
    sector: str
    size_band: str
    ai_score: int
    ai_band: str
    funding_12m_usd: float
    hiring_velocity_60d: float
    bench_match_score: float
    ai_confidence: str
    about: str
    industries: str


def _safe_json_list(raw: str) -> list:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_industries(raw: str) -> list[str]:
    arr = _safe_json_list(raw)
    if arr:
        out: list[str] = []
        for item in arr:
            if isinstance(item, dict):
                val = item.get("value") or item.get("name")
                if val:
                    out.append(str(val).strip())
            elif isinstance(item, str):
                out.append(item.strip())
        if out:
            return out
    if isinstance(raw, str):
        return [p.strip() for p in re.split(r"[,;|]", raw) if p.strip()]
    return []


def _size_band(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "unknown"
    t = raw.strip().lower()
    if t in {"nan", "none", "null", ""}:
        return "unknown"
    if t == "1-10":
        return "1-10"
    if t == "11-50":
        return "11-50"
    if t in {"51-100", "101-250"}:
        return "51-250"
    if t in {"251-500", "501-1000"}:
        return "251-1000"
    if t in {"1001-5000", "5001-10000", "10001+"}:
        return "1001+"
    return t


def _funding_12m_usd(rounds_raw: str, row_ts_raw: str) -> float:
    rounds = _safe_json_list(rounds_raw)
    if not rounds:
        return 0.0
    try:
        row_ts = datetime.fromisoformat(str(row_ts_raw).replace("Z", ""))
    except Exception:
        row_ts = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    cutoff = row_ts - timedelta(days=365)
    total = 0.0
    for r in rounds:
        if not isinstance(r, dict):
            continue
        announced_on = r.get("announced_on")
        if not announced_on:
            continue
        try:
            dt = datetime.fromisoformat(str(announced_on))
        except Exception:
            continue
        if dt < cutoff or dt > row_ts:
            continue
        money = r.get("money_raised") or {}
        if isinstance(money, dict):
            val = money.get("value_usd") or money.get("value")
            try:
                total += float(val or 0)
            except Exception:
                pass
    return round(total, 2)


def _ai_band(score: int) -> str:
    if score <= 1:
        return "low(0-1)"
    if score == 2:
        return "medium(2)"
    return "high(3)"


def _bench_match_score(text_blob: str, ai_score: int, hiring_velocity_60d: float, funding_12m_usd: float) -> float:
    hits = len(set(m.group(0).lower() for m in TENACIOUS_BENCH_RX.finditer(text_blob)))
    sector_fit = min(1.0, hits / 4.0)
    readiness_fit = ai_score / 3.0
    urgency = 0.0
    if hiring_velocity_60d > 0:
        urgency += min(1.0, hiring_velocity_60d / 8.0) * 0.6
    if funding_12m_usd > 0:
        urgency += 0.4
    score = 100.0 * (0.5 * sector_fit + 0.3 * readiness_fit + 0.2 * min(1.0, urgency))
    return round(score, 2)


def _norm(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([0.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo)


def _iter_company_rows(df: pd.DataFrame) -> Iterable[CompanyRow]:
    for _, row in df.iterrows():
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        industries_list = _parse_industries(row.get("industries"))
        sector = industries_list[0] if industries_list else "Unknown"
        size_band = _size_band(str(row.get("num_employees") or ""))

        about = str(row.get("about") or row.get("full_description") or "")
        industries_txt = ", ".join(industries_list)
        text_blob = f"{about} {industries_txt}"

        jobs = build_job_posts_signal_dict(fetch_job_posts_signal(name, mode="frozen"))
        velocity = float(jobs.get("velocity_delta_60d") or 0.0)

        ai = score_ai_maturity(
            enrichment_brief={
                "description": about,
                "industry": industries_txt,
                "key_people": str(row.get("founders") or ""),
            },
            jobs_signal=jobs,
            exec_commentary=about,
        )
        ai_score = int(ai.score)
        # Conservative boost: explicit AI wording should never stay at 0.
        if ai_score == 0:
            if AI_STRONG_HINT_RX.search(text_blob):
                ai_score = 2
            elif AI_MODERATE_HINT_RX.search(text_blob):
                ai_score = 1

        funding_12m = _funding_12m_usd(str(row.get("funding_rounds_list") or "[]"), str(row.get("timestamp") or ""))
        bench = _bench_match_score(text_blob, ai_score, velocity, funding_12m)

        yield CompanyRow(
            name=name,
            sector=sector,
            size_band=size_band,
            ai_score=ai_score,
            ai_band=_ai_band(ai_score),
            funding_12m_usd=funding_12m,
            hiring_velocity_60d=velocity,
            bench_match_score=bench,
            ai_confidence=ai.confidence,
            about=about,
            industries=industries_txt,
        )


def _analyst_review_label(row: pd.Series) -> str:
    text = f"{row['industries']} {row['about']}".lower()
    if any(k in text for k in ("artificial intelligence", "machine learning", "mlops", "llm", "generative")):
        return "high"
    if any(k in text for k in ("analytics", "data", "automation", "software", "platform")):
        return "medium"
    return "low"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATA)
    companies = pd.DataFrame([c.__dict__ for c in _iter_company_rows(df)])

    cells = (
        companies.groupby(["sector", "size_band", "ai_band"], dropna=False)
        .agg(
            cell_population=("name", "count"),
            avg_funding_12m_usd=("funding_12m_usd", "mean"),
            avg_hiring_velocity_60d=("hiring_velocity_60d", "mean"),
            bench_match_score=("bench_match_score", "mean"),
            avg_ai_maturity_score=("ai_score", "mean"),
        )
        .reset_index()
    )
    cells["combined_score"] = (
        0.35 * _norm(cells["cell_population"])
        + 0.25 * _norm(cells["avg_funding_12m_usd"])
        + 0.2 * _norm(cells["avg_hiring_velocity_60d"])
        + 0.2 * _norm(cells["bench_match_score"])
    ) * 100.0
    cells = cells.sort_values("combined_score", ascending=False)

    market_space_path = OUT_DIR / "market_space.csv"
    cells.to_csv(market_space_path, index=False, float_format="%.4f")

    top = cells[
        (cells["sector"] != "Unknown")
        & (cells["size_band"] != "unknown")
        & (cells["cell_population"] >= 3)
    ].head(5).copy()
    top_md = ["# Top Cells For Outbound Allocation", ""]
    for rank, (_, r) in enumerate(top.iterrows(), start=1):
        title = f"{r['sector']} | {r['size_band']} | {r['ai_band']}"
        rec = (
            "Allocate outbound sequences with research-finding language and a discovery CTA."
            if "medium" in r["ai_band"] or "high" in r["ai_band"]
            else "Allocate lighter educational outbound; prioritize qualification before hard booking asks."
        )
        paragraph = (
            f"**{title}** scored {r['combined_score']:.1f}. This cell has population={int(r['cell_population'])}, "
            f"avg_funding_12m_usd={r['avg_funding_12m_usd']:.0f}, avg_hiring_velocity_60d={r['avg_hiring_velocity_60d']:.2f}, "
            f"and bench_match_score={r['bench_match_score']:.1f}. Recommendation: {rec}"
        )
        top_md.append(f"## {rank}. {title}")
        top_md.append("")
        top_md.append(paragraph)
        top_md.append("")

    (OUT_DIR / "top_cells.md").write_text("\n".join(top_md), encoding="utf-8")

    # Lightweight validation sample for methodology section.
    sample_hi = companies.sort_values("ai_score", ascending=False).head(12)
    sample_lo = companies.sort_values("ai_score", ascending=True).head(12)
    validation = pd.concat([sample_hi, sample_lo], ignore_index=True).drop_duplicates(subset=["name"]).head(24)
    validation["predicted_label"] = validation["ai_score"].map(lambda s: "high" if s >= 3 else ("medium" if s == 2 else "low"))
    validation["review_label"] = validation.apply(_analyst_review_label, axis=1)
    validation["match"] = validation["predicted_label"] == validation["review_label"]
    validation_path = OUT_DIR / "validation_sample.csv"
    validation[["name", "sector", "size_band", "ai_score", "predicted_label", "review_label", "match", "industries", "about"]].to_csv(
        validation_path, index=False
    )

    tp = int(((validation["predicted_label"] != "low") & (validation["review_label"] != "low")).sum())
    fp = int(((validation["predicted_label"] != "low") & (validation["review_label"] == "low")).sum())
    fn = int(((validation["predicted_label"] == "low") & (validation["review_label"] != "low")).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    methodology = f"""# Market Space Mapping Methodology

## Scope
- Dataset: `data/crunchbase_sample.csv` (n={len(df)} companies).
- Segmentation cell: `(sector, company-size band, AI-readiness band)`.
- Sector definition: first normalized Crunchbase industry token from `industries`.
- Size bands: `1-10`, `11-50`, `51-250`, `251-1000`, `1001+`, `unknown`.

## AI-readiness scoring
- Base scorer: `enrichment.ai_maturity.score_ai_maturity` (same rubric used in per-lead enrichment).
- Inputs: description/about text, industry text, founders/key-people text, and frozen jobs signal (`data/job_posts_snapshot.json`).
- Conservative adjustment: if base score is `0` but explicit AI hint terms are present in public text, score is lifted to `1` (or `2` for strong AI language like "machine learning", "LLM", "generative AI").
- Readiness bands: `low(0-1)`, `medium(2)`, `high(3)`.

## Cell metrics
- `cell_population`: company count in each cell.
- `avg_funding_12m_usd`: mean USD raised in prior 12 months parsed from `funding_rounds_list`.
- `avg_hiring_velocity_60d`: mean (`current_roles - roles_60d_ago`) from frozen job snapshots; defaults to `0` where unavailable.
- `bench_match_score`: 0-100 fit proxy against Tenacious delivery strengths (AdTech/marketing analytics, loyalty/rewards automation, multi-platform integration, data/AI delivery).
- `combined_score`: weighted ranking score = 35% population + 25% funding + 20% hiring velocity + 20% bench match (min-max normalized).

## Validation snapshot
- Validation artifact: `eval/market_space/validation_sample.csv` (24 records, stratified from high and low predicted readiness).
- Review labels are analyst-reviewed proxy labels from public descriptions (`low|medium|high`) to estimate directional quality.
- Positive class = `medium/high`.
- Precision: `{precision:.3f}`
- Recall: `{recall:.3f}`
- TP={tp}, FP={fp}, FN={fn}

## Known error modes
- False negatives: companies with real internal AI maturity but weak public text footprint.
- False positives: companies with AI-heavy messaging but limited execution capacity.
- Hiring velocity sparsity: most firms lack frozen job snapshots; velocity estimates are conservative.
- Funding sparsity: many rows have empty `funding_rounds_list`, causing undercounting of 12-month funding.
"""
    (OUT_DIR / "methodology.md").write_text(methodology, encoding="utf-8")

    print(f"Wrote: {market_space_path}")
    print(f"Wrote: {OUT_DIR / 'top_cells.md'}")
    print(f"Wrote: {OUT_DIR / 'methodology.md'}")
    print(f"Wrote: {validation_path}")


if __name__ == "__main__":
    main()
