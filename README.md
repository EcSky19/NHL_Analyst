# Sports Analytics: NHL and NFL

This repository now contains two pregame sports-modeling research tracks: the original NHL work and a new NFL prediction project. The common theme is honest out-of-sample evaluation, explicit data provenance, and resisting headline accuracy claims that do not survive audit.

## NHL project

The NHL project builds and evaluates pregame win-probability models from historical game, team, roster, goalie, schedule, and matchup features. It is useful for researching modest predictive edges, calibration, confidence tiers, and model failure modes in a high-variance sport.

## Honest current benchmark

Previous headline accuracy claims of **61.66%**, **61.89%**, and **62.04%** are retracted. They should not be used as evidence of model quality.

The corrected benchmark is a real-only, no-market expanding walk-forward evaluation over 5,248 games:

| Test season | Games | Accuracy |
|---|---:|---:|
| 2022-23 | 1,312 | 59.07% |
| 2023-24 | 1,312 | 58.23% |
| 2024-25 | 1,312 | 56.78% |
| 2025-26 | 1,312 | 53.20% |
| **Overall** | **5,248** | **56.82%** |

This is a real but modest edge over an always-pick-home baseline of roughly 52-54%, not a 60%+ all-games system.

Primary audit: `data\reports\data_integrity_audit.md`.

## Confidence tiers

Restricting predictions to high-confidence games raises accuracy, but **no tier clears 70% with statistical confidence** once measured on an adequate sample.

Expanded walk-forward evaluation on real data (largest available sample):

| Minimum confidence | Games | Coverage | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|---:|
| >=0.55 | 7,454 | 65.31% | 60.46% | 59.35%-61.57% |
| >=0.60 | 4,093 | 35.86% | 62.86% | 61.37%-64.33% |
| >=0.65 | 1,850 | 16.21% | 67.68% | 65.51%-69.77% |
| >=0.70 | 623 | 5.46% | 71.59% | 67.92%-74.99% |
| >=0.75 | 157 | 1.38% | 73.89% | 66.50%-80.13% |

An earlier verification on a smaller sample reported 77.40% at `>=0.70` (177 games, CI 70.70%-82.94%) and treated it as a defensible 70%+ result. **That finding did not replicate.** With 623 games instead of 177, the same tier falls to 71.59% and its confidence interval lower bound drops to 67.92%, below the 70% bar. The original figure was small-sample optimism.

Honest reading: the highest-confidence tier lands somewhere around **70-72%**, but the data does not support claiming it reliably exceeds 70%. Tiers above `>=0.70` have too few games to distinguish from noise.

Primary verification: `data\reports\confidence_tiers_clean_verification.md` and `data\reports\real_expanded_retrain_results.md`.

## Data integrity incident

A 2026-08-05 audit found two major contamination sources:

1. `scripts\generate_synthetic_historical_data.py` fabricated the 2015-16, 2016-17, and 2017-18 seasons using seeded random generation. Quarantine scope: 1,406 fabricated game/feature rows, 59,052 roster/stat rows, and 2,812 team pregame rows.
2. `scripts\fetch_market_signals.py` did not fetch real betting odds. It synthesized "market" and "Vegas" features from pregame statistics already available to the model, including season points percentage, last-10 percentage, goal differential, and home/road splits. Any measured "market lift" was circular.

The contaminated rows and artifacts were marked rather than deleted. Honest evaluation must exclude synthetic rows and market proxy features.

## What is genuinely true

- Honest all-games accuracy is about **56.8%** on the current clean benchmark.
- The model beats simple baselines, but the edge is modest.
- High-confidence games are genuinely more predictable, but **no confidence tier reliably reaches 70%**. The best tier sits near 71% with a confidence interval spanning 68-75%.
- About **6,084 genuinely real historical games from 2015-2020** have now been ingested from the NHL API with era-correct team handling: Arizona present, Utah/Seattle absent, and Vegas beginning in 2017-18.
- **More real history did not improve accuracy.** Retraining on the expanded real dataset produced 56.82%, identical to the prior benchmark (+0.00 pp). Recent-seasons-only scored 56.90% and recency-weighted full history 56.73% — all within noise. See `data\reports\real_expanded_retrain_results.md`. This suggests the model is limited by signal quality and inherent NHL randomness, not by training volume.

## What is not true

