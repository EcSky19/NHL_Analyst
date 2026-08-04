# Roster-aware Pregame Model Training Summary

- Model version: `roster_aware_logreg_v1`
- Model type: deterministic logistic regression with robust-scaled features.
- Tuning/training protocol: leakage-safe walk-forward by season (train on prior seasons only).

## Selected hyperparameters
- learning_rate: 0.05
- l2: 0.01
- epochs: 400
- CV accuracy: 0.5953
- CV log loss: 0.6553

## Walk-forward backtest metrics (out-of-sample seasons)
- Games evaluated: 5248
- Accuracy: 0.5972
- Log loss: 0.6588
- Brier score: 0.2335
- Baseline accuracy: 0.5788
- Accuracy delta vs baseline: +0.0184

## Per-season metrics
| Season | Games | Accuracy | Log loss | Brier score |
|---|---:|---:|---:|---:|
| 20222023 | 1312 | 0.6029 | 0.6692 | 0.2374 |
| 20232024 | 1312 | 0.6174 | 0.6497 | 0.2288 |
| 20242025 | 1312 | 0.6067 | 0.6447 | 0.2276 |
| 20252026 | 1312 | 0.5617 | 0.6715 | 0.2400 |

## Top feature signals (mean abs fold weight)
| Feature | Mean abs weight |
|---|---:|
| delta_roster_games_covered | 0.224452 |
| delta_roster_coverage_pct | 0.187353 |
| delta_season_goal_diff_pg | 0.178198 |
| delta_season_points_pct | 0.125415 |
| home_back_to_back | 0.085991 |
| quality_x_form | 0.076126 |
| delta_roster_quality | 0.070839 |
| goalie_x_continuity | 0.066431 |
| delta_injuries | 0.066283 |
| delta_goalie_save_pct | 0.063395 |
| home_streak | 0.052597 |
| away_back_to_back | 0.051899 |

## Feature coverage highlights
- Goalie signal: `delta_goalie_save_pct`, `goalie_x_continuity`.
- Skater production/two-way: `delta_skater_points_last5`, `delta_skater_two_way_last5`, `quality_x_form`.
- Roster quality/continuity: `delta_roster_quality`, `delta_roster_coverage_pct`, `delta_roster_games_covered`, `roster_continuity_edge`.
- Streak/location/team-strength priors: streak features, `home_location_edge_points_pct`, rest/B2B, prior-season deltas.

## Artifacts
- `data\processed\roster_aware_model_config.json`
- `data\processed\roster_aware_feature_importance.csv`
- `data\processed\roster_aware_walk_forward_predictions.csv`
- `data\reports\roster_aware_model_training_summary.md`
