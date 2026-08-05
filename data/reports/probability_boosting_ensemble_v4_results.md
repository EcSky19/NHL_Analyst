> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Probability Boosting Ensemble v4

## Result
- Best accuracy: 0.620427
- Current best: 0.618902
- Delta: +0.001524

## Recipe
- 0.80 * phase1_eval_final:`blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`
- 0.20 * deep_feature_expansion_v4:`blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`

## Validation reference
- Phase 1 benchmark candidate is walk-forward validated in the repo.
- Deep feature-expansion and error-slice candidates are the strongest 2021-2022 holdout signals.
- Regime-aware output was tested as a diagnostic, but the fixed blend above was best overall.

## Candidate metrics
| Candidate | Accuracy | Log loss | Brier | Games |
|---|---:|---:|---:|---:|
| phase1_base | 0.616616 | 0.664252 | 0.235530 | 1312 |
| deep_feature_base | 0.617378 | 0.660604 | 0.233979 | 1312 |
| phase1_alt | 0.612805 | 0.670509 | 0.238459 | 1312 |
| deep_feature_alt | 0.606707 | 0.664439 | 0.235856 | 1312 |
| season_regime | 0.598323 | 0.674386 | 0.240651 | 1312 |
| error_slice_adjusted | 0.618902 | 0.664445 | 0.235626 | 1312 |
| boosted | 0.620427 | 0.663181 | 0.235073 | 1312 |

## Artifacts
- `data\processed\execution_plan\probability_boosting_ensemble_v4\predictions.csv`
- `data\processed\execution_plan\probability_boosting_ensemble_v4\candidate_metrics.csv`
- `data\processed\execution_plan\probability_boosting_ensemble_v4\overall_metrics.csv`
- `data\processed\execution_plan\probability_boosting_ensemble_v4\summary.json`
