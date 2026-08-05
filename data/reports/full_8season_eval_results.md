> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Full 8-Season Walk-Forward Evaluation

## Result
- Best accuracy: 0.616616 (61.66%)
- Delta vs 61.66%: +0.00 pp
- Moves meaningfully toward 70%: No
- Best model: `blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`

## Strict walk-forward setup
- 8-season dataset, season-expanding folds
- Train seasons always precede each held-out test season
- Recency selector: `season_regime_drift`
- Calibration selector: `season_aware`
- Strongest recovered variant: top-2 blend of calibrated weighted + ELO probabilities

## Best-model season breakdown
| Season | Games | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| 2021-2022 | 1312 | 0.616616 | 0.664252 | 0.235530 |

## Artifacts
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\full_8season_eval\predictions.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\full_8season_eval\overall_metrics.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\full_8season_eval\by_season_metrics.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\full_8season_eval\recency_comparison.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\full_8season_eval\summary.json`
