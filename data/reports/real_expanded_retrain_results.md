# Real expanded retrain results

## Executive result
Against the fixed honest benchmark window (5248 games, 20222023 20232024 20242025 20252026), all prior real history scored **56.82%** vs the prior **56.82%** benchmark (+0.00 pp; z≈0.00 using the requested ~0.6 pp SE).
**Statistically meaningful:** no.

## Data integrity checks
- The expanded feature table has no `market_*` columns.
- `exclude_synthetic_data=True` was used when loading features.
- 2015-2019 rows are real NHL API rows (`data_source='real_nhl_api_web'`); no fabricated 2015-2018 feature rows were used.

| season | games | synthetic_rows | sources |
| --- | --- | --- | --- |
| 20152016 | 1230 | 0 | real_nhl_api_web |
| 20162017 | 1230 | 0 | real_nhl_api_web |
| 20172018 | 1271 | 0 | real_nhl_api_web |
| 20182019 | 1271 | 0 | real_nhl_api_web |
| 20192020 | 1082 | 0 | real_nhl_api_web |
| 20212022 | 1312 | 0 | REAL_NHL_API_OR_DERIVED_FROM_REAL |
| 20222023 | 1312 | 0 | REAL_NHL_API_OR_DERIVED_FROM_REAL |
| 20232024 | 1312 | 0 | REAL_NHL_API_OR_DERIVED_FROM_REAL |
| 20242025 | 1312 | 0 | REAL_NHL_API_OR_DERIVED_FROM_REAL |
| 20252026 | 1312 | 0 | REAL_NHL_API_OR_DERIVED_FROM_REAL |

## Roster/player-stat coverage
Roster/player boxscore features exist for 2015-2018 and 2021-2026. They are intentionally absent for 2018-2019 and 2019-2020, so roster features degrade to null/default-safe values rather than imputed outcomes.

| season | games | both_roster_source_games | avg_home_roster_coverage_pct | avg_away_roster_coverage_pct |
| --- | --- | --- | --- | --- |
| 20152016 | 1230 | 1230 | 0.98 | 0.98 |
| 20162017 | 1230 | 1230 | 1.0 | 1.0 |
| 20172018 | 1271 | 1271 | 1.0 | 1.0 |
| 20182019 | 1271 | 0 | 0.0 | 0.0 |
| 20192020 | 1082 | 0 | 0.0 | 0.0 |
| 20212022 | 1312 | 1312 | 0.99 | 0.99 |
| 20222023 | 1312 | 1312 | 1.0 | 1.0 |
| 20232024 | 1312 | 1312 | 1.0 | 1.0 |
| 20242025 | 1312 | 1312 | 1.0 | 1.0 |
| 20252026 | 1312 | 1312 | 1.0 | 1.0 |

## Benchmark-window model comparison
| policy | test_scope | test_seasons | games | accuracy | log_loss | brier_score |
| --- | --- | --- | --- | --- | --- | --- |
| all_prior_real | benchmark_window | 20222023 20232024 20242025 20252026 | 5248 | 56.82% | 0.6763 | 0.2418 |
| recent_2021_forward | benchmark_window | 20222023 20232024 20242025 20252026 | 5248 | 56.90% | 0.6780 | 0.2425 |
| all_prior_real_recency_weighted | benchmark_window | 20222023 20232024 20242025 20252026 | 5248 | 56.73% | 0.6767 | 0.2420 |

Policy definitions: `all_prior_real` trains on every earlier real season; `recent_2021_forward` trains only on earlier seasons from 2021-2022 onward; `all_prior_real_recency_weighted` uses all earlier real seasons with a predeclared 2-season half-life.

## Benchmark-window folds
| policy | season | train_start_season | train_end_season | train_games | games | accuracy | log_loss | brier_score | weighted_calibrator |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all_prior_real | 20222023 | 20152016 | 20212022 | 7396 | 1312 | 58.99% | 0.6669 | 0.2373 | platt |
| all_prior_real | 20232024 | 20152016 | 20222023 | 8708 | 1312 | 58.31% | 0.6733 | 0.2403 | platt |
| all_prior_real | 20242025 | 20152016 | 20232024 | 10020 | 1312 | 56.86% | 0.6728 | 0.2402 | platt |
| all_prior_real | 20252026 | 20152016 | 20242025 | 11332 | 1312 | 53.12% | 0.6923 | 0.2495 | platt |
| recent_2021_forward | 20222023 | 20212022 | 20212022 | 1312 | 1312 | 58.08% | 0.6689 | 0.2381 | isotonic |
| recent_2021_forward | 20232024 | 20212022 | 20222023 | 2624 | 1312 | 58.23% | 0.6766 | 0.2416 | isotonic |
| recent_2021_forward | 20242025 | 20212022 | 20232024 | 3936 | 1312 | 58.00% | 0.6733 | 0.2404 | platt |
| recent_2021_forward | 20252026 | 20212022 | 20242025 | 5248 | 1312 | 53.28% | 0.6931 | 0.2498 | platt |
| all_prior_real_recency_weighted | 20222023 | 20152016 | 20212022 | 7396 | 1312 | 58.92% | 0.6675 | 0.2376 | platt |
| all_prior_real_recency_weighted | 20232024 | 20152016 | 20222023 | 8708 | 1312 | 58.00% | 0.6740 | 0.2406 | platt |
| all_prior_real_recency_weighted | 20242025 | 20152016 | 20232024 | 10020 | 1312 | 56.86% | 0.6730 | 0.2403 | platt |
| all_prior_real_recency_weighted | 20252026 | 20152016 | 20242025 | 11332 | 1312 | 53.12% | 0.6924 | 0.2495 | platt |

## Larger-sample confidence tiers
Computed on the full expanded walk-forward `all_prior_real` run (first season training-only).

| threshold | games | coverage_pct | accuracy | ci95_low | ci95_high |
| --- | --- | --- | --- | --- | --- |
| >=0.55 | 7454 | 65.31 | 60.46% | 59.35% | 61.57% |
| >=0.60 | 4093 | 35.86 | 62.86% | 61.37% | 64.33% |
| >=0.65 | 1850 | 16.21 | 67.68% | 65.51% | 69.77% |
| >=0.70 | 623 | 5.46 | 71.59% | 67.92% | 74.99% |
| >=0.75 | 157 | 1.38 | 73.89% | 66.50% | 80.13% |

## Interpretation
More genuine history improved the fixed benchmark by +0.00 pp. The recent-only policy scored 56.90%; the recency-weighted all-history diagnostic scored 56.73%. Because these variants were compared on the same fixed test window, treat the variant comparison as diagnostic rather than a newly selected production model.
