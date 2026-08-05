# Last 5 NHL Regular Seasons Evaluation

## Methodology
- Strict pregame walk-forward evaluation over `historical_games_last5`.
- Per game, probability is generated before outcome using only information available before puck drop:
  - carry-over Elo-like team strength
  - season-to-date pregame win percentage
  - season-to-date pregame goal differential per game
- Deterministic setup (no random seeds or stochastic training).
- Backtest-feature dependency status: `backtest_features_available`.

## Model parameters
- ELO_MEAN=1500.0
- ELO_REGRESSION=0.75
- ELO_HOME_ADVANTAGE=55.0
- ELO_K_FACTOR=18.0
- FORM_WIN_PCT_ELO_WEIGHT=120.0
- FORM_GOAL_DIFF_ELO_WEIGHT=35.0

## Overall metrics
- Games: 7966
- Accuracy: 0.5685
- Log loss: 0.6940
- Brier score: 0.2489

## Per-season metrics
| Season | Games | Accuracy | Log loss | Brier score |
|---|---:|---:|---:|---:|
| 2015-2016 | 470 | 0.5170 | 0.7183 | 0.2609 |
| 2016-2017 | 468 | 0.5385 | 0.7129 | 0.2583 |
| 2017-2018 | 468 | 0.5043 | 0.7302 | 0.2662 |
| 2021-2022 | 1312 | 0.6181 | 0.6673 | 0.2358 |
| 2022-2023 | 1312 | 0.5899 | 0.6799 | 0.2423 |
| 2023-2024 | 1312 | 0.5854 | 0.6894 | 0.2464 |
| 2024-2025 | 1312 | 0.5655 | 0.6883 | 0.2465 |
| 2025-2026 | 1312 | 0.5358 | 0.7166 | 0.2597 |

## Artifacts
- `data\processed\last5seasons_game_predictions.csv`
- `data\processed\last5seasons_evaluation_summary.json`
- `data\processed\last5seasons_evaluation_by_season.csv`
- `data\reports\last5seasons_evaluation_report.md`
