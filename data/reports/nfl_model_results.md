# NFL final model results

Generated: 2026-08-05T20:22:42+00:00

## Holdout policy

The final configurations were frozen to `data\nfl\nfl_final_model_frozen_config.json` before the 2024-2025 holdout was unlocked. The holdout was then evaluated once with the explicit unlock token.

Configurations evaluated during development: **16 total** (**8 per model**, two feature sets: market-free and full). Development folds were expanding walk-forward seasons 2014-2023, training only on prior seasons from 2010-2023.

Selection rule: simplest model family within 1.00 percentage point of the best walk-forward accuracy, with lower log loss as tie-breaker.

## Locked holdout headline

| Model | Games | Correct | Accuracy (Wilson 95% CI) | Log loss | Brier |
|---|---|---|---|---|---|
| Market-free | 543 | 359 | 66.11% (62.03%-69.97%) | 0.6210 | 0.2155 |
| Full | 543 | 366 | 67.40% (63.35%-71.21%) | 0.6035 | 0.2083 |

## Baseline comparison

| Baseline on same 2024-2025 holdout | Games | Correct | Accuracy (Wilson 95% CI) |
|---|---|---|---|
| Always pick home | 543 | 291 | 53.59% (49.39%-57.75%) |
| Vegas moneyline favorite | 543 | 372 | 68.51% (64.48%-72.27%) |

Project reference bars from the methodology report are always-pick-home **56.17%** (55.00%-57.33%) and Vegas moneyline favorite **66.59%** (65.27%-67.88%). The 2024-2025 sample is only two seasons, so differences below roughly 4.5-8 percentage points should be treated as noise.

- Market-free: 66.11% (62.03%-69.97%); vs global home bar +9.94 pp, vs global Vegas bar -0.48 pp.
- Full: 67.40% (63.35%-71.21%); vs global home bar +11.23 pp, vs global Vegas bar +0.81 pp.
- None of the model/Vegas differences on this two-season holdout should be described as a detectable improvement unless the Wilson intervals and noise floor clearly separate them; here they do not.

## Calibration

| Model | Log loss | Brier |
|---|---|---|
| Market-free | 0.6210 | 0.2155 |
| Full | 0.6035 | 0.2083 |

Reliability by predicted home-win probability:

| Model | Predicted home bucket | Games | Avg predicted | Actual home win |
|---|---|---|---|---|
| Market-free | 0-20% | 25 | 15.94% | 24.00% |
| Market-free | 20-40% | 141 | 31.38% | 31.91% |
| Market-free | 40-50% | 86 | 45.07% | 47.67% |
| Market-free | 50-60% | 93 | 55.37% | 58.06% |
| Market-free | 60-80% | 148 | 69.61% | 68.92% |
| Market-free | 80-100% | 50 | 85.63% | 86.00% |
| Full | 0-20% | 33 | 16.11% | 15.15% |
| Full | 20-40% | 139 | 31.01% | 32.37% |
| Full | 40-50% | 67 | 45.48% | 47.76% |
| Full | 50-60% | 83 | 55.25% | 53.01% |
| Full | 60-80% | 166 | 69.65% | 71.69% |
| Full | 80-100% | 55 | 86.69% | 83.64% |

## Accuracy by confidence tier

| Model | Confidence | Games | Coverage | Accuracy (Wilson 95% CI) | Flag |
|---|---|---|---|---|---|
| Market-free | 50-55% | 82 | 15.10% | 54.88% (44.13%-65.19%) | too small |
| Market-free | 55-60% | 97 | 17.86% | 55.67% (45.76%-65.15%) | too small |
| Market-free | 60-65% | 93 | 17.13% | 61.29% (51.13%-70.55%) | too small |
| Market-free | 65-70% | 63 | 11.60% | 71.43% (59.30%-81.10%) | too small |
| Market-free | 70-75% | 75 | 13.81% | 73.33% (62.37%-82.02%) | too small |
| Market-free | 75-80% | 58 | 10.68% | 70.69% (57.99%-80.82%) | too small |
| Market-free | 80-90% | 67 | 12.34% | 82.09% (71.25%-89.45%) | too small |
| Market-free | 90-100% | 8 | 1.47% | 87.50% (52.91%-97.76%) | too small |
| Full | 50-55% | 79 | 14.55% | 54.43% (43.50%-64.95%) | too small |
| Full | 55-60% | 71 | 13.08% | 50.70% (39.34%-61.99%) | too small |
| Full | 60-65% | 83 | 15.29% | 68.67% (58.06%-77.64%) | too small |
| Full | 65-70% | 87 | 16.02% | 65.52% (55.06%-74.66%) | too small |
| Full | 70-75% | 74 | 13.63% | 74.32% (63.35%-82.90%) | too small |
| Full | 75-80% | 61 | 11.23% | 72.13% (59.83%-81.81%) | too small |
| Full | 80-90% | 77 | 14.18% | 83.12% (73.23%-89.86%) | too small |
| Full | 90-100% | 11 | 2.03% | 90.91% (62.26%-98.38%) | too small |

Only sub-150-game tiers reach 70% accuracy with a Wilson lower bound at or above 70%, so none is reliable enough to lean on.

## Market-free feature importance

| Feature | Importance | Coefficient |
|---|---|---|
| diff_qb_passing_epa_career_to_date | 0.1652 | +0.1652 |
| home_qb_passing_cpoe_career_to_date | 0.1115 | -0.1115 |
| home_qb_passing_cpoe_last5 | 0.1082 | +0.1082 |
| home_offensive_success_rate_last3 | 0.1066 | +0.1066 |
| away_rush_epa_per_play_season_to_date | 0.0997 | +0.0997 |
| home_turnover_margin_last3 | 0.0985 | +0.0985 |
| home_offensive_epa_per_play_last5 | 0.0974 | +0.0974 |
| home_pass_success_rate_last5 | 0.0969 | -0.0969 |
| diff_defensive_epa_per_play_allowed_last8 | 0.0968 | -0.0968 |
| diff_qb_passing_epa_per_dropback_last5 | 0.0963 | -0.0963 |
| home_pass_epa_per_play_last3 | 0.0958 | -0.0958 |
| away_offensive_epa_per_play_last5 | 0.0943 | +0.0943 |
| home_takeaway_rate_last5 | 0.0943 | -0.0943 |
| away_pass_epa_per_play_last8 | 0.0939 | -0.0939 |
| away_rush_epa_per_play_last3 | 0.0915 | -0.0915 |
| home_qb_passing_epa_per_dropback_career_to_date | 0.0898 | +0.0898 |
| home_qb_passing_epa_per_dropback_last3 | 0.0895 | +0.0895 |
| away_travel_timezone_abs | 0.0884 | -0.0884 |
| away_pass_success_rate_last5 | 0.0884 | -0.0884 |
| away_elo_pregame | 0.0840 | -0.0840 |

Interpretation: the market-free model is the football-fundamentals model. The full model includes separable market features and should be read as a maximum-accuracy market-replication model, not proof that engineered team features add value beyond Vegas.
