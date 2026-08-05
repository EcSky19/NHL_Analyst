# NHL principled improvement attempt

Generated: 2026-08-05

## Verdict

Selected frozen holdout model: **58.61%** (769/1312), Wilson 95% CI **55.93%-61.25%**. This is above the audited live 56.82% point estimate; the interval is wide enough that the margin is inside the noise floor. It is rejected as a serving improvement because the probability sanity check failed.

Synthetic rows excluded from `deep_feature_expansion_v4_features` by `is_synthetic = 0`: **1406**. Schema check found `is_synthetic`: **True**.

OT/SO handling: All final NHL winners are included; OT/SO games are not separated because this feature table has no reliable pregame-safe regulation/OT flag. Accuracy is final winner accuracy.

## Frozen holdout and baselines

| Approach | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| Selected model | 1312 | 58.61% | 55.93%-61.25% | 0.671218 | 0.239515 |
| Always home | 1312 | 52.21% | 49.50%-54.90% | 0.692444 | 0.249648 |
| Elo baseline | 1312 | 54.34% | 51.64%-57.02% | 0.704634 | 0.254780 |

## Development attempts

All attempts used walk-forward development folds only: train earlier seasons, Platt-calibrate on a later season, test on a still later season. The final holdout was not scored until after `scripts\nhl\nhl_principled_frozen_config.json` was written.

| Rank | Approach | Features | Games | Dev accuracy | Wilson 95% CI | Log loss | Brier |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | hist_gradient_boosting:all_pregame_safe | 157 | 2624 | 59.79% | 57.91%-61.65% | 0.665075 | 0.236461 |
| 2 | hist_gradient_boosting:roster_goalie | 106 | 2624 | 59.34% | 57.45%-61.20% | 0.667336 | 0.237505 |
| 3 | hist_gradient_boosting:roster_goalie | 106 | 2624 | 58.80% | 56.91%-60.67% | 0.667345 | 0.237540 |
| 4 | hist_gradient_boosting:all_pregame_safe | 157 | 2624 | 58.54% | 56.64%-60.41% | 0.664036 | 0.235975 |
| 5 | logistic:all_pregame_safe | 157 | 2624 | 58.38% | 56.49%-60.26% | 0.672713 | 0.239718 |
| 6 | logistic:all_pregame_safe | 157 | 2624 | 57.89% | 55.99%-59.76% | 0.675541 | 0.241057 |
| 7 | logistic:all_pregame_safe | 157 | 2624 | 57.77% | 55.87%-59.65% | 0.673413 | 0.240039 |
| 8 | logistic:all_pregame_safe | 157 | 2624 | 57.66% | 55.76%-59.54% | 0.676937 | 0.241731 |
| 9 | logistic:all_pregame_safe | 157 | 2624 | 57.58% | 55.68%-59.46% | 0.674828 | 0.240710 |
| 10 | logistic:all_pregame_safe | 157 | 2624 | 57.47% | 55.57%-59.35% | 0.674243 | 0.240429 |
| 11 | hist_gradient_boosting:goalie_augmented | 40 | 2624 | 57.28% | 55.38%-59.16% | 0.672900 | 0.240217 |
| 12 | hist_gradient_boosting:goalie_augmented | 40 | 2624 | 57.05% | 55.15%-58.93% | 0.671790 | 0.239751 |

Elo was tuned on development folds as a serious hockey baseline. Best development Elo parameters were `K=12.0`, `home_advantage=65.0` with development accuracy 59.07%.

Special-teams features were attempted only where present in the pregame-derived table. Static or ambiguously season-final columns were not allowed to override the leakage checks.

## Calibration reliability table

Buckets are by calibrated home-win probability. Buckets with fewer than 150 games must not support confidence-tier claims.

| Bucket | Games | Avg predicted home P | Observed home win rate | Wilson 95% CI | Under 150? |
|---|---:|---:|---:|---:|---:|
| 0.30-0.40 | 84 | 35.96% | 29.76% | 21.04%-40.25% | 1 |
| 0.40-0.45 | 97 | 42.78% | 42.27% | 32.92%-52.21% | 1 |
| 0.45-0.50 | 161 | 47.68% | 45.34% | 37.85%-53.05% | 0 |
| 0.50-0.55 | 244 | 52.59% | 58.20% | 51.93%-64.21% | 0 |
| 0.55-0.60 | 267 | 57.52% | 50.56% | 44.60%-56.51% | 0 |
| 0.60-0.70 | 308 | 64.06% | 58.12% | 52.54%-63.49% | 0 |

## Leakage self-checks

- Final goal-differential regression R-squared on selected features (non-holdout rows): **0.1657**.
- Shuffled training/calibration labels holdout accuracy: **52.29%**. This collapses near chance and argues against a direct label leak.
- Maximum holdout probability emitted: **0.906**; minimum: **0.146**. This fails the stated hockey sanity range and is treated as an overconfidence/calibration bug, not a deployable win.

## Candid verdict

The attempt is directionally better than the audited 56.82% point estimate on the single frozen 2025-2026 holdout, but the Wilson interval overlaps both 56.82% and the baselines, and the selected model is too overconfident. That is not strong evidence of a durable or serving-safe improvement. Hockey remains noisy; goalie/roster/context features help only modestly without reliable confirmed starter and regulation/OT labels.

## Artifacts

- Script: `scripts\nhl\nhl_principled_improvement.py`
- Frozen config: `scripts\nhl\nhl_principled_frozen_config.json`
- Database tables: `nhl_improved_predictions`, `nhl_improved_metrics`, `nhl_improved_calibration`
