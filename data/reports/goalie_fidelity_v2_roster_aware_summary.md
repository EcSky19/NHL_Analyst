# Roster-aware Pregame Model Training Summary

- Model version: `roster_aware_logreg_v3_interactions`
- Model type: deterministic logistic regression with robust-scaled features.
- Tuning/training protocol: leakage-safe walk-forward by season (train on prior seasons only).

## Selected hyperparameters
- learning_rate: 0.05
- l2: 0.3
- epochs: 250
- CV accuracy: 0.5617
- CV log loss: 0.6793

## Walk-forward backtest metrics (out-of-sample seasons)
- Games evaluated: 7496
- Accuracy: 0.5627
- Log loss: 0.6792
- Brier score: 0.2432
- Baseline accuracy: 0.5788
- Accuracy delta vs baseline: -0.0161

## Per-season metrics
| Season | Games | Accuracy | Log loss | Brier score |
|---|---:|---:|---:|---:|
| 20162017 | 468 | 0.5363 | 0.6979 | 0.2522 |
| 20172018 | 468 | 0.5385 | 0.6910 | 0.2488 |
| 20212022 | 1312 | 0.5206 | 0.7083 | 0.2572 |
| 20222023 | 1312 | 0.5663 | 0.6744 | 0.2409 |
| 20232024 | 1312 | 0.5777 | 0.6678 | 0.2377 |
| 20242025 | 1312 | 0.5861 | 0.6616 | 0.2348 |
| 20252026 | 1312 | 0.5808 | 0.6729 | 0.2403 |

## Top feature signals (mean abs fold weight)
| Feature | Mean abs weight |
|---|---:|
| delta_roster_coverage_pct | 0.058719 |
| delta_roster_games_covered | 0.055884 |
| delta_injuries | 0.053858 |
| delta_skater_two_way_last5 | 0.041483 |
| team_vs_opponent_win_rate_prior | 0.032913 |
| delta_skater_points_last5 | 0.031249 |
| roster_continuity_edge | 0.027120 |
| delta_roster_quality | 0.022182 |
| roster_continuity_x_opponent_quality | 0.017613 |
| delta_goalie_starter_quality_gap_last5 | 0.016633 |
| delta_goalie_starter_quality_gap_last5 | 0.016633 |
| quality_x_form | 0.016244 |

## Feature coverage highlights
- Goalie signal: `delta_goalie_save_pct`, `goalie_x_continuity`.
- Skater production/two-way: `delta_skater_points_last5`, `delta_skater_two_way_last5`, `quality_x_form`.
- Roster quality/continuity: `delta_roster_quality`, `delta_roster_coverage_pct`, `delta_roster_games_covered`, `roster_continuity_edge`.
- Streak/location/team-strength priors: streak features, `home_location_edge_points_pct`, rest/B2B, prior-season deltas.
- Team-opponent interactions (regularized): `matchup_home_win_rate_prior`, `matchup_home_games_prior_log`, `team_vs_opponent_win_rate_prior`, `team_vs_opponent_games_prior_log`.

## Artifacts
- `data\processed\roster_aware_model_config.json`
- `data\processed\roster_aware_feature_importance.csv`
- `data\processed\roster_aware_walk_forward_predictions.csv`
- `data\reports\roster_aware_model_training_summary.md`
