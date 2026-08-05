> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Season Regime Ensemble v2

## Result
- Best accuracy: 0.622225
- Overall accuracy: 0.588645
- Phase 1 winner benchmark: 0.616616
- Drift help: Yes

## Notes
- Early/mid/late regimes are defined by within-season terciles.
- Weights are selected fold-safely from prior seasons plus only earlier games in the same season.
- Candidate pool: `elo_form_tuned`, `logistic_engineered`, `weighted_calibrated_isotonic`, `blend_logistic_weighted_70_30`.

## Season metrics
| Season | Games | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| 2017-2018 | 7020 | 0.534188 | 0.691812 | 0.249275 |
| 2021-2022 | 19680 | 0.598323 | 0.674373 | 0.240644 |
| 2022-2023 | 19680 | 0.591463 | 0.667090 | 0.237055 |
| 2023-2024 | 19680 | 0.596037 | 0.662667 | 0.235177 |
| 2024-2025 | 19680 | 0.599848 | 0.660173 | 0.234043 |
| 2025-2026 | 19680 | 0.576982 | 0.678308 | 0.242798 |

## Regime metrics
| Regime | Games | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| early | 35140 | 0.561042 | 0.681540 | 0.244316 |
| mid | 35140 | 0.582669 | 0.672428 | 0.239786 |
| late | 35140 | 0.622225 | 0.656251 | 0.231992 |

## Artifacts
- `data\processed\execution_plan\season_regime_ensemble_v2\overall_metrics.csv`
- `data\processed\execution_plan\season_regime_ensemble_v2\predictions.csv`
- `data\processed\execution_plan\season_regime_ensemble_v2\regime_metrics.csv`
- `data\processed\execution_plan\season_regime_ensemble_v2\regime_weights.csv`
- `data\processed\execution_plan\season_regime_ensemble_v2\season_metrics.csv`
- `data\processed\execution_plan\season_regime_ensemble_v2\summary.json`
