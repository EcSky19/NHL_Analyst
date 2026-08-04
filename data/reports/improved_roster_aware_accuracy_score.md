# Improved Roster-Aware Accuracy Score

- **Overall improved accuracy:** `0.597180` (59.7180%)
- **Improvement vs prior baseline:** `+0.018369` (+1.8369 percentage points) over baseline `0.578811`
- **Total games evaluated:** `5248`

## Per-season improved accuracies
- `2022-2023`: `0.602896`
- `2023-2024`: `0.617378`
- `2024-2025`: `0.606707`
- `2025-2026`: `0.561738`

## Methodology (concise)
Evaluation uses walk-forward, roster-aware predictions where each game prediction is computed from information available **before that game** (roster-before-game features), with no future-game leakage into feature construction or scoring. Accuracy is computed deterministically with a 0.5 threshold.

## Key artifacts
- `data\processed\improved_roster_aware_evaluation_summary.json`
- `data\processed\improved_roster_aware_evaluation_by_season.csv`
- `data\processed\improved_roster_aware_vs_baseline_comparison.csv`
- `data\processed\roster_aware_walk_forward_predictions.csv`
- `data\reports\improved_roster_aware_evaluation_report.md`
