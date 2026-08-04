# Wave-2 Experiment Summary

Date: 2026-08-03

## Scope
Executed the wave-2 walk-forward harness with roster features, interaction terms, fold-safe calibration/blending, and season-aware recency selector active.

## Winner
- Selected variant: `blend_logistic_weighted_70_30` (recency candidate `single`)
- Overall metrics (n=3936):
  - Accuracy: **0.590447**
  - Log loss: **0.662053**
  - Brier score: **0.235120**

## Selection rule
Primary rank by higher accuracy; tie-breakers by lower log loss, then lower Brier.

## Selected by-season accuracy
- 2023-2024: 0.606707 (1312 games)
- 2024-2025: 0.603659 (1312 games)
- 2025-2026: 0.560976 (1312 games)

## Canonical Wave-2 artifacts
- `data\processed\quickwin_wave2\wave2_selected_variant_summary.json`
- `data\processed\quickwin_wave2\wave2_selected_predictions.csv`
- `data\processed\quickwin_wave2\wave2_selected_metrics_overall.csv`
- `data\processed\quickwin_wave2\wave2_selected_metrics_overall.json`
- `data\processed\quickwin_wave2\wave2_selected_metrics_by_season.csv`
- `data\processed\quickwin_wave2\wave2_selected_metrics_by_season.json`
- `data\processed\quickwin_wave2\wave2_variant_comparison.csv`

## Deterministic rerun command
```powershell
python .\scripts\run_walk_forward_experiments.py --require-roster-features --recency-selector-mode season_regime --recency-decay-mode hybrid_exponential --recency-season-half-life 1.0 --recency-game-half-life 650 --recency-min-weight 0.1 --output-predictions-csv .\data\processed\quickwin_wave2\wave2_full_matrix_predictions.csv --output-overall-csv .\data\processed\quickwin_wave2\wave2_full_matrix_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave2\wave2_full_matrix_metrics_by_season.csv --output-recency-comparison-csv .\data\processed\quickwin_wave2\wave2_full_matrix_comparison.csv --output-logistic-importance-csv .\data\processed\quickwin_wave2\wave2_full_matrix_logistic_importance.csv --output-summary-json .\data\processed\quickwin_wave2\wave2_full_matrix_summary.json
```
