# Market Space Mapping Methodology

## Scope
- Dataset: `data/crunchbase_sample.csv` (n=1000 companies).
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
- Precision: `1.000`
- Recall: `0.857`
- TP=12, FP=0, FN=2

## Known error modes
- False negatives: companies with real internal AI maturity but weak public text footprint.
- False positives: companies with AI-heavy messaging but limited execution capacity.
- Hiring velocity sparsity: most firms lack frozen job snapshots; velocity estimates are conservative.
- Funding sparsity: many rows have empty `funding_rounds_list`, causing undercounting of 12-month funding.