- This repo does **not** currently demonstrate 61.66%, 61.89%, or 62.04% honest all-games accuracy.
- This repo does **not** contain real historical Vegas odds in the synthetic market artifacts.
- This repo does **not** show that 70% accuracy is attainable across all NHL games.
- This repo does **not** show that 70% accuracy is reliably attainable even on a high-confidence subset. The earlier 77.40% claim failed to replicate on a larger sample.

Realistic context: published NHL prediction models and market favorites typically land around the low 60s at best, with Vegas closing favorites around 60%. NHL outcomes have high game-to-game variance, so 70% all-games accuracy is not a realistic target for a pregame model.


## NFL project

The NFL project uses real nflverse data, including real betting-market fields, to test how far pregame team/EPA/QB signal can go.

Key artifacts:

- `data\reports\nfl_project_summary.md` — complete NFL overview and honest interpretation.
- `data\reports\nfl_ingestion_report.md` — games/provenance report.
- `data\reports\nfl_advanced_stats_ingestion.md` — EPA/QB/team-week ingestion report.
- `data\reports\nfl_feature_engineering.md` — feature table and leakage checks.
- `data\reports\nfl_baselines_and_methodology.md` — baselines, holdout rules, and noise floor.
- `data\reports\nfl_market_signal_analysis.md` — market-ceiling and residual-signal tests.

NFL data summary:

- `games`: **7,548** real nflverse games, seasons **1999-2026**.
- Real Vegas moneylines: **72.77%** coverage; real spreads/totals: **100%** coverage.
- Future/unplayed games: **272**, flagged and excluded.
- Ties: **15**, with winner label set to NULL rather than coerced.
- Advanced team-week data: **8,726** rows, seasons **2010-2025**.
- QB weekly stats: **9,874** rows.
- Feature table: **4,363** played non-preseason games, **274** columns, leakage verification passed with **0** source-date violations.

NFL baselines and model findings:

| Reference / model | Accuracy | Notes |
|---|---:|---|
| Always pick home | 56.17% | Wilson 55.00%-57.33% |
| Vegas moneyline favorite | 66.59% | Wilson 65.27%-67.88%, n=5,025 |
| Market only walk-forward | 66.24% | log loss 0.6112 |
| Team/EPA/QB only, no market | 63.98% | log loss 0.6305 |
| Market + team features | 66.34% | log loss worsened to 0.6154 |

Central NFL finding: team/EPA/QB features add **no detectable value** beyond the betting market on the common walk-forward sample. The market + team accuracy gain was only **+0.10 percentage points** with a paired CI of **-0.79 to +0.99 pp**, and log loss worsened. The market is well calibrated, with bucket MAE **1.32%**, and no pre-registered market-bias slice produced a reliable exploitable edge.

The realistic NFL straight-up ceiling here is therefore about **66%-67%**. A durable **70%** result is not supported; it would require beating the closing market by roughly **3.4 pp**. The genuinely positive result is that a market-free model reached **63.98%** using Elo, EPA, and QB signal, within about **2.3 pp** of Vegas.

Home-field advantage is also time-varying: it was often around **57%-61%** in 1999-2003, fell to exactly **50.00%** in the 2020 empty-stadium season, and has been roughly **53%-56%** in 2023-2025.

Noise-floor caution: one modern NFL season has only about 272 games. The minimum detectable difference is about **7.92 pp** for one season, **4.57 pp** for three seasons, and **1.65 pp** for the full 2002-present regular-season era. Small one-season wins over a baseline are not evidence of a better model.

## Cross-sport lesson

NFL games are substantially more predictable than NHL games in this repository: the NFL market sits around **66%-67%**, while the corrected NHL all-games benchmark is about **56.8%**. But **70% is out of reach in both projects** for different versions of the same reason: it sits above the practical ceiling supported by clean out-of-sample evidence.

The earlier NHL failure is the reason the NFL project is explicit about provenance, synthetic-data prohibition, market-feature separation, holdout locking, and empirical leakage checks. In NHL, fabricated seasons and circular fake market features invalidated 61%-62% headline claims. In NFL, the betting market fields are real, but they mostly define the ceiling rather than create an exploitable path beyond it.

## Reading old reports

Older reports are retained for history. Reports with invalidated accuracy claims or market-feature interpretations now carry correction notices at the top. When in doubt, prefer:

- `data\reports\data_integrity_audit.md`
- `data\reports\confidence_tiers_clean_verification.md`
