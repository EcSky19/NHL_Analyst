> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Goalie Fidelity V2 Results

## Summary
- Best observed 2025-2026 accuracy: **58.08%** (roster-aware logistic on goalie-fidelity features).
- Benchmark current best model: **61.66%**.
- Goalie fidelity **did not beat** the benchmark, but it improved goalie feature coverage and lifted the roster-aware logistic vs the prior 2025-2026 logistic baseline.

## Coverage
- `home_pregame_goalie_starter_certainty`: 100.00%
- `away_pregame_goalie_starter_certainty`: 100.00%
- `home_pregame_goalie_starter_quality_gap_last5`: 100.00%
- `away_pregame_goalie_starter_quality_gap_last5`: 100.00%
- `delta_pregame_goalie_starter_quality_gap_last5_home_minus_away`: 100.00%

## Coverage improvement vs earlier goalie features
- Starter certainty was already full coverage.
- Starter quality-gap coverage improved from ~5.9% to **100%**.
- Delta quality-gap coverage improved from ~0.32% to **100%**.

## Interpretation
- The new starter selection logic is more complete and pregame-safe.
- The extra goalie fidelity helped the lower-tier roster-aware logistic model, but not enough to surpass 61.66%.

## Artifacts
- `data\processed\execution_plan\goalie_fidelity_v2\backtest_features_last5_roster_goalie_fidelity_v2.csv`
- `data\processed\execution_plan\goalie_fidelity_v2\goalie_feature_coverage_comparison.csv`
- `data\processed\execution_plan\goalie_fidelity_v2\goalie_starter_diagnostics.json`
- `data\processed\execution_plan\goalie_fidelity_v2\roster_aware_model_config.json`
- `data\processed\execution_plan\goalie_fidelity_v2\roster_aware_feature_importance.csv`
- `data\processed\execution_plan\goalie_fidelity_v2\roster_aware_walk_forward_predictions.csv`
- `data\processed\execution_plan\goalie_fidelity_v2\elo_predictions.csv`
- `data\processed\execution_plan\goalie_fidelity_v2\elo_summary.json`
