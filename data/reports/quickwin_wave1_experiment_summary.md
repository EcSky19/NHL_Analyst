# Quick-Win Wave 1 Experiment Summary

Date: 2026-08-03

## Scope
Executed the walk-forward harness with quick-win improvements active (recency weighting modes, fold-safe calibrator selection, and deterministic blend variants), then selected a canonical winner by:
1) highest accuracy, 2) lower log loss, 3) lower Brier score.

## Winner
- **Selected variant:** `logistic_engineered` with `recency_mode=hybrid_exponential`
- **Overall metrics (n=3936):**
  - Accuracy: **0.597561**
  - Log loss: **0.655001**
  - Brier score: **0.232060**

## Why this won
- It had the highest out-of-sample accuracy across all 28 evaluated `(recency_mode, model_id)` variants.
- It also improved over non-recency logistic (`0.597561` vs `0.595020`, +0.002541).
- Blend variants were competitive but did not beat top logistic accuracy.
- Weighted calibrated variants remained below logistic/blend families on accuracy.

## Canonical Wave-1 artifact bundle
- `data\processed\quickwin_wave1\wave1_selected_variant_summary.json`
- `data\processed\quickwin_wave1\wave1_selected_predictions.csv`
- `data\processed\quickwin_wave1\wave1_selected_metrics_overall.csv`
- `data\processed\quickwin_wave1\wave1_selected_metrics_overall.json`
- `data\processed\quickwin_wave1\wave1_selected_metrics_by_season.csv`
- `data\processed\quickwin_wave1\wave1_selected_metrics_by_season.json`
- Full ranking table: `data\processed\quickwin_wave1\wave1_variant_comparison.csv`

## Selected model by-season accuracy
- 2023-2024: 0.612805
- 2024-2025: 0.612043
- 2025-2026: 0.567835

## Deterministic rerun commands
```powershell
python .\scripts\run_walk_forward_experiments.py --recency-decay-mode none --output-predictions-csv .\data\processed\quickwin_wave1\walk_forward_none_predictions.csv --output-overall-csv .\data\processed\quickwin_wave1\walk_forward_none_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave1\walk_forward_none_metrics_by_season.csv --output-summary-json .\data\processed\quickwin_wave1\walk_forward_none_summary.json
python .\scripts\run_walk_forward_experiments.py --recency-decay-mode season_exponential --output-predictions-csv .\data\processed\quickwin_wave1\walk_forward_season_exponential_predictions.csv --output-overall-csv .\data\processed\quickwin_wave1\walk_forward_season_exponential_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave1\walk_forward_season_exponential_metrics_by_season.csv --output-summary-json .\data\processed\quickwin_wave1\walk_forward_season_exponential_summary.json
python .\scripts\run_walk_forward_experiments.py --recency-decay-mode game_exponential --output-predictions-csv .\data\processed\quickwin_wave1\walk_forward_game_exponential_predictions.csv --output-overall-csv .\data\processed\quickwin_wave1\walk_forward_game_exponential_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave1\walk_forward_game_exponential_metrics_by_season.csv --output-summary-json .\data\processed\quickwin_wave1\walk_forward_game_exponential_summary.json
python .\scripts\run_walk_forward_experiments.py --recency-decay-mode hybrid_exponential --output-predictions-csv .\data\processed\quickwin_wave1\walk_forward_hybrid_exponential_predictions.csv --output-overall-csv .\data\processed\quickwin_wave1\walk_forward_hybrid_exponential_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave1\walk_forward_hybrid_exponential_metrics_by_season.csv --output-summary-json .\data\processed\quickwin_wave1\walk_forward_hybrid_exponential_summary.json
```
