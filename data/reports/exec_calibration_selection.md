# Execution calibration selection report

## Scope
Implemented fold-safe calibration selector upgrades in `scripts\run_walk_forward_experiments.py`:
- Added `CalibrationConfig` and CLI tuning knobs.
- Added selector modes: `static`, `season_aware`, `season_regime`.
- Kept strict fold-local fitting: calibrators fit only on calibration-fit rows from the fold training window, selected on fold-local validation rows, then refit on fold-train before fold-test scoring.
- Added diagnostics outputs (`*_diagnostics.csv`) and richer fold summary JSON fields (`selector_mode`, `selector_view`, per-view metrics, validation seasons, objective settings).

## Experiments run
Data source for this phase: `data\processed\execution_plan\phase1\calibration_sample.db` (900 sampled games, 180 per season across 5 seasons).

Artifacts:
- `data\processed\execution_plan\phase1\calibration_static_*`
- `data\processed\execution_plan\phase1\calibration_season_aware_*`
- `data\processed\execution_plan\phase1\calibration_regime_*`

## Weighted-calibrated variant impact (overall)
| Selector | Accuracy | LogLoss | Brier |
|---|---:|---:|---:|
| static | 0.525926 | 0.689991 | 0.248453 |
| season_aware | 0.514815 | 0.733508 | 0.249408 |
| season_regime | 0.514815 | 0.733508 | 0.249408 |

## Delta vs static (weighted_calibrated)
| Selector | Δ Accuracy | Δ LogLoss | Δ Brier |
|---|---:|---:|---:|
| season_aware | -0.011111 | +0.043517 | +0.000955 |
| season_regime | -0.011111 | +0.043517 | +0.000955 |

## Diagnostics highlights
- `static`: selected `platt` in all folds.
- `season_aware`: selected `isotonic` for 20232024, then `platt` for 20242025 and 20252026.
- `season_regime`: same selections as season_aware on this sampled run (`regime_late_window` view used).

## Recommendation
For this sampled phase-1 calibration run, keep `platt` as default (`--calibration-selector-mode static`) because it delivered better logloss/brier and higher accuracy than the season/regime-aware selector outcomes.
