# Broader Season Retrain v4 Results

## Result
- Best held-out accuracy: **0.6166** (61.66%)
- Delta vs current best 61.89%: **-0.23 pp**
- Delta vs phase1 benchmark 61.66%: **+0.00 pp**
- Broader history meaningfully helped overall? **No**

## Interpretation
- The broader 8-season retrain matched the phase1 winner on the strongest slice (2021-2022) but did not surpass the 61.89% slice-adjusted benchmark.
- On the full 7,028-game broader window, the best model was `elo_form_tuned` at **57.7262%**, slightly below the last-5-seasons overall baseline (**57.8811%**).
- That means deeper history added coverage, but not enough signal to move the aggregate ceiling toward 70%.
- Gains were slice-specific: the 2021-2022 slice remained strong, while 2025-2026 stayed weak at **53.5823%**.

## Best full-window model
- Model: `elo_form_tuned`
- Accuracy: **0.5773**
- Games: 7028

## ELO season breakdown
| Season | Games | Accuracy | Log loss | Brier |
|---|---:|---:|---:|---:|
| 2017-2018 | 468 | 0.5107 | 0.7126 | 0.2590 |
| 2021-2022 | 1312 | 0.6166 | 0.6576 | 0.2323 |
| 2022-2023 | 1312 | 0.5922 | 0.6664 | 0.2368 |
| 2023-2024 | 1312 | 0.5877 | 0.6746 | 0.2405 |
| 2024-2025 | 1312 | 0.5777 | 0.6777 | 0.2422 |
| 2025-2026 | 1312 | 0.5358 | 0.7008 | 0.2533 |

## Outputs
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\predictions.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\overall_metrics.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\by_season_metrics.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\recency_comparison.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\logistic_importance.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\calibration_diagnostics.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\broader_season_retrain_v4\summary.json`
