# exec-nonlinear-variant

## Done
- Added deterministic nonlinear variant integration in `scripts\run_walk_forward_experiments.py`:
  - Tries LightGBM first, then XGBoost, then deterministic internal tree-ensemble fallback.
  - In this environment, chosen backend: `deterministic_tree_ensemble_fallback` (`bagged_cart_trees`).
- Integrated nonlinear family into variant matrix and blend variants:
  - Base variant: `nonlinear_tree`
  - Added static blends: `blend_nonlinear_logistic_50_50`, `blend_nonlinear_weighted_60_40`
  - Included nonlinear family in fold-local validated top-3 blends.
- Kept leakage-safe setup unchanged:
  - Same season-expanding folds
  - Fold-local train/validation calibration/tuning only
  - No test-season leakage in model fitting.
- Extended output schemas (CSV + SQLite summary tables) with:
  - `nonlinear_model_backend`
  - `nonlinear_model_style`

## Artifacts
- `data\processed\execution_plan\phase2\nonlinear_predictions.csv`
- `data\processed\execution_plan\phase2\nonlinear_metrics_overall.csv`
- `data\processed\execution_plan\phase2\nonlinear_metrics_by_season.csv`
- `data\processed\execution_plan\phase2\nonlinear_recency_comparison.csv`
- `data\processed\execution_plan\phase2\nonlinear_logistic_importance.csv`
- `data\processed\execution_plan\phase2\nonlinear_calibration_diagnostics.csv`
- `data\processed\execution_plan\phase2\nonlinear_summary.json`

## Key metrics (overall, recency candidate `single`)
- `nonlinear_tree`: accuracy `0.553100`, log_loss `0.683355`, brier `0.245132`
- `logistic_engineered`: accuracy `0.590193`, log_loss `0.659290`, brier `0.233973`
- Best overall variant: `blend_top3_fixed_50_30_20__logistic_engineered__elo_form_tuned__weighted_calibrated`
  - accuracy `0.602896`, log_loss `0.660289`, brier `0.234005`

## Needs work
- Optional: install/enable LightGBM or XGBoost in runtime to benchmark boosted-tree backend against current deterministic fallback.

## Blockers
- None.
