# Exec Recency Retune (phase1)

Date: 2026-08-04

## Scope
- Extended `scripts\run_walk_forward_experiments.py` recency framework with:
  - deterministic drift grid profile: `drift_2025_2026`
  - strengthened fold-local selector mode: `season_regime_drift`
  - optional fast retune scope (`--model-scope logistic_only`) for grid iteration
- Executed deterministic recency sweep outputs to:
  - `data\processed\execution_plan\phase1\recency_*`

## Best candidate (from executed retune run)
- Candidate: `sweep_001`
- Model: `logistic_engineered`
- Recency config (selected fold-local): `mode=none, season_half_life=1.0, game_half_life=1.0, min_weight=1.0`
- Overall (3936 games):
  - Accuracy: **0.590193**
  - Log loss: **0.659290**
  - Brier: **0.233973**

## Comparison vs current SOTA
- Current SOTA accuracy: **0.597561**
- Retune best accuracy: **0.590193**
- Delta vs SOTA: **-0.007368**

## By-season accuracy (best candidate)
- 2023-2024: 0.608994
- 2024-2025: 0.598323
- 2025-2026: 0.563262

## Leakage controls
- Season-expanding folds (train seasons strictly before test season)
- Fold-local recency selector applied from train-season regime only
- Fold-local scaler/tuning retained in training scope only
