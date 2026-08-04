# Out-of-sample Blending: logistic_engineered + improved_roster_aware

## Setup
- Inputs:
  - `data\processed\walk_forward_selected_logistic_engineered_predictions.csv`
  - `data\processed\roster_aware_walk_forward_predictions.csv`
- Overlap used: games present in both sources.
- Fold-safe weighting: for each test season, blend weights are selected only from earlier-seasons validation games.
- Deterministic candidates:
  - fixed: 50/50, 55/45, 60/40, 65/35, 70/30 (logistic/improved)
  - validated: per-season best from the same deterministic grid on prior-season validation only.

## Best model
- Model: `blend_fixed_50_50`
- Games: 3936
- Accuracy: 0.593242
- Log loss: 0.654813
- Brier score: 0.231946

## Overall metrics (all candidates)
| Model | Games | Accuracy | Log loss | Brier score |
|---|---:|---:|---:|---:|
| blend_fixed_50_50 | 3936 | 0.593242 | 0.654813 | 0.231946 |
| blend_fold_validated_logistic_improved | 3936 | 0.593242 | 0.654813 | 0.231946 |
| blend_fixed_55_45 | 3936 | 0.594004 | 0.654822 | 0.231953 |
| blend_fixed_60_40 | 3936 | 0.594258 | 0.654841 | 0.231964 |
| blend_fixed_65_35 | 3936 | 0.595020 | 0.654870 | 0.231980 |
| blend_fixed_70_30 | 3936 | 0.595783 | 0.654908 | 0.232000 |
| improved_roster_aware | 3936 | 0.595274 | 0.655302 | 0.232128 |
| logistic_engineered | 3936 | 0.595020 | 0.655350 | 0.232216 |

## Fold-safe validation diagnostics
- Seasons evaluated: 20232024, 20242025, 20252026
- First season fallback (no prior validation): `blend_fixed_50_50`
- Per-season selected weights and validation sample sizes are stored in diagnostics JSON.

## Artifacts
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\phase1\blend_metrics_by_season.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\phase1\blend_diagnostics.json`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\phase1\blend_metrics_overall.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\phase1\blend_predictions.csv`
- `C:\Users\t-ecoskay\Sports_analytics\data\reports\exec_oos_blending.md`
- `C:\Users\t-ecoskay\Sports_analytics\data\processed\execution_plan\phase1\blend_summary.json`
