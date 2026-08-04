# Improved Roster-aware Model Evaluation

## Methodology
- Source: `data\processed\roster_aware_walk_forward_predictions.csv`.
- Predictions regenerated during this run: no.
- Deterministic metric definitions:
  - Accuracy = mean(is_correct_pick) with 0.5 threshold on home_win_probability.
  - Log loss = mean(-[y*ln(p_home)+(1-y)*ln(p_away)]), with probability clamp to [1e-6, 1-1e-6].
  - Brier score = mean((p_home - y)^2).

## Overall
- Games: 5248
- Accuracy: 0.5972
- Log loss: 0.6588
- Brier score: 0.2334
- Baseline accuracy: 0.5788
- Delta vs baseline: +0.0184 (+1.84 pp)

## Per-season
| Season | Games | Accuracy | Log loss | Brier score | Delta vs baseline |
|---|---:|---:|---:|---:|---:|
| 2022-2023 | 1312 | 0.6029 | 0.6692 | 0.2374 | +0.0241 |
| 2023-2024 | 1312 | 0.6174 | 0.6497 | 0.2288 | +0.0386 |
| 2024-2025 | 1312 | 0.6067 | 0.6447 | 0.2276 | +0.0279 |
| 2025-2026 | 1312 | 0.5617 | 0.6715 | 0.2400 | -0.0171 |

## Artifacts
- `data\processed\improved_roster_aware_evaluation_summary.json`
- `data\processed\improved_roster_aware_evaluation_by_season.csv`
- `data\processed\improved_roster_aware_vs_baseline_comparison.csv`
- `data\reports\improved_roster_aware_evaluation_report.md`
- SQLite tables in `data\processed\nhl_research.db`: `improved_roster_aware_evaluation_summary`, `improved_roster_aware_evaluation_by_season`
