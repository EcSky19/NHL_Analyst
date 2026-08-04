# Wave-3 Experiment Summary

Date: 2026-08-03

## Scope
Ran deterministic walk-forward experiments on enriched wave3 features, then selected the canonical variant by: 1) highest accuracy, 2) lower log loss, 3) lower Brier score.

## Selection fairness guardrail
Compared only full-coverage variants with 3936 games; excluded 10 partial-coverage variants.

## Winner
- Selected variant: `logistic_engineered` (recency candidate `single`)
- Overall metrics (n=3936):
  - Accuracy: **0.592226**
  - Log loss: **0.661336**
  - Brier score: **0.234841**

## Comparison vs current SOTA
- Wave1 SOTA accuracy: **0.597561**
- Wave3 selected accuracy: **0.592226**
- Delta: **-0.005335** (did not beat)

## Selected by-season accuracy
- 2023-2024: 0.608994 (1312 games)
- 2024-2025: 0.608232 (1312 games)
- 2025-2026: 0.559451 (1312 games)

## Canonical Wave-3 artifacts
- `data\processed\quickwin_wave3\wave3_selected_variant_summary.json`
- `data\processed\quickwin_wave3\wave3_selected_predictions.csv`
- `data\processed\quickwin_wave3\wave3_selected_metrics_overall.csv`
- `data\processed\quickwin_wave3\wave3_selected_metrics_overall.json`
- `data\processed\quickwin_wave3\wave3_selected_metrics_by_season.csv`
- `data\processed\quickwin_wave3\wave3_selected_metrics_by_season.json`
- `data\processed\quickwin_wave3\wave3_variant_comparison.csv`

## Deterministic rerun command
```powershell
python .\scripts\run_walk_forward_experiments.py --require-roster-features --recency-selector-mode season_regime --recency-decay-mode hybrid_exponential --recency-season-half-life 1.0 --recency-game-half-life 650 --recency-min-weight 0.1 --output-predictions-csv .\data\processed\quickwin_wave3\wave3_full_matrix_predictions.csv --output-overall-csv .\data\processed\quickwin_wave3\wave3_full_matrix_metrics_overall.csv --output-by-season-csv .\data\processed\quickwin_wave3\wave3_full_matrix_metrics_by_season.csv --output-recency-comparison-csv .\data\processed\quickwin_wave3\wave3_full_matrix_comparison.csv --output-logistic-importance-csv .\data\processed\quickwin_wave3\wave3_full_matrix_logistic_importance.csv --output-summary-json .\data\processed\quickwin_wave3\wave3_full_matrix_summary.json
```
