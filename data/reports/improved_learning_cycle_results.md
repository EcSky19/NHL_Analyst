# Improved Learning Cycle Results

## Best model this cycle
- **Model:** `logistic_engineered`
- **Selection rule:** highest out-of-sample accuracy; tie-breakers: lower log loss, then lower brier score.
- **Source summary:** `data\processed\walk_forward_selected_logistic_engineered_summary.json`

## Overall metrics (selected model)
- **Accuracy:** `0.595020`
- **Log loss:** `0.655350`
- **Brier score:** `0.232216`
- **Games:** `3936`

## Accuracy comparisons
- **Vs previous best roster-aware model (`0.597180`):** `-0.002160` (not improved)
- **Vs baseline (`0.578811`):** `+0.016209` (improved vs baseline)

## Per-season accuracy (selected model)
| Season | Games | Accuracy |
|---|---:|---:|
| 2023-2024 | 1312 | 0.612805 |
| 2024-2025 | 1312 | 0.608232 |
| 2025-2026 | 1312 | 0.564024 |

## Conclusion
This cycle **did not improve overall accuracy** versus the previous best roster-aware model (0.595020 vs 0.597180, delta -0.002160). It did improve over baseline (0.578811).

## Key artifact paths
- `data\processed\walk_forward_selected_logistic_engineered_summary.json`
- `data\processed\walk_forward_selected_logistic_engineered_predictions.csv`
- `data\processed\walk_forward_experiment_summary.json`
- `data\processed\walk_forward_experiment_metrics_overall.csv`
- `data\processed\walk_forward_experiment_metrics_by_season.csv`
- `data\processed\improved_roster_aware_evaluation_summary.json`
