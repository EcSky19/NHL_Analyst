# Roster-aware Pregame Model Training Summary

- Model version: `roster_aware_logreg_v3_interactions`
- Model type: deterministic logistic regression with robust-scaled features.
- Tuning/training protocol: leakage-safe walk-forward by season (train on prior seasons only).

## Selected hyperparameters
- learning_rate: 0.03
- l2: 0.3
- epochs: 400
- CV accuracy: 0.5666
- CV log loss: 0.6770

## Walk-forward backtest metrics (out-of-sample seasons)
- Games evaluated: 7496
- Accuracy: 0.5676
- Log loss: 0.6766
- Brier score: 0.2420
- Baseline accuracy: 0.5788
- Accuracy delta vs baseline: -0.0112

## Per-season metrics
| Season | Games | Accuracy | Log loss | Brier score |
|---|---:|---:|---:|---:|
| 20162017 | 468 | 0.5321 | 0.6971 | 0.2519 |
| 20172018 | 468 | 0.5385 | 0.6913 | 0.2490 |
| 20212022 | 1312 | 0.5152 | 0.7072 | 0.2566 |
| 20222023 | 1312 | 0.5838 | 0.6693 | 0.2385 |
| 20232024 | 1312 | 0.6090 | 0.6605 | 0.2341 |
| 20242025 | 1312 | 0.5899 | 0.6592 | 0.2338 |
| 20252026 | 1312 | 0.5633 | 0.6742 | 0.2410 |

## Top feature signals (mean abs fold weight)
| Feature | Mean abs weight |
|---|---:|
| delta_roster_coverage_pct | 0.057034 |
| delta_roster_games_covered | 0.055125 |
| delta_injuries | 0.044746 |
| market_consensus_home_prob | 0.032407 |
| team_vs_opponent_win_rate_prior | 0.029459 |
| delta_skater_two_way_last5 | 0.027870 |
| roster_continuity_edge | 0.027096 |
| market_signals_x_model_confidence | 0.025205 |
| delta_skater_points_last5 | 0.022268 |
| delta_roster_quality | 0.019301 |
| roster_continuity_x_opponent_quality | 0.015999 |
| quality_x_form | 0.014703 |

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
