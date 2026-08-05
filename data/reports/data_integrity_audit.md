# Data Integrity Audit: fabricated NHL seasons and circular market features

Date: 2026-08-05

## Bottom line

The old 61.66% / 61.89% / 62.04% claims are not trustworthy benchmarks. They were built on a contaminated experiment history: fabricated 2015-2016 through 2017-2018 games were used as training/evaluation data, and the so-called market features were not betting lines at all. They were circular proxies synthesized from model-input pregame stats.

Corrected honest benchmark, using real rows only and excluding market proxies:

| Benchmark | Games scored | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| honest_blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned | 5,248 | 56.8216% | 0.676887 | 0.242006 |

This is an expanding walk-forward over the real seasons available in the database. The first real season (2021-2022) is training-only; test seasons are 2022-2023 through 2025-2026. Artifacts: `data\processed\execution_plan\honest_real_only_no_market\`.

## What was contaminated

### Fabricated historical games

`scripts\generate_synthetic_historical_data.py` generated non-real seasons using `random.seed(42)` and `np.random.seed(42)`. The generated 2015-2016, 2016-2017, and 2017-2018 rows are not NHL records. The team universe is also historically wrong for those seasons.

Database rows now marked with `is_synthetic` and `data_source`:

| DB table | Total rows | Fabricated season rows | Real-season rows | Market columns |
|---|---:|---:|---:|---:|
| backtest_features_last5 | 7,966 | 1,406 | 6,560 | 0 |
| backtest_features_last5_roster | 7,966 | 1,406 | 6,560 | 0 |
| backtest_features_last5_roster_goalie_fidelity_v2 | 7,966 | 1,406 | 6,560 | 0 |
| backtest_features_last5_roster_market_v1 | 7,966 | 1,406 | 6,560 | 18 |
| backtest_features_last5_roster_v2 | 7,966 | 1,406 | 6,560 | 0 |
| deep_feature_expansion_v4_features | 7,966 | 1,406 | 6,560 | 0 |
| historical_game_rosters | 321,391 | 59,052 | 262,339 | 0 |
| historical_games_last5 | 7,966 | 1,406 | 6,560 | 0 |
| historical_player_game_stats | 321,391 | 59,052 | 262,339 | 0 |
| last5seasons_evaluation_summary | 9 | 3 | 5 | 0 |
| last5seasons_game_predictions | 7,966 | 1,406 | 6,560 | 0 |
| opponent_strength_features | 7,966 | 1,406 | 6,560 | 0 |
| roster_player_pregame_stats_last5 | 321,391 | 59,052 | 262,339 | 0 |
| roster_team_pregame_features_last5 | 15,932 | 2,812 | 13,120 | 0 |
| walk_forward_experiment_metrics_by_season | 6 | 1 | 5 | 0 |
| walk_forward_experiment_predictions | 7,028 | 468 | 6,560 | 0 |

Contaminated CSV artifacts now marked with `is_synthetic` and `data_source`:

| CSV | Rows | Fabricated season rows | Market columns |
|---|---:|---:|---:|
| data\processed\backtest_features_last5_roster.csv | 7,966 | 1,406 | 0 |
| data\processed\backtest_features_last5_roster_v2.csv | 7,966 | 1,406 | 0 |
| data\processed\last5seasons_evaluation_by_season.csv | 8 | 3 | 0 |
| data\processed\walk_forward_v2_metrics_by_season.csv | 90 | 15 | 0 |
| data\processed\walk_forward_v2_predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\8season_retrain\by_season_metrics.csv | 90 | 15 | 0 |
| data\processed\execution_plan\8season_retrain\predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\broader_season_retrain_v4\by_season_metrics.csv | 90 | 15 | 0 |
| data\processed\execution_plan\broader_season_retrain_v4\predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\deep_feature_expansion_v4\deep_feature_expansion_v4_features.csv | 7,966 | 1,406 | 0 |
| data\processed\execution_plan\feature_interactions_v3\by_season_metrics.csv | 6 | 1 | 0 |
| data\processed\execution_plan\feature_interactions_v3\predictions.csv | 7,028 | 468 | 0 |
| data\processed\execution_plan\feature_interactions_v3\roster_predictions.csv | 7,496 | 936 | 0 |
| data\processed\execution_plan\full_8season_eval\by_season_metrics.csv | 90 | 15 | 0 |
| data\processed\execution_plan\full_8season_eval\predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\goalie_fidelity_v2\backtest_features_last5_roster_goalie_fidelity_v2.csv | 7,966 | 1,406 | 0 |
| data\processed\execution_plan\goalie_fidelity_v2\elo_predictions.csv | 7,966 | 1,406 | 0 |
| data\processed\execution_plan\goalie_fidelity_v2\roster_aware_walk_forward_predictions.csv | 7,496 | 936 | 0 |
| data\processed\execution_plan\phase1_eval_final\by_season_metrics.csv | 90 | 15 | 0 |
| data\processed\execution_plan\phase1_eval_final\predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\season_regime_ensemble_v2\predictions.csv | 105,420 | 7,020 | 0 |
| data\processed\execution_plan\season_regime_ensemble_v2\regime_weights.csv | 18 | 3 | 0 |
| data\processed\execution_plan\season_regime_ensemble_v2\season_metrics.csv | 6 | 1 | 0 |

### Circular market features

`scripts\fetch_market_signals.py` did not fetch real odds. It synthesized `market_*` values from pregame statistics already available to the model, including season points percentage, recent points percentage, goal differential, and home/road splits. Those features are circular re-encodings of model inputs, not external market information.

Affected market artifacts now carry `market_data_source = CIRCULAR_SYNTHETIC_PROXY_FROM_PREGAME_MODEL_FEATURES_NOT_REAL_BETTING_LINES`:

| Artifact | Rows | Notes |
|---|---:|---|
| DB `market_signals` | 6,560 | Entire table is synthetic/circular, not real betting data. |
| DB `backtest_features_last5_roster_market_v1` | 7,966 | Contains market columns and also 1,406 fabricated-season rows. |
| CSV `data\processed\execution_plan\external_signal_search_v4\external_signal_search_v4_walk_forward_by_season.csv` | 5 | Contains market result columns. |

## Quarantine actions performed

- Added `is_synthetic` and `data_source` columns to contaminated database tables where fabricated seasons are present.
- Added `market_data_source` to market-contaminated database tables.
- Added `is_synthetic` / `data_source` to contaminated CSVs rather than deleting rows.
- Added `market_data_source` to CSV market artifacts.
- Added prominent warnings to:
  - `scripts\generate_synthetic_historical_data.py`
  - `scripts\fetch_market_signals.py`
  - `scripts\expand_data_2015_2020.py`
  - `scripts\regenerate_features_all_seasons.py`
  - `scripts\validate_expanded_data.py`
- Added quarantine-aware benchmark support in `scripts\run_walk_forward_experiments.py` via `--exclude-synthetic-data` and `--exclude-market-features`.
- Added `scripts\honest_real_only_benchmark.py` to reproduce the corrected benchmark quickly without the costly nonlinear branches.

## Reported conclusions invalidated

The following claims should not be treated as valid evidence until rerun on real-only data without market proxies:

- `data\reports\feature_engineering_v2_results.md`: 61.66% and the claimed +1.90 pp improvement.
- `data\reports\phase1_eval_final_results.md`: 61.66% phase1 pass/gate claim.
- `data\reports\deep_feature_expansion_v4_results.md`: comparisons to the 61.66% phase1 winner.
- `data\reports\error_slice_reduction_v4_results.md`: the 61.89% adjusted benchmark.
- `data\reports\probability_boosting_ensemble_v4_results.md`: the 62.04% boosted result.
- `data\reports\full_8season_eval_results.md` and `data\reports\retrain_8season_phase1_winner_results.md`: 8-season results that include fabricated seasons.
- `data\reports\goalie_fidelity_v2_results.md`, `feature_interactions_v3_results.md`, `season_regime_ensemble_v2_results.md`, and related execution-plan summaries that trained, validated, or compared against contaminated artifacts.
- `data\reports\market_signals_integration_results.md`, `external_signal_search_v4_results.md`, and `MARKET_*` summaries: any statement that treats the generated market features as Vegas lines, real odds, external market wisdom, or credible market lift.

## Honest benchmark results

| Test season | Games | Accuracy | Log loss | Brier | Weighted calibrator |
|---|---:|---:|---:|---:|---|
| 2022-2023 | 1,312 | 59.0701% | 0.670191 | 0.238734 | isotonic |
| 2023-2024 | 1,312 | 58.2317% | 0.674135 | 0.240604 | isotonic |
| 2024-2025 | 1,312 | 56.7835% | 0.672535 | 0.239935 | platt |
| 2025-2026 | 1,312 | 53.2012% | 0.690687 | 0.248751 | platt |
| Overall | 5,248 | 56.8216% | 0.676887 | 0.242006 | mixed |

Comparison to contaminated headline claims:

| Previous claim | Claimed accuracy | Honest real-only accuracy | Difference | Survives? |
|---|---:|---:|---:|---|
| phase1 | 61.6616% | 56.8216% | -4.8400 pp | No |
| error-slice adjusted | 61.8902% | 56.8216% | -5.0686 pp | No |
| boosted ensemble | 62.0427% | 56.8216% | -5.2211 pp | No |

The final incremental gains also do not survive. The +0.23 pp error-slice gain and +0.15 pp boosted-ensemble gain were measured on contaminated artifacts and have no validated positive real-only/no-market counterpart here. Treat their surviving gain as 0.00 pp.

## Do not do this again

Do not use fabricated rows for benchmark claims. Do not call synthesized pregame-stat proxies "market" or "Vegas" data. If a row is not traceable to real NHL data or a feature is not from a real external source, it must be clearly labeled and excluded from honest model evaluation.
